import asyncio
import datetime
import json
import logging
import time

import aiohttp
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from homeassistant import core
from homeassistant.core import callback
from custom_components.oig_cloud.api.oig_cloud_config import OIGCloudConfig
from custom_components.oig_cloud.api.oig_cloud_authenticator import (
    OigClassAuthenticator,
)
from custom_components.oig_cloud.const import (
    OIG_BASE_URL,
    OIG_GET_STATS_URL,
    OIG_SET_BATT_FORMATTING_URL,
    OIG_SET_GRID_DELIVERY_URL,
    OIG_SET_MODE_URL,
)

from custom_components.oig_cloud.exceptions import (
    OigApiCallError,
    OigNoTelemetryException,
)


tracer = trace.get_tracer(__name__)

lock = asyncio.Lock()


class OigCloudApi:
    # OIG_BASE_URL = "https://www.oigpower.cz/cez/"
    # OIG_LOGIN_URL = "inc/php/scripts/Login.php"
    # OIG_GET_STATS_URL = "json.php"
    # OIG_SET_MODE_URL = "inc/php/scripts/Device.Set.Value.php"
    # OIG_SET_GRID_DELIVERY_URL = "inc/php/scripts/ToGrid.Toggle.php"
    # OIG_SET_BATT_FORMATTING_URL = "inc/php/scripts/Battery.Format.Save.php"

    call_in_progress: bool = False
    box_id: str = None

    def __init__(
        self, username: str, password: str, no_telemetry: bool, _: core.HomeAssistant
    ) -> None:
        with tracer.start_as_current_span("initialize"):
            self._no_telemetry = no_telemetry
            self._logger = logging.getLogger(__name__)

            self._last_update = datetime.datetime(1, 1, 1, 0, 0)

            config: OIGCloudConfig = OIGCloudConfig(username, password)
            self.authenticator = OigClassAuthenticator(config, self._logger)

            self.last_state = None
            self.expected_state = {}

            self._logger.debug("OigCloud initialized")

    def get_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            headers={"Cookie": f"PHPSESSID={self.authenticator.config.phpsessid}"}
        )

    async def get_stats(self) -> object:
        async with lock:
            current_time = datetime.datetime.now()
            if (current_time - self._last_update).total_seconds() < 30:
                self._logger.debug("Using cached stats")
                return self.last_state
            with tracer.start_as_current_span("get_stats"):
                try:
                    to_return: object = None
                    try:
                        to_return = await self._get_stats_internal()
                    except Exception:
                        self._logger.debug("Retrying authentication")
                        if await self.authenticator.authenticate():
                            to_return = await self._get_stats_internal()
                    self._logger.debug("Retrieved stats")
                    if self.box_id is None:
                        self.box_id = list(to_return.keys())[0]

                    self._last_update = datetime.datetime.now()
                    self._logger.debug(f"Last update: {self._last_update}")
                    return to_return
                except Exception as exception:
                    self._logger.error(f"Error: {exception}", stack_info=True)
                    raise exception

    async def _get_stats_internal(self, dependent: bool = False) -> object:
        with tracer.start_as_current_span("get_stats_internal"):
            to_return: object = None
            self._logger.debug("Starting session")
            async with self.get_session() as session:
                url = OIG_BASE_URL + OIG_GET_STATS_URL
                self._logger.debug(f"Getting stats from {url}")
                with tracer.start_as_current_span(
                    "get_stats_internal.get",
                    kind=SpanKind.SERVER,
                    attributes={"http.url": url, "http.method": "GET"},
                ):
                    async with session.get(url) as response:
                        if response.status == 200:
                            to_return = await response.json()
                            # the response should be a json dictionary, otherwise it's an error
                            if not isinstance(to_return, dict) and not dependent:
                                self._logger.info("Retrying authentication")
                                if await self.authenticator.authenticate():
                                    second_try = await self._get_stats_internal(True)
                                    if not isinstance(second_try, dict):
                                        self._logger.warning(f"Error: {second_try}")
                                        return None
                                    else:
                                        to_return = second_try
                                else:
                                    return None
                        self.last_state = to_return
                        self._logger.debug("Retrieved stats internal finished")
                    return to_return

    async def set_box_mode(self, mode: str) -> bool:
        """
        Sets the mode of the box.

        Args:
            mode (str): The mode to set the box to.

        Returns:
            bool: True if the mode was set successfully, False otherwise.
        """
        with tracer.start_as_current_span("set_mode"):
            try:
                if self.call_in_progress:
                    self._logger.warning("Another call in progress, aborting...")
                    return False
                self._logger.debug("Setting mode to %s", mode)
                return await self._set_box_params_internal("box_prms", "mode", mode)
            except Exception as error:
                self._logger.error("Error: %s", error, stack_info=True)
                raise error
            finally:
                self.call_in_progress = False

    async def set_grid_delivery_limit(self, limit: int) -> bool:
        with tracer.start_as_current_span("set_grid_delivery_limit"):
            try:
                if self.call_in_progress:
                    self._logger.warning("Another call in progress, aborting...")
                    return False
                self._logger.debug("Setting grid delivery limit to %s", limit)
                return await self._set_box_params_internal(
                    "invertor_prm1", "p_max_feed_grid", limit
                )
            except Exception as error:
                self._logger.error("Error: %s", error, stack_info=True)
                raise error
            finally:
                self.call_in_progress = False

    async def set_boiler_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_boiler_mode"):
            try:
                if self.call_in_progress:
                    self._logger.warning("Another call in progress, aborting...")
                    return False
                self._logger.debug("Setting boiler mode to %s", mode)
                return await self._set_box_params_internal(
                    "boiler_prms", "manual", mode
                )
            except Exception as error:
                self._logger.error("Error: %s", error, stack_info=True)
                raise error
            finally:
                self.call_in_progress = False

    async def _set_box_params_internal(
        self, table: str, column: str, value: str
    ) -> bool:
        with tracer.start_as_current_span("set_box_params_internal"):
            async with self.get_session() as session:
                data = json.dumps(
                    {
                        "id_device": self.box_id,
                        "table": table,
                        "column": column,
                        "value": value,
                    }
                )
                _nonce = int(time.time() * 1000)
                target_url = f"{OIG_BASE_URL}{OIG_SET_MODE_URL}?_nonce={_nonce}"

                self._logger.debug(
                    "Sending mode request to %s with %s",
                    target_url,
                    data.replace(self.box_id, "xxxxxx"),
                )

                with tracer.start_as_current_span(
                    "set_box_params_internal.post",
                    kind=SpanKind.SERVER,
                    attributes={"http.url": target_url, "http.method": "POST"},
                ):
                    async with session.post(
                        target_url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        responsecontent = await response.text()
                        if response.status == 200:
                            response_json = json.loads(responsecontent)
                            message = response_json[0][2]
                            self._logger.info(f"Response: {message}")
                            return True
                        raise Exception(
                            f"Error setting mode: {response.status}",
                            responsecontent,
                        )

    async def set_grid_delivery(self, mode: int) -> bool:
        with tracer.start_as_current_span("set_grid_delivery"):
            try:
                self._check_telemetry_or_throw()
                if self.call_in_progress:
                    self._logger.warning("Another call in progress, aborting...")
                    return False
                self._logger.debug(f"Setting grid delivery to {mode}")
                async with self.get_session() as session:
                    data = json.dumps(
                        {
                            "id_device": self.box_id,
                            "value": mode,
                        }
                    )

                    _nonce = int(time.time() * 1000)
                    target_url = (
                        f"{OIG_BASE_URL}{OIG_SET_GRID_DELIVERY_URL}?_nonce={_nonce}"
                    )
                    self._logger.info(
                        f"Sending grid delivery request to {target_url} for {data.replace(self.box_id, 'xxxxxx')}"
                    )
                    with tracer.start_as_current_span(
                        "set_grid_delivery.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": target_url, "http.method": "POST"},
                    ):
                        async with session.post(
                            target_url,
                            data=data,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            responsecontent = await response.text()
                            if response.status == 200:
                                response_json = json.loads(responsecontent)
                                self._logger.debug(f"Response: {response_json}")
                                return True

                            raise OigApiCallError(
                                "Error setting grid delivery",
                                response.status,
                                responsecontent,
                            )
            except Exception as error:
                self._logger.error(f"Error: {error}", stack_info=True)
                raise error
            finally:
                self.call_in_progress = False

    async def set_formating_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_formating_battery"):
            try:
                if self.call_in_progress:
                    self._logger.warning("Another call in progress, aborting...")
                    return False
                self._logger.debug("Setting grid delivery to battery %s", mode)
                async with self.get_session() as session:
                    data = json.dumps(
                        {
                            "bat_ac": mode,
                        }
                    )

                    _nonce = int(time.time() * 1000)
                    target_url = (
                        f"{OIG_BASE_URL}{OIG_SET_BATT_FORMATTING_URL}?_nonce={_nonce}"
                    )
                    self._logger.info(
                        "Sending grid battery delivery request to %s for %s",
                        target_url,
                        data.replace(self.box_id, "xxxxxx"),
                    )
                    with tracer.start_as_current_span(
                        "set_formating_battery.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": target_url, "http.method": "POST"},
                    ):
                        async with session.post(
                            target_url,
                            data=data,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            responsecontent = await response.text()
                            if response.status == 200:
                                response_json = json.loads(responsecontent)
                                self._logger.debug(f"Response: {response_json}")

                                return True
                            raise Exception(
                                "Error setting set_formating_battery",
                                responsecontent,
                            )
            except Exception as error:
                self._logger.error(f"Error: {error}", stack_info=True)
                raise error
            finally:
                self.call_in_progress = False

    def _check_telemetry_or_throw(self):
        if self._no_telemetry:
            raise OigNoTelemetryException(
                "Tato funkce je ve vývoji a proto je momentálně dostupná pouze pro systémy s aktivní telemetrií"
            )

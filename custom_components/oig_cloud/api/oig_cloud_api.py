import asyncio
import datetime
import json
import logging
import time
from typing import Any, Dict, Optional, Union, cast

import aiohttp
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from homeassistant import core

from ..models import OigCloudData, OigCloudDeviceData

tracer = trace.get_tracer(__name__)

# Using a lock to prevent multiple simultaneous API calls
lock = asyncio.Lock()


class OigCloudApiError(Exception):
    """Exception for OIG Cloud API errors."""


class OigCloudAuthError(OigCloudApiError):
    """Exception for authentication errors."""


class OigCloudApi:
    _base_url = "https://www.oigpower.cz/cez/"
    _login_url = "inc/php/scripts/Login.php"
    _get_stats_url = "json.php"
    _set_mode_url = "inc/php/scripts/Device.Set.Value.php"
    _set_grid_delivery_url = "inc/php/scripts/ToGrid.Toggle.php"
    _set_batt_formating_url = "inc/php/scripts/Battery.Format.Save.php"

    def __init__(
        self,
        username: str,
        password: str,
        no_telemetry: bool,
        hass: core.HomeAssistant,
        standard_scan_interval: int = 30,
    ) -> None:
        self._no_telemetry = no_telemetry
        self._logger = logging.getLogger(__name__)
        self._last_update = datetime.datetime(1, 1, 1, 0, 0)
        self._username = username
        self._password = password
        self._standard_scan_interval = standard_scan_interval
        self.last_state = None
        self.box_id = None
        self._logger.debug("OigCloud initialized")

    async def authenticate(self) -> bool:
        """Authenticate with the OIG Cloud API."""
        with tracer.start_as_current_span("authenticate") as span:
            try:
                login_command: Dict[str, str] = {
                    "email": self._username,
                    "password": self._password,
                }
                self._logger.debug("Authenticating with OIG Cloud")

                async with aiohttp.ClientSession() as session:
                    url: str = self._base_url + self._login_url
                    data: str = json.dumps(login_command)
                    headers: Dict[str, str] = {"Content-Type": "application/json"}

                    with tracer.start_as_current_span(
                        "authenticate.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": url, "http.method": "POST"},
                    ):
                        async with session.post(
                            url, data=data, headers=headers
                        ) as response:
                            responsecontent = await response.text()
                            span.add_event(
                                "Received auth response",
                                {
                                    "response": responsecontent,
                                    "status": response.status,
                                },
                            )
                            if response.status == 200:
                                if responsecontent == '[[2,"",false]]':
                                    self._phpsessid = (
                                        session.cookie_jar.filter_cookies(
                                            self._base_url
                                        )
                                        .get("PHPSESSID")
                                        .value
                                    )
                                    return True

                            raise OigCloudAuthError("Authentication failed")
            except OigCloudAuthError as e:
                self._logger.error(f"Authentication error: {e}", stack_info=True)
                raise
            except Exception as e:
                self._logger.error(
                    f"Unexpected error during authentication: {e}", stack_info=True
                )
                raise OigCloudAuthError(f"Authentication failed: {e}") from e

    def get_session(self) -> aiohttp.ClientSession:
        """Get a session with authentication cookies."""
        if not self._phpsessid:
            raise OigCloudAuthError("Not authenticated, call authenticate() first")

        return aiohttp.ClientSession(headers={"Cookie": f"PHPSESSID={self._phpsessid}"})

    async def get_stats(self) -> Dict[str, Any]:
        """Get stats from the OIG Cloud API with caching."""
        async with lock:
            current_time = datetime.datetime.now()
            if (
                current_time - self._last_update
            ).total_seconds() < self._standard_scan_interval:
                self._logger.debug("Using cached stats")
                return self.last_state
            with tracer.start_as_current_span("get_stats") as span:
                try:
                    to_return = await self._try_get_stats()
                    self._logger.debug("Retrieved stats")
                    if self.box_id is None and to_return:
                        self.box_id = list(to_return.keys())[0]
                    self._last_update = datetime.datetime.now()
                    self.last_state = to_return
                    return to_return
                except Exception as e:
                    self._logger.error(f"Unexpected error: {e}", stack_info=True)
                    raise OigCloudApiError(f"Failed to get stats: {e}") from e

    async def _try_get_stats(self, dependent: bool = False) -> object:
        with tracer.start_as_current_span("get_stats_internal"):
            async with self.get_session() as session:
                url = self._base_url + self._get_stats_url
                self._logger.debug(f"Getting stats from {url}")
                async with session.get(url) as response:
                    if response.status == 200:
                        result = await response.json()
                        if not isinstance(result, dict) and not dependent:
                            self._logger.info("Retrying authentication")
                            if await self.authenticate():
                                return await self._try_get_stats(True)
                            return None
                        return result
                    else:
                        raise Exception(
                            f"Failed to fetch stats, status {response.status}"
                        )

    async def set_box_mode(self, mode: str) -> bool:
        """Set box mode (Home 1, Home 2, etc.)."""
        with tracer.start_as_current_span("set_mode") as span:
            try:
                self._logger.debug(f"Setting box mode to {mode}")
                return await self.set_box_params_internal("box_prms", "mode", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_grid_delivery_limit(self, limit: int) -> bool:
        with tracer.start_as_current_span("set_grid_delivery_limit") as span:
            try:
                self._logger.debug(f"Setting grid delivery limit to {limit}")
                return await self.set_box_params_internal(
                    "invertor_prm1", "p_max_feed_grid", limit
                )
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_boiler_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_boiler_mode") as span:
            try:
                self._logger.debug(f"Setting boiler mode to {mode}")
                return await self.set_box_params_internal("boiler_prms", "manual", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_ssr_rele_1(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_ssr_rele_1") as span:
            try:
                self._logger.debug(f"Setting SSR 1 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr0", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_ssr_rele_2(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_ssr_rele_2") as span:
            try:
                self._logger.debug(f"Setting SSR 2 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr1", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_ssr_rele_3(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_ssr_rele_3") as span:
            try:
                self._logger.debug(f"Setting SSR 3 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr2", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_box_params_internal(
        self, table: str, column: str, value: str
    ) -> bool:
        with tracer.start_as_current_span("set_box_params_internal") as span:
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
                target_url = f"{self._base_url}{self._set_mode_url}?_nonce={_nonce}"

                self._logger.debug(
                    f"Sending mode request to {target_url} with {data.replace(self.box_id, 'xxxxxx')}"
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
                        response_content = await response.text()
                        if response.status == 200:
                            response_json = json.loads(response_content)
                            message = response_json[0][2]
                            self._logger.info(f"Response: {message}")
                            return True
                        else:
                            raise Exception(
                                f"Error setting mode: {response.status}",
                                response_content,
                            )

    async def set_grid_delivery(self, mode: int) -> bool:
        """Set grid delivery mode."""
        with tracer.start_as_current_span("set_grid_delivery") as span:
            try:
                if self._no_telemetry:
                    raise OigCloudApiError(
                        "Tato funkce je ve vývoji a proto je momentálně dostupná pouze pro systémy s aktivní telemetrií."
                    )

                self._logger.debug(f"Setting grid delivery to mode {mode}")

                if not self.box_id:
                    raise OigCloudApiError("Box ID not available, fetch stats first")

                async with self.get_session() as session:
                    data: str = json.dumps(
                        {
                            "id_device": self.box_id,
                            "value": mode,
                            "value": mode,
                        }
                    )

                    _nonce: int = int(time.time() * 1000)
                    target_url: str = (
                        f"{self._base_url}{self._set_grid_delivery_url}?_nonce={_nonce}"
                    )

                    # Log with redacted box_id for security
                    self._logger.info(
                        f"Sending grid delivery request to {target_url} for {data.replace(str(self.box_id), 'xxxxxx')}"
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
                            response_content: str = await response.text()

                            if response.status == 200:
                                response_json = json.loads(response_content)
                                self._logger.debug(f"API response: {response_json}")
                                return True
                            else:
                                raise OigCloudApiError(
                                    f"Error setting grid delivery: {response.status} - {response_content}"
                                )
            except OigCloudApiError:
                raise
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    # Funkce na nastavení nabíjení baterie z gridu
    async def set_battery_formating(self, mode: str, limit: int) -> bool:
        with tracer.start_as_current_span("set_batt_formating") as span:
            try:
                self._logger.debug(f"Setting formatting battery to {limit} percent")
                async with self.get_session() as session:
                    data = json.dumps(
                        {
                            "id_device": self.box_id,
                            "column": "bat_ac",
                            "value": limit,
                        }
                    )

                    _nonce = int(time.time() * 1000)
                    target_url = f"{self._base_url}{self._set_batt_formating_url}?_nonce={_nonce}"

                    self._logger.debug(
                        f"Sending formatting battery request to {target_url} with {data.replace(self.box_id, 'xxxxxx')}"
                    )

                    with tracer.start_as_current_span(
                        "set_mode.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": target_url, "http.method": "POST"},
                    ):
                        async with session.post(
                            target_url,
                            data=data,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            response_content = await response.text()
                            if response.status == 200:
                                response_json = json.loads(response_content)
                                message = response_json[0][2]
                                self._logger.info(f"Response: {message}")
                                return True
                            else:
                                raise Exception(
                                    f"Error setting mode: {response.status}",
                                    response_content,
                                )
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise

    async def get_extended_stats(
        self, name: str, from_date: str, to_date: str
    ) -> object:
        with tracer.start_as_current_span("get_extended_stats") as span:
            try:
                async with self.get_session() as session:
                    url = self._base_url + "json2.php"
                    self._logger.debug(f"Requesting extended stats from {url}")

                    payload = {"name": name, "range": f"{from_date},{to_date},0"}
                    headers = {"Content-Type": "application/json"}

                    with tracer.start_as_current_span(
                        "get_extended_stats.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": url, "http.method": "POST"},
                    ):
                        async with session.post(
                            url, json=payload, headers=headers
                        ) as response:
                            if response.status == 200:
                                result = await response.json()
                                self._logger.debug(
                                    f"Extended stats '{name}' retrieved successfully"
                                )
                                return result
                            else:
                                raise Exception(
                                    f"Error fetching extended stats: {response.status}"
                                )
            except Exception as e:
                self._logger.error(f"Error in get_extended_stats: {e}", stack_info=True)
                raise e

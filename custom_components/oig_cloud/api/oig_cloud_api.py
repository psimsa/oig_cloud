import asyncio
import datetime
import json
import logging
import time

import aiohttp
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from homeassistant import core

tracer = trace.get_tracer(__name__)

lock = asyncio.Lock()


class OigCloudApi:
    _base_url = "https://www.oigpower.cz/cez/"
    _login_url = "inc/php/scripts/Login.php"
    _get_stats_url = "json.php"
    _set_mode_url = "inc/php/scripts/Device.Set.Value.php"
    _set_grid_delivery_url = "inc/php/scripts/ToGrid.Toggle.php"
    _set_batt_formating_url = "inc/php/scripts/Battery.Format.Save.php"

    def __init__(
        self, username: str, password: str, no_telemetry: bool, hass: core.HomeAssistant, standard_scan_interval: int = 30
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
        with tracer.start_as_current_span("authenticate") as span:
            try:
                login_command = {"email": self._username, "password": self._password}
                self._logger.debug("Authenticating")

                async with (aiohttp.ClientSession()) as session:
                    url = self._base_url + self._login_url
                    data = json.dumps(login_command)
                    headers = {"Content-Type": "application/json"}
                    with tracer.start_as_current_span(
                        "authenticate.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": url, "http.method": "POST"},
                    ):
                        async with session.post(url, data=data, headers=headers) as response:
                            responsecontent = await response.text()
                            span.add_event("Received auth response", {"response": responsecontent, "status": response.status})
                            if response.status == 200:
                                if responsecontent == '[[2,"",false]]':
                                    self._phpsessid = session.cookie_jar.filter_cookies(self._base_url).get("PHPSESSID").value
                                    return True
                            raise Exception("Authentication failed")
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    def get_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers={"Cookie": f"PHPSESSID={self._phpsessid}"})

    async def get_stats(self) -> object:
        async with lock:
            current_time = datetime.datetime.now()
            if (current_time - self._last_update).total_seconds() < self._standard_scan_interval:
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
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e

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
                        raise Exception(f"Failed to fetch stats, status {response.status}")

    async def set_box_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_mode") as span:
            try:
                self._logger.debug(f"Setting mode to {mode}")
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
                        responsecontent = await response.text()
                        if response.status == 200:
                            response_json = json.loads(responsecontent)
                            message = response_json[0][2]
                            self._logger.info(f"Response: {message}")
                            return True
                        else:
                            raise Exception(
                                f"Error setting mode: {response.status}",
                                responsecontent,
                            )

    async def set_grid_delivery(self, mode: int) -> bool:
        with tracer.start_as_current_span("set_grid_delivery") as span:
            try:
                if self._no_telemetry:
                    raise Exception(
                        "Tato funkce je ve vývoji a proto je momentálně dostupná pouze pro systémy s aktivní telemetrií."
                    )

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
                        f"{self._base_url}{self._set_grid_delivery_url}?_nonce={_nonce}"
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
                            else:
                                raise Exception(
                                    "Error setting grid delivery", responsecontent
                                )
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_formating_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_formating_battery") as span:
            try:
                self._logger.debug(f"Setting grid delivery to battery {mode}")
                async with self.get_session() as session:
                    data = json.dumps(
                        {
                           "bat_ac": mode,
                        }
                    )

                    _nonce = int(time.time() * 1000)
                    target_url = f"{self._base_url}{self._set_batt_formating_url}?_nonce={_nonce}"
                    self._logger.info(
                        f"Sending grid battery delivery request to {target_url} for {data.replace(self.box_id, 'xxxxxx')}"
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
                            else:
                                raise Exception(
                                    "Error setting set_formating_battery",
                                    responsecontent,
                                )
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e
                
    async def get_extended_stats(self, name: str, from_date: str, to_date: str) -> object:
        with tracer.start_as_current_span("get_extended_stats") as span:
            try:
                async with self.get_session() as session:
                    url = self._base_url + "json2.php"
                    self._logger.debug(f"Requesting extended stats from {url}")

                    payload = {
                        "name": name,
                        "range": f"{from_date},{to_date},0"
                    }
                    headers = {"Content-Type": "application/json"}

                    with tracer.start_as_current_span(
                        "get_extended_stats.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": url, "http.method": "POST"},
                    ):
                        async with session.post(url, json=payload, headers=headers) as response:
                            if response.status == 200:
                                result = await response.json()
                                self._logger.debug(f"Extended stats '{name}' retrieved successfully")
                                return result
                            else:
                                raise Exception(f"Error fetching extended stats: {response.status}")
            except Exception as e:
                self._logger.error(f"Error in get_extended_stats: {e}", stack_info=True)
                raise e

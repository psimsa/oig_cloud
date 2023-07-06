import asyncio
import datetime
import hashlib
import json
import logging
import time

import aiohttp
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from ..shared.logging import LOGGING_HANDLER

from homeassistant import core

tracer = trace.get_tracer(__name__)

lock = asyncio.Lock()


class OigCloudApi:
    _base_url = "https://www.oigpower.cz/cez/"
    _login_url = "inc/php/scripts/Login.php"
    _get_stats_url = "json.php"
    _set_mode_url = "inc/php/scripts/Device.Set.Value.php"
    _set_grid_delivery_url = "inc/php/scripts/ToGrid.Toggle.php"

    _username: str = None
    _password: str = None

    _phpsessid: str = None

    box_id: str = None

    def __init__(
        self, username: str, password: str, no_telemetry: bool, hass: core.HomeAssistant
    ) -> None:
        with tracer.start_as_current_span("initialize") as span:
            self._no_telemetry = no_telemetry
            self._logger = logging.getLogger(__name__)

            self._last_update = datetime.datetime(1, 1, 1, 0, 0)
            self._username = username
            self._password = password
            self._email_hash = hashlib.md5(self._username.encode("utf-8")).hexdigest()
            self._initialize_span()
            
            if not self._no_telemetry:
                span.set_attributes(
                    {
                        "hass.language": hass.config.language,
                        "hass.time_zone": hass.config.time_zone,
                    }
                )
                span.add_event("log", {"level": logging.INFO, "msg": "Initializing"})
                self._logger.info(f"Telemetry hash is {self._email_hash}")

            self.last_state = None
            self._logger.debug("OigCloud initialized")

    def _initialize_span(self):
        span = trace.get_current_span()
        if span:
            span.set_attributes(
                {
                    "email_hash": self._email_hash,
                }
            )

    async def authenticate(self) -> bool:
        with tracer.start_as_current_span("authenticate") as span:
            try:
                self._initialize_span()
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
                        async with session.post(
                            url,
                            data=data,
                            headers=headers,
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
                            raise Exception("Authentication failed")
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    def get_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers={"Cookie": f"PHPSESSID={self._phpsessid}"})

    async def get_stats(self) -> object:
        async with lock:
            current_time = datetime.datetime.now()
            if (current_time - self._last_update).total_seconds() < 10:
                self._logger.debug("Using cached stats")
                return self.last_state
            with tracer.start_as_current_span("get_stats") as span:
                try:
                    self._initialize_span()

                    to_return: object = None
                    try:
                        to_return = await self.get_stats_internal()
                    except:
                        self._logger.debug("Retrying authentication")
                        if await self.authenticate():
                            to_return = await self.get_stats_internal()
                    self._logger.debug("Retrieved stats")
                    if self.box_id is None:
                        self.box_id = list(to_return.keys())[0]

                    self._last_update = datetime.datetime.now()
                    self._logger.debug(f"Last update: {self._last_update}")
                    return to_return
                except Exception as e:
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e

    async def get_stats_internal(self, dependent: bool = False) -> object:
        with tracer.start_as_current_span("get_stats_internal"):
            self._initialize_span()
            to_return: object = None
            self._logger.debug("Starting session")
            async with self.get_session() as session:
                url = self._base_url + self._get_stats_url
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
                                if await self.authenticate():
                                    second_try = await self.get_stats_internal(True)
                                    if not isinstance(second_try, dict):
                                        self._logger.warn(f"Error: {second_try}")
                                        return None
                                    else:
                                        to_return = second_try
                                else:
                                    return None
                        self.last_state = to_return
                        self._logger.debug("Retrieved stats internal finished")
                    return to_return

    async def set_box_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_mode") as span:
            try:
                self._initialize_span()
                self._logger.debug(f"Setting mode to {mode}")
                async with self.get_session() as session:
                    data = json.dumps(
                        {
                            "id_device": self.box_id,
                            "table": "box_prms",
                            "column": "mode",
                            "value": mode,
                        }
                    )

                    _nonce = int(time.time() * 1000)
                    target_url = f"{self._base_url}{self._set_mode_url}?_nonce={_nonce}"

                    self._logger.debug(
                        f"Sending mode request to {target_url} with {data.replace(self.box_id, 'xxxxxx')}"
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
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_grid_delivery(self, enabled: bool) -> bool:
        with tracer.start_as_current_span("set_grid_delivery") as span:
            try:
                self._initialize_span()
                if self._no_telemetry:
                    raise Exception(
                        "Tato funkce je ve vývoji a proto je momentálně dostupná pouze pro systémy s aktivní telemetrií."
                    )

                self._logger.debug(f"Setting grid delivery to {enabled}")
                async with self.get_session() as session:
                    data = json.dumps(
                        {
                            "id_device": self.box_id,
                            "value": 1 if enabled else 0,
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

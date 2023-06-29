import hashlib
import json
import logging
import time

import aiohttp
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from homeassistant import core
from ..release_const import COMPONENT_VERSION, SERVICE_NAME
from ..shared.logging import debug, info, error, warning

resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
# processor = BatchSpanProcessor(
#     OTLPSpanExporter(
#         endpoint="https://otlp.eu01.nr-data.net",
#         insecure=False,
#         headers=[
#             (
#                 "api-key",
#                 "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
#             )
#         ],
#     )
# )

processor = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint="https://ingest.lightstep.com:443",
        insecure=False,
        headers=[
            (
                "lightstep-access-token",
                "pHuPl2wVZ6XXFPTscpzkD7TKyAh/TypqFiO7vvZhwmfSRyZo6rtGxtW+DbHwv9010LiguMogUti7E0WlrInJ2ev3mkn7oBhe/qbgznU6"
            )
        ],
    )
)

trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


class OigCloud:
    _base_url = "https://www.oigpower.cz/cez/"
    _login_url = "inc/php/scripts/Login.php"
    _get_stats_url = "json.php"
    _set_mode_url = "inc/php/scripts/Device.Set.Value.php"

    _username: str = None
    _password: str = None

    _phpsessid: str = None

    _box_id: str = None

    def __init__(
            self, username: str, password: str, no_telemetry: bool, hass: core.HomeAssistant
    ) -> None:
      with tracer.start_as_current_span("initialize") as span:

        self._username = username
        self._password = password
        self._no_telemetry = no_telemetry
        self._email_hash = hashlib.md5(self._username.encode("utf-8")).hexdigest()
        self._initialize_span()
        self._logger = logging.getLogger(__name__)

        if not self._no_telemetry:
                provider.add_span_processor(processor)

                span.set_attributes(
                    {
                        "hass.language": hass.config.language,
                        "hass.time_zone": hass.config.time_zone,
                    }
                )
                span.add_event("log", {"level": logging.INFO, "msg": "Initializing"})
                info(self._logger, f"Telemetry hash is {self._email_hash}")

        self.last_state = None
        debug(self._logger, "OigCloud initialized")

    def _initialize_span(self):
        span = trace.get_current_span()
        if span:
            span.set_attributes(
                {
                    "email_hash": self._email_hash,
                    "service.version": COMPONENT_VERSION,
                }
            )

    async def authenticate(self) -> bool:
        with tracer.start_as_current_span("authenticate") as span:
            self._initialize_span()
            login_command = {"email": self._username, "password": self._password}
            debug(self._logger, "Authenticating")
            async with (aiohttp.ClientSession()) as session:
                url = self._base_url + self._login_url
                data = json.dumps(login_command)
                headers = {"Content-Type": "application/json"}
                async with session.post(
                        url,
                        data=data,
                        headers=headers,
                ) as response:
                    responsecontent = await response.text()
                    span.add_event(
                        "Received auth response",
                        {"response": responsecontent, "status": response.status},
                    )
                    if response.status == 200:
                        if responsecontent == '[[2,"",false]]':
                            self._phpsessid = (
                                session.cookie_jar.filter_cookies(self._base_url)
                                .get("PHPSESSID")
                                .value
                            )
                            return True
                    return False

    def get_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers={"Cookie": f"PHPSESSID={self._phpsessid}"})

    async def get_stats(self) -> object:
        with tracer.start_as_current_span("get_stats") as span:
            self._initialize_span()
            to_return: object = None
            try:
                to_return = await self.get_stats_internal()
            except:
                debug(self._logger, "Retrying authentication")
                if await self.authenticate():
                    to_return = await self.get_stats_internal()
            debug(self._logger, "Retrieved stats")
        if self._box_id is None:
            self._box_id = list(to_return.keys())[0]
        return to_return

    async def get_stats_internal(self, dependent: bool = False) -> object:
        with tracer.start_as_current_span("get_stats_internal"):
            self._initialize_span()
            to_return: object = None
            async with self.get_session() as session:
                url = self._base_url + self._get_stats_url
                async with session.get(
                        url
                ) as response:
                    if response.status == 200:
                        to_return = await response.json()
                        # the response should be a json dictionary, otherwise it's an error
                        if not isinstance(to_return, dict) and not dependent:
                            info(self._logger, "Retrying authentication")
                            if await self.authenticate():
                                second_try = await self.get_stats_internal(True)
                                if not isinstance(second_try, dict):
                                    error(self._logger, f"Error: {second_try}")
                                    return None
                                else:
                                    to_return = second_try
                            else:
                                return None
                    self.last_state = to_return
                return to_return

    async def set_box_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_mode") as span:
            self._initialize_span()
            debug(self._logger, f"Setting mode to {mode}")
            async with self.get_session() as session:
                data = json.dumps(
                    {
                        "id_device": self._box_id,
                        "table": "box_prms",
                        "column": "mode",
                        "value": mode
                    }
                )

                _nonce = int(time.time() * 1000)
                target_url = f"{self._base_url}{self._set_mode_url}?_nonce={_nonce}"
                span.add_event(
                    "Sending mode request", {"data": data.replace(self._box_id, "xxxxxx"), "url": target_url}
                )
                async with session.post(
                        target_url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                ) as response:
                    responsecontent = await response.text()
                    if response.status == 200:
                        response_json = json.loads(responsecontent)
                        message = response_json[0][2]
                        info(self._logger, f"Response: {message}")
                        return True
                    else:
                        span.add_event("Error setting mode", {"response": responsecontent, "status": response.status})
                        return False

    async def set_grid_delivery(self, enabled: bool) -> bool:
        pass

import json
import logging
import aiohttp
import hashlib

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from .release_const import COMPONENT_VERSION, SERVICE_NAME

from homeassistant import core

resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint="https://otlp.eu01.nr-data.net",
        insecure=False,
        headers=[
            (
                "api-key",
                "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
            )
        ],
    )
)

trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


def info(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.INFO, msg=msg)


def debug(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.DEBUG, msg=msg)


def warning(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.WARNING, msg=msg)


def error(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.ERROR, msg=msg)


def log(logger: logging.Logger, level: int, msg: str):
    span = trace.get_current_span()
    if span:
        span.add_event("log", {"level": level, "msg": msg})

    logger.log(level=level, msg=msg)


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
        self._username = username
        self._password = password
        self._no_telemetry = no_telemetry
        self._email_hash = hashlib.md5(self._username.encode("utf-8")).hexdigest()
        self._logger = logging.getLogger(__name__)

        if not self._no_telemetry:
            provider.add_span_processor(processor)

            with tracer.start_as_current_span("initialize") as span:
                self._initialize_span()
                span.set_attributes(
                    {
                        "hass.language": hass.config.language,
                        "hass.time_zone": hass.config.time_zone,
                    }
                )
                span.add_event("log", {"level": logging.INFO, "msg": "Initializing"})
                self._logger.info(f"Telemetry hash is {self._email_hash}")

        self.last_state = None
        debug(self._logger, "OigCloud initialized")

    def _initialize_span(self):
        span = trace.get_current_span()
        if span:
            # span.set_attribute("email_hash", self.email_hash)
            # span.set_attribute("oig_cloud.version", COMPONENT_VERSION)
            span.set_attributes(
                {
                    "email_hash": self._email_hash,
                    "oig_cloud.version": COMPONENT_VERSION,
                }
            )

    async def authenticate(self) -> bool:
        with tracer.start_as_current_span("authenticate") as span:
            self._initialize_span()
            login_command = {"email": self._username, "password": self._password}

            debug(self._logger, "Authenticating")
            async with (aiohttp.ClientSession()) as session:
                async with session.post(
                        self._base_url + self._login_url,
                        data=json.dumps(login_command),
                        headers={"Content-Type": "application/json"},
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
                async with session.get(
                        self._base_url + self._get_stats_url
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
        # in c# the structure looks like this:
        # private record OigCommand(
        #   [property: JsonPropertyName("id_device")]
        #   string DeviceId,
        #   [property: JsonPropertyName("table")] string Table,
        #   [property: JsonPropertyName("column")] string Column,
        #   [property: JsonPropertyName("value")] string Value);
        # table will be box_prms, column will be mode, value will be the mode

        with tracer.start_as_current_span("set_mode") as span:
            self._initialize_span()
            debug(self._logger, f"Setting mode to {mode}")
            async with self.get_session() as session:
                async with session.post(
                        self._base_url + self._set_mode_url,
                        data=json.dumps(
                            {
                                "id_device": self._box_id,
                                "table": "box_prms",
                                "column": "mode",
                                "value": mode,
                            }
                        ),
                        headers={"Content-Type": "application/json"},
                ) as response:
                    responsecontent = await response.text()
                    span.add_event(
                        "Received mode response",
                        {"response": responsecontent, "status": response.status},
                    )
                    if response.status == 200:
                        return True
                    return False

    async def set_grid_delivery(self, enabled: bool) -> bool:
        pass

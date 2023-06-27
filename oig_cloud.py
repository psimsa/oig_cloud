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
    base_url = "https://www.oigpower.cz/cez/"
    login_url = "inc/php/scripts/Login.php"
    get_stats_url = "json.php"

    username: str = None
    password: str = None

    phpsessid: str = None

    def __init__(
        self, username: str, password: str, no_telemetry: bool, hass: core.HomeAssistant
    ) -> None:
        self.username = username
        self.password = password
        self.no_telemetry = no_telemetry
        self.email_hash = hashlib.md5(self.username.encode("utf-8")).hexdigest()
        self.logger = logging.getLogger(__name__)

        if not self.no_telemetry:
            provider.add_span_processor(processor)

            with tracer.start_as_current_span("initialize") as span:
                span.set_attributes(
                    {
                        "email_hash": self.email_hash,
                        "hass.language": hass.config.language,
                        "hass.time_zone": hass.config.time_zone,
                        "oig_cloud.version": COMPONENT_VERSION,
                    }
                )
                span.add_event("log", {"level": logging.INFO, "msg": "Initializing"})
                self.logger.info(f"Telemetry hash is {self.email_hash}")

        self.last_state = None
        debug(self.logger, "OigCloud initialized")

    async def authenticate(self) -> bool:
        with tracer.start_as_current_span("authenticate") as span:
            span.set_attribute("email_hash", self.email_hash)
            login_command = {"email": self.username, "password": self.password}

            debug(self.logger, "Authenticating")
            async with (aiohttp.ClientSession()) as session:
                async with session.post(
                    self.base_url + self.login_url,
                    data=json.dumps(login_command),
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status == 200:
                        responsecontent = await response.text()
                        if responsecontent == '[[2,"",false]]':
                            self.phpsessid = (
                                session.cookie_jar.filter_cookies(self.base_url)
                                .get("PHPSESSID")
                                .value
                            )
                            return True
                    return False

    def get_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers={"Cookie": f"PHPSESSID={self.phpsessid}"})

    async def get_stats(self) -> object:
        with tracer.start_as_current_span("get_stats") as span:
            span.set_attribute("email_hash", self.email_hash)
            to_return: object = None
            try:
                to_return = await self.get_stats_internal()
            except:
                debug(self.logger, "Retrying authentication")
                if await self.authenticate():
                    to_return = await self.get_stats_internal()
            debug(self.logger, "Retrieved stats")
        return to_return

    async def get_stats_internal(self, dependent: bool = False) -> object:
        with tracer.start_as_current_span("get_stats_internal"):
            to_return: object = None
            async with self.get_session() as session:
                async with session.get(self.base_url + self.get_stats_url) as response:
                    if response.status == 200:
                        to_return = await response.json()
                        # the response should be a json dictionary, otherwise it's an error
                        if not isinstance(to_return, dict) and not dependent:
                            info(self.logger, "Retrying authentication")
                            if await self.authenticate():
                                second_try = await self.get_stats_internal(True)
                                if not isinstance(second_try, dict):
                                    error(self.logger, f"Error: {second_try}")
                                    return None
                                else:
                                    to_return = second_try
                            else:
                                return None
                    self.last_state = to_return
                return to_return

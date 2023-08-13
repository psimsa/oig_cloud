import aiohttp
import json
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from custom_components.oig_cloud.api.oig_cloud_config import OIGCloudConfig
from custom_components.oig_cloud.const import OIG_BASE_URL, OIG_LOGIN_URL

class OigClassAuthenticator:
    
    config : OIGCloudConfig = None

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.tracer = trace.get_tracer(__name__)

    async def authenticate(self) -> bool:
        with self.tracer.start_as_current_span("authenticate") as span:
            try:
                login_command = {"email": self.config.username, "password": self.config.password}
                self.logger.debug("Authenticating")

                async with (aiohttp.ClientSession()) as session:
                    url = OIG_BASE_URL + OIG_LOGIN_URL
                    data = json.dumps(login_command)
                    headers = {"Content-Type": "application/json"}
                    with self.tracer.start_as_current_span(
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
                                    self.config.phpsessid = (
                                        session.cookie_jar.filter_cookies(
                                            OIG_BASE_URL
                                        )
                                        .get("PHPSESSID")
                                        .value
                                    )
                                    return True
                            raise Exception("Authentication failed")
            except Exception as exception:
                self.logger.error(f"Error: {exception}", stack_info=True)
                raise exception
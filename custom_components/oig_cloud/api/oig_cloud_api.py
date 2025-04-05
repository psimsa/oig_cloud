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
    """API client for OIG Cloud."""
    
    # API endpoints
    _base_url: str = "https://www.oigpower.cz/cez/"
    _login_url: str = "inc/php/scripts/Login.php"
    _get_stats_url: str = "json.php"
    _set_mode_url: str = "inc/php/scripts/Device.Set.Value.php"
    _set_grid_delivery_url: str = "inc/php/scripts/ToGrid.Toggle.php"
    _set_batt_formating_url: str = "inc/php/scripts/Battery.Format.Save.php"

    def __init__(
        self, username: str, password: str, no_telemetry: bool, hass: core.HomeAssistant
    ) -> None:
        """Initialize the API client."""
        with tracer.start_as_current_span("initialize") as span:
            self._no_telemetry: bool = no_telemetry
            self._logger: logging.Logger = logging.getLogger(__name__)
            self._username: str = username
            self._password: str = password
            self._phpsessid: Optional[str] = None
            self._last_update: datetime.datetime = datetime.datetime(1, 1, 1, 0, 0)
            
            # Track the state
            self.box_id: Optional[str] = None
            self.last_state: Optional[Dict[str, Any]] = None
            self.last_parsed_state: Optional[OigCloudData] = None
            
            self._logger.debug("OigCloud API client initialized")

    async def authenticate(self) -> bool:
        """Authenticate with the OIG Cloud API."""
        with tracer.start_as_current_span("authenticate") as span:
            try:
                login_command: Dict[str, str] = {"email": self._username, "password": self._password}
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
                            url,
                            data=data,
                            headers=headers,
                        ) as response:
                            response_content: str = await response.text()
                            span.add_event(
                                "Received auth response",
                                {
                                    "response": response_content,
                                    "status": response.status,
                                },
                            )
                            
                            if response.status == 200:
                                if response_content == '[[2,"",false]]':
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
                self._logger.error(f"Unexpected error during authentication: {e}", stack_info=True)
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
            
            # Use cache if data is less than 30 seconds old
            if (current_time - self._last_update).total_seconds() < 30 and self.last_state:
                self._logger.debug("Using cached stats (< 30s old)")
                return cast(Dict[str, Any], self.last_state)
                
            with tracer.start_as_current_span("get_stats") as span:
                try:
                    data: Optional[Dict[str, Any]] = None
                    
                    try:
                        data = await self.get_stats_internal()
                    except OigCloudAuthError:
                        self._logger.debug("Authentication failed, retrying...")
                        if await self.authenticate():
                            data = await self.get_stats_internal()
                        else:
                            raise OigCloudAuthError("Failed to authenticate after retry")
                    
                    self._logger.debug("Successfully retrieved stats")
                    
                    if data and self.box_id is None and data:
                        self.box_id = list(data.keys())[0]
                        
                    # Parse the data into our model
                    if data:
                        try:
                            self.last_parsed_state = OigCloudData.from_dict(data)
                        except (ValueError, KeyError) as e:
                            self._logger.warning(f"Error parsing API data: {e}")
                            
                    # Update last_update timestamp
                    self._last_update = datetime.datetime.now()
                    self._logger.debug(f"Updated stats timestamp: {self._last_update}")
                    
                    return data
                    
                except OigCloudApiError as e:
                    self._logger.error(f"API error: {e}", stack_info=True)
                    raise
                except Exception as e:
                    self._logger.error(f"Unexpected error: {e}", stack_info=True)
                    raise OigCloudApiError(f"Failed to get stats: {e}") from e

    async def get_stats_internal(self, dependent: bool = False) -> Dict[str, Any]:
        """Internal method to fetch stats from API without caching."""
        with tracer.start_as_current_span("get_stats_internal"):
            self._logger.debug("Starting API session")
            
            async with self.get_session() as session:
                url: str = self._base_url + self._get_stats_url
                self._logger.debug(f"Fetching stats from {url}")
                
                with tracer.start_as_current_span(
                    "get_stats_internal.get",
                    kind=SpanKind.SERVER,
                    attributes={"http.url": url, "http.method": "GET"},
                ):
                    async with session.get(url) as response:
                        if response.status == 200:
                            json_response: Any = await response.json()
                            
                            # The response should be a JSON dictionary, otherwise it's an error
                            if not isinstance(json_response, dict) and not dependent:
                                self._logger.info("Invalid response, retrying authentication")
                                
                                if await self.authenticate():
                                    second_try = await self.get_stats_internal(True)
                                    if not isinstance(second_try, dict):
                                        self._logger.warning(f"Error after retry: {second_try}")
                                        return {}
                                    else:
                                        self.last_state = second_try
                                        return second_try
                                else:
                                    return {}
                            else:
                                self.last_state = json_response
                        else:
                            raise OigCloudApiError(f"API returned status {response.status}")
                        
                        self._logger.debug("Retrieved stats successfully")
                        return cast(Dict[str, Any], self.last_state)

    async def set_box_mode(self, mode: str) -> bool:
        """Set box mode (Home 1, Home 2, etc.)."""
        with tracer.start_as_current_span("set_mode") as span:
            try:
                self._logger.debug(f"Setting box mode to {mode}")
                return await self.set_box_params_internal("box_prms", "mode", mode)
            except Exception as e:
                self._logger.error(f"Error setting box mode: {e}", stack_info=True)
                raise OigCloudApiError(f"Failed to set box mode: {e}") from e

    async def set_grid_delivery_limit(self, limit: int) -> bool:
        """Set grid delivery power limit."""
        with tracer.start_as_current_span("set_grid_delivery_limit") as span:
            try:
                self._logger.debug(f"Setting grid delivery limit to {limit}W")
                return await self.set_box_params_internal(
                    "invertor_prm1", "p_max_feed_grid", limit
                )
            except Exception as e:
                self._logger.error(f"Error setting grid delivery limit: {e}", stack_info=True)
                raise OigCloudApiError(f"Failed to set grid delivery limit: {e}") from e

    async def set_boiler_mode(self, mode: str) -> bool:
        """Set boiler mode (manual or automatic)."""
        with tracer.start_as_current_span("set_boiler_mode") as span:
            try:
                self._logger.debug(f"Setting boiler mode to {mode}")
                return await self.set_box_params_internal("boiler_prms", "manual", mode)
            except Exception as e:
                self._logger.error(f"Error setting boiler mode: {e}", stack_info=True)
                raise OigCloudApiError(f"Failed to set boiler mode: {e}") from e

    async def set_box_params_internal(
        self, table: str, column: str, value: Union[str, int]
    ) -> bool:
        """Set a specific box parameter."""
        with tracer.start_as_current_span("set_box_params_internal") as span:
            if not self.box_id:
                raise OigCloudApiError("Box ID not available, fetch stats first")
                
            async with self.get_session() as session:
                data: str = json.dumps(
                    {
                        "id_device": self.box_id,
                        "table": table,
                        "column": column,
                        "value": value,
                    }
                )
                _nonce: int = int(time.time() * 1000)
                target_url: str = f"{self._base_url}{self._set_mode_url}?_nonce={_nonce}"

                # Log with redacted box_id for security
                self._logger.debug(
                    f"Sending parameter update to {target_url} with {data.replace(str(self.box_id), 'xxxxxx')}"
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
                        response_content: str = await response.text()
                        
                        if response.status == 200:
                            response_json = json.loads(response_content)
                            message = response_json[0][2]
                            self._logger.info(f"API response: {message}")
                            return True
                        else:
                            raise OigCloudApiError(
                                f"Error setting parameter: {response.status} - {response_content}"
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
                self._logger.error(f"Error setting grid delivery: {e}", stack_info=True)
                raise OigCloudApiError(f"Failed to set grid delivery: {e}") from e

    async def set_formating_mode(self, mode: str) -> bool:
        """Set battery formatting mode."""
        with tracer.start_as_current_span("set_formating_battery") as span:
            try:
                self._logger.debug(f"Setting battery formatting mode to {mode}")
                
                async with self.get_session() as session:
                    data: str = json.dumps(
                        {
                           "bat_ac": mode,
                        }
                    )

                    _nonce: int = int(time.time() * 1000)
                    target_url: str = f"{self._base_url}{self._set_batt_formating_url}?_nonce={_nonce}"
                    
                    # Log with redacted box_id for security
                    self._logger.info(
                        f"Sending battery formatting request to {target_url}"
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
                            response_content: str = await response.text()
                            
                            if response.status == 200:
                                response_json = json.loads(response_content)
                                self._logger.debug(f"API response: {response_json}")
                                return True
                            else:
                                raise OigCloudApiError(
                                    f"Error setting battery formatting mode: {response.status} - {response_content}"
                                )
            except OigCloudApiError:
                raise
            except Exception as e:
                self._logger.error(f"Error setting battery formatting mode: {e}", stack_info=True)
                raise OigCloudApiError(f"Failed to set battery formatting mode: {e}") from e

    async def get_data(self) -> Dict[str, Any]:
        """Get the latest data as a Dictionary.
        
        This is the preferred method for getting data from the API.
        It returns the raw dictionary for compatibility with existing code.
        """
        with tracer.start_as_current_span("get_data") as span:
            try:
                # Get the raw data
                data = await self.get_stats()
                if not data:
                    self._logger.warning("No data received from API")
                    return {}
                
                return data
            except Exception as e:
                self._logger.error(f"Failed to get data: {e}")
                raise

    async def get_typed_data(self) -> Optional[OigCloudData]:
        """Get the latest data as a typed OigCloudData object.
        
        This returns the structured data model version of the API response.
        """
        with tracer.start_as_current_span("get_typed_data") as span:
            try:
                # Get the raw data
                data = await self.get_stats()
                if not data:
                    self._logger.warning("No data received from API")
                    return None
                
                # Convert to typed model
                return OigCloudData.from_dict(data)
            except Exception as e:
                self._logger.error(f"Failed to get typed data: {e}")
                raise

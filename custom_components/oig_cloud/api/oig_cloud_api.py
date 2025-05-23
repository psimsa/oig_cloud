import asyncio
import datetime
import json
import logging
import time
from typing import Any, Dict, Optional, Union, cast
import re

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
        self,
        username: str,
        password: str,
        no_telemetry: bool,
        hass: core.HomeAssistant, # hass is used for logging and event loop, but not explicitly typed here.
        standard_scan_interval: int = 30,
    ) -> None:
        """Initialize the API client."""
        with tracer.start_as_current_span("initialize") as span: # type: ignore
            self._no_telemetry: bool = no_telemetry
            self._logger: logging.Logger = logging.getLogger(__name__)
            self._username: str = username
            self._password: str = password
            self._phpsessid: Optional[str] = None

            self._last_update: datetime.datetime = datetime.datetime.min
            self._standard_scan_interval: int = standard_scan_interval
            self.box_id: Optional[str] = None
            self.last_state: Optional[Dict[str, Any]] = None
            self.last_parsed_state: Optional[OigCloudData] = None
            self._logger.debug("OigCloud initialized")

    async def authenticate(self) -> bool:
        """Authenticate with the OIG Cloud API."""
        with tracer.start_as_current_span("authenticate") as span: # type: ignore
            try:
                login_command: Dict[str, str] = {
                    "email": self._username,
                    "password": self._password,
                }
                self._logger.debug("Authenticating with OIG Cloud")

                async with aiohttp.ClientSession() as session:
                    url: str = f"{self._base_url}{self._login_url}"
                    data: str = json.dumps(login_command)
                    headers: Dict[str, str] = {"Content-Type": "application/json"}

                    with tracer.start_as_current_span( # type: ignore
                        "authenticate.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": url, "http.method": "POST"},
                    ):
                        async with session.post(
                            url, data=data, headers=headers
                        ) as response: # type: ignore
                            responsecontent: str = await response.text()
                            span.add_event( # type: ignore
                                "Received auth response",
                                {
                                    "response": responsecontent,
                                    "status": response.status,
                                },
                            )
                            if response.status == 200:
                                if responsecontent == '[[2,"",false]]':
                                    cookie = session.cookie_jar.filter_cookies(self._base_url).get("PHPSESSID")
                                    if cookie:
                                        self._phpsessid = cookie.value
                                        return True
                                    else:
                                        # Handle case where PHPSESSID might be missing after successful login
                                        self._logger.warning("PHPSESSID cookie not found after successful-looking authentication.")
                                        raise OigCloudAuthError("Authentication succeeded but PHPSESSID cookie was not found.")


                            raise OigCloudAuthError(f"Authentication failed, status: {response.status}, content: {responsecontent}")
            except OigCloudAuthError as e:
                self._logger.error(f"Authentication error: {e}", stack_info=True)
                raise
            except Exception as e:
                self._logger.error(f"Unexpected error during authentication: {e}", stack_info=True)
                raise OigCloudAuthError(f"Authentication failed due to unexpected error: {e}") from e

    def get_session(self) -> aiohttp.ClientSession:
        """Get a session with authentication cookies."""
        if not self._phpsessid:
            raise OigCloudAuthError("Not authenticated, call authenticate() first")

        # Ensure PHPSESSID is not None before using it. This should be guaranteed by the check above.
        phpsessid_value = cast(str, self._phpsessid)
        return aiohttp.ClientSession(headers={"Cookie": f"PHPSESSID={phpsessid_value}"})

    async def get_stats(self) -> Optional[Dict[str, Any]]:
        """Get stats from the OIG Cloud API with caching."""
        async with lock:
            current_time: datetime.datetime = datetime.datetime.now()
            if (current_time - self._last_update).total_seconds() < self._standard_scan_interval:
                self._logger.debug("Using cached stats")
                return self.last_state
            with tracer.start_as_current_span("get_stats") as span: # type: ignore
                try:
                    to_return: Optional[Dict[str, Any]] = await self._try_get_stats()
                    self._logger.debug("Retrieved stats")
                    if self.box_id is None and to_return:
                        # Ensure to_return is not None and is a dictionary before accessing its keys
                        if isinstance(to_return, dict) and to_return.keys():
                            self.box_id = list(to_return.keys())[0]
                    self._last_update = datetime.datetime.now()
                    self.last_state = to_return
                    return to_return
                except Exception as e:
                    self._logger.error(f"Unexpected error during get_stats: {e}", stack_info=True)
                    raise OigCloudApiError(f"Failed to get stats: {e}") from e

    async def _try_get_stats(self, dependent: bool = False) -> Optional[Dict[str, Any]]:
        with tracer.start_as_current_span("get_stats_internal"): # type: ignore
            async with self.get_session() as session:
                url: str = f"{self._base_url}{self._get_stats_url}"
                self._logger.debug(f"Getting stats from {url}")
                async with session.get(url) as response: # type: ignore
                    if response.status == 200:
                        # Assuming response.json() returns Dict[str, Any] or List[...]
                        # The API seems to return a dict for stats, but sometimes a list like `[[2,"",false]]`
                        result: Any = await response.json()
                        if not isinstance(result, dict) and not dependent:
                            self._logger.info("Retrying authentication as stats result was not a dict.")
                            if await self.authenticate():
                                return await self._try_get_stats(True) # Recursive call
                            return None # Auth failed
                        # Ensure that if result is not a dict, we return None or handle appropriately
                        return cast(Optional[Dict[str, Any]], result if isinstance(result, dict) else None)
                    else:
                        content = await response.text()
                        raise OigCloudApiError(f"Failed to fetch stats, status {response.status}, content: {content}")

    async def set_box_mode(self, mode: str) -> bool:
        """Set box mode (Home 1, Home 2, etc.)."""
        with tracer.start_as_current_span("set_mode") as span: # type: ignore
            try:
                self._logger.debug(f"Setting box mode to {mode}")
                return await self.set_box_params_internal("box_prms", "mode", mode)
            except Exception as e:
                self._logger.error(f"Error setting box mode: {e}", stack_info=True)
                raise

    async def set_grid_delivery_limit(self, limit: int) -> bool:
        with tracer.start_as_current_span("set_grid_delivery_limit") as span: # type: ignore
            try:
                self._logger.debug(f"Setting grid delivery limit to {limit}")
                # Assuming value for p_max_feed_grid should be string
                return await self.set_box_params_internal("invertor_prm1", "p_max_feed_grid", str(limit))
            except Exception as e:
                self._logger.error(f"Error setting grid delivery limit: {e}", stack_info=True)
                raise

    async def set_boiler_mode(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_boiler_mode") as span: # type: ignore
            try:
                self._logger.debug(f"Setting boiler mode to {mode}")
                return await self.set_box_params_internal("boiler_prms", "manual", mode)
            except Exception as e:
                self._logger.error(f"Error setting boiler mode: {e}", stack_info=True)
                raise

    async def set_ssr_rele_1(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_ssr_rele_1") as span: # type: ignore
            try:
                self._logger.debug(f"Setting SSR 1 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr0", mode)
            except Exception as e:
                self._logger.error(f"Error setting SSR 1: {e}", stack_info=True)
                raise

    async def set_ssr_rele_2(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_ssr_rele_2") as span: # type: ignore
            try:
                self._logger.debug(f"Setting SSR 2 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr1", mode)
            except Exception as e:
                self._logger.error(f"Error setting SSR 2: {e}", stack_info=True)
                raise

    async def set_ssr_rele_3(self, mode: str) -> bool:
        with tracer.start_as_current_span("set_ssr_rele_3") as span: # type: ignore
            try:
                self._logger.debug(f"Setting SSR 3 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr2", mode)
            except Exception as e:
                self._logger.error(f"Error setting SSR 3: {e}", stack_info=True)
                raise

    async def set_box_params_internal(
        self, table: str, column: str, value: Union[str, int] # Value can be int for some params
    ) -> bool:
        with tracer.start_as_current_span("set_box_params_internal") as span: # type: ignore
            if self.box_id is None:
                self._logger.error("box_id is not set, cannot call set_box_params_internal")
                return False
            async with self.get_session() as session:
                payload: Dict[str, Any] = {
                    "id_device": self.box_id,
                    "table": table,
                    "column": column,
                    "value": str(value), # API expects string value
                }
                data: str = json.dumps(payload)
                _nonce: int = int(time.time() * 1000)
                target_url: str = f"{self._base_url}{self._set_mode_url}?_nonce={_nonce}"
                
                # Redact box_id from log
                log_data = payload.copy()
                log_data["id_device"] = "xxxxxx"
                self._logger.debug(
                    f"Sending mode request to {target_url} with {json.dumps(log_data)}"
                )

                with tracer.start_as_current_span( # type: ignore
                    "set_box_params_internal.post",
                    kind=SpanKind.SERVER,
                    attributes={"http.url": target_url, "http.method": "POST"},
                ):
                    async with session.post(
                        target_url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                    ) as response: # type: ignore
                        response_content: str = await response.text()
                        if response.status == 200:
                            try:
                                response_json: Any = json.loads(response_content)
                                # Assuming the actual message is in response_json[0][2]
                                message: str = str(response_json[0][2]) if isinstance(response_json, list) and len(response_json) > 0 and isinstance(response_json[0], list) and len(response_json[0]) > 2 else response_content
                                self._logger.info(f"Response: {message}")
                                return True
                            except json.JSONDecodeError:
                                self._logger.error(f"Failed to decode JSON response: {response_content}")
                                raise OigCloudApiError(f"Failed to decode JSON response: {response_content}")
                        else:
                            raise OigCloudApiError(f"Error setting mode: status {response.status}, content: {response_content}")

    async def set_grid_delivery(self, mode: int) -> bool:
        """Set grid delivery mode."""
        with tracer.start_as_current_span("set_grid_delivery") as span: # type: ignore
            try:
                if self._no_telemetry:
                    raise OigCloudApiError("Tato funkce je ve vývoji a proto je momentálně dostupná pouze pro systémy s aktivní telemetrií.")

                self._logger.debug(f"Setting grid delivery to mode {mode}")

                if not self.box_id:
                    raise OigCloudApiError("Box ID not available, fetch stats first")

                async with self.get_session() as session:
                    # Corrected duplicate "value" key
                    payload: Dict[str, Any] = {"id_device": self.box_id, "value": mode}
                    data: str = json.dumps(payload)

                    _nonce: int = int(time.time() * 1000)
                    target_url: str = f"{self._base_url}{self._set_grid_delivery_url}?_nonce={_nonce}"
                    
                    # Log with redacted box_id for security
                    log_payload = payload.copy()
                    log_payload["id_device"] = "xxxxxx"
                    self._logger.info(f"Sending grid delivery request to {target_url} for {json.dumps(log_payload)}")

                    with tracer.start_as_current_span( # type: ignore
                        "set_grid_delivery.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": target_url, "http.method": "POST"},
                    ):
                        async with session.post(
                            target_url,
                            data=data,
                            headers={"Content-Type": "application/json"},
                        ) as response: # type: ignore
                            response_content: str = await response.text()

                            if response.status == 200:
                                try:
                                    response_json: Any = json.loads(response_content)
                                    self._logger.debug(f"API response: {response_json}")
                                    return True
                                except json.JSONDecodeError:
                                    self._logger.error(f"Failed to decode JSON response: {response_content}")
                                    # Assuming success if status is 200 but json is malformed, or specific error handling
                                    return True # Or raise error
                            else:
                                raise OigCloudApiError(f"Error setting grid delivery: status {response.status} - {response_content}")
            except OigCloudApiError:
                raise
            except Exception as e:
                self._logger.error(f"Error setting grid delivery: {e}", stack_info=True)
                raise # Re-raise as OigCloudApiError for consistency if desired

    # Funkce na nastavení nabíjení baterie z gridu
    async def set_battery_formating(self, mode: str, limit: int) -> bool: # mode parameter seems unused
        with tracer.start_as_current_span("set_batt_formating") as span: # type: ignore
            try:
                self._logger.debug(f"Setting formatting battery to {limit} percent (mode: {mode} - unused)")
                if self.box_id is None:
                    self._logger.error("box_id is not set, cannot call set_battery_formating")
                    return False
                async with self.get_session() as session:
                    payload: Dict[str, Any] = {
                        "id_device": self.box_id,
                        "column": "bat_ac", # This seems to be the parameter name for the limit
                        "value": limit, # The actual limit value
                    }
                    data: str = json.dumps(payload)

                    _nonce: int = int(time.time() * 1000)
                    target_url: str = f"{self._base_url}{self._set_batt_formating_url}?_nonce={_nonce}"
                    
                    log_payload = payload.copy()
                    log_payload["id_device"] = "xxxxxx"
                    self._logger.debug(
                        f"Sending formatting battery request to {target_url} with {json.dumps(log_payload)}"
                    )

                    with tracer.start_as_current_span( # type: ignore
                        "set_battery_formating.post", # Changed span name from "set_mode.post"
                        kind=SpanKind.SERVER,
                        attributes={"http.url": target_url, "http.method": "POST"},
                    ):
                        async with session.post(
                            target_url,
                            data=data,
                            headers={"Content-Type": "application/json"},
                        ) as response: # type: ignore
                            response_content: str = await response.text()
                            if response.status == 200:
                                try:
                                    response_json: Any = json.loads(response_content)
                                    message: str = str(response_json[0][2]) if isinstance(response_json, list) and len(response_json) > 0 and isinstance(response_json[0], list) and len(response_json[0]) > 2 else response_content
                                    self._logger.info(f"Response: {message}")
                                    return True
                                except json.JSONDecodeError:
                                    self._logger.error(f"Failed to decode JSON response: {response_content}")
                                    raise OigCloudApiError(f"Failed to decode JSON response: {response_content}")
                            else:
                                raise OigCloudApiError(f"Error setting battery formatting: status {response.status}, content: {response_content}")
            except Exception as e:
                self._logger.error(f"Error setting battery formatting: {e}", stack_info=True)
                raise # Re-raise as OigCloudApiError for consistency if desired

    async def get_extended_stats(
        self, name: str, from_date: str, to_date: str
    ) -> Optional[Union[Dict[str, Any], list]]: # Return type can be dict or list based on API
        with tracer.start_as_current_span("get_extended_stats") as span: # type: ignore
            try:
                async with self.get_session() as session:
                    url: str = f"{self._base_url}json2.php" # json2.php seems to be the correct endpoint
                    self._logger.debug(f"Requesting extended stats from {url} for '{name}' from {from_date} to {to_date}")

                    payload: Dict[str, str] = {"name": name, "range": f"{from_date},{to_date},0"}
                    headers: Dict[str, str] = {"Content-Type": "application/json"} # Usually POST with JSON uses this

                    with tracer.start_as_current_span( # type: ignore
                        "get_extended_stats.post",
                        kind=SpanKind.SERVER,
                        attributes={"http.url": url, "http.method": "POST"},
                    ):
                        async with session.post(url, json=payload, headers=headers) as response: # type: ignore
                            response_content = await response.text()
                            if response.status == 200:
                                try:
                                    result: Union[Dict[str, Any], list] = json.loads(response_content)
                                    self._logger.debug(f"Extended stats '{name}' retrieved successfully: {result}")
                                    return result
                                except json.JSONDecodeError:
                                    self._logger.error(f"Failed to decode JSON for extended stats '{name}': {response_content}")
                                    raise OigCloudApiError(f"Failed to decode JSON for extended stats '{name}': {response_content}")
                            else:
                                raise OigCloudApiError(f"Error fetching extended stats '{name}': status {response.status}, content: {response_content}")
            except Exception as e:
                self._logger.error(f"Error in get_extended_stats for '{name}': {e}", stack_info=True)
                raise OigCloudApiError(f"Error in get_extended_stats for '{name}': {e}") from e

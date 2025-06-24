import asyncio
import datetime
import json
import logging
import time
from typing import Any, Dict, Optional, Union, cast
import re

import aiohttp
from aiohttp import (
    ClientTimeout,
    ClientConnectorError,
    ClientResponseError,
    ServerTimeoutError,
)

# Conditional import of opentelemetry
_logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind

    tracer = trace.get_tracer(__name__)
    _has_opentelemetry = True
except ImportError:
    _logger.warning(
        "OpenTelemetry není nainstalován. Pro povolení telemetrie je nutné ručně nainstalovat balíček: pip install opentelemetry-exporter-otlp-proto-grpc==1.31.0"
    )
    tracer = None  # type: ignore
    SpanKind = None  # type: ignore
    _has_opentelemetry = False

from homeassistant import core

from ..models import OigCloudData, OigCloudDeviceData

# Using a lock to prevent multiple simultaneous API calls
lock: asyncio.Lock = asyncio.Lock()


class OigCloudApiError(Exception):
    """Exception for OIG Cloud API errors."""


class OigCloudAuthError(OigCloudApiError):
    """Exception for authentication errors."""


class OigCloudConnectionError(OigCloudApiError):
    """Exception for connection errors."""


class OigCloudTimeoutError(OigCloudApiError):
    """Exception for timeout errors."""


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
        hass: core.HomeAssistant,
        standard_scan_interval: int = 30,
        timeout: int = 30,
    ) -> None:
        """Initialize the API client."""
        self._no_telemetry: bool = no_telemetry
        self._logger: logging.Logger = logging.getLogger(__name__)
        self._username: str = username
        self._password: str = password
        self._phpsessid: Optional[str] = None
        self._timeout: ClientTimeout = ClientTimeout(total=timeout)

        self._last_update: datetime.datetime = datetime.datetime(1, 1, 1, 0, 0)
        self._standard_scan_interval: int = standard_scan_interval
        self.box_id: Optional[str] = None
        self.last_state: Optional[Dict[str, Any]] = None
        self.last_parsed_state: Optional[OigCloudData] = None
        self._logger.debug("OigCloud initialized")

    async def authenticate(self) -> bool:
        """Authenticate with the OIG Cloud API."""
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("authenticate") as span:
                return await self._authenticate_internal()
        else:
            return await self._authenticate_internal()

    async def _authenticate_internal(self) -> bool:
        """Internal authentication method with proper error handling."""
        try:
            login_command: Dict[str, str] = {
                "email": self._username,
                "password": self._password,
            }
            self._logger.debug("Authenticating with OIG Cloud")

            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                url: str = self._base_url + self._login_url
                data: str = json.dumps(login_command)
                headers: Dict[str, str] = {"Content-Type": "application/json"}

                async with session.post(url, data=data, headers=headers) as response:
                    responsecontent: str = await response.text()
                    if response.status == 200:
                        if responsecontent == '[[2,"",false]]':
                            self._phpsessid = (
                                session.cookie_jar.filter_cookies(self._base_url)
                                .get("PHPSESSID")
                                .value
                            )
                            return True
                    raise OigCloudAuthError("Authentication failed")

        except (asyncio.TimeoutError, ServerTimeoutError) as e:
            self._logger.error(f"Authentication timeout: {e}")
            raise OigCloudTimeoutError(f"Authentication timeout: {e}") from e
        except ClientConnectorError as e:
            self._logger.error(f"Connection error during authentication: {e}")
            raise OigCloudConnectionError(f"Connection error: {e}") from e
        except OigCloudAuthError:
            raise
        except Exception as e:
            self._logger.error(f"Unexpected error during authentication: {e}")
            raise OigCloudAuthError(f"Authentication failed: {e}") from e

    def get_session(self) -> aiohttp.ClientSession:
        """Get a session with authentication cookies."""
        if not self._phpsessid:
            raise OigCloudAuthError("Not authenticated, call authenticate() first")

        return aiohttp.ClientSession(
            headers={"Cookie": f"PHPSESSID={self._phpsessid}"}, timeout=self._timeout
        )

    async def get_stats(self) -> Optional[Dict[str, Any]]:
        """Get stats from the OIG Cloud API with caching."""
        async with lock:
            current_time = datetime.datetime.now()
            if (
                current_time - self._last_update
            ).total_seconds() < self._standard_scan_interval:
                self._logger.debug("Using cached stats")
                return self.last_state

            if _has_opentelemetry and tracer:
                with tracer.start_as_current_span("get_stats") as span:
                    return await self._get_stats_internal()
            else:
                return await self._get_stats_internal()

    async def _get_stats_internal(self) -> Optional[Dict[str, Any]]:
        """Internal get stats method with proper error handling."""
        try:
            to_return = await self._try_get_stats()
            self._logger.debug("Retrieved stats")
            if self.box_id is None and to_return:
                self.box_id = list(to_return.keys())[0]
            self._last_update = datetime.datetime.now()
            self.last_state = to_return
            return to_return
        except (asyncio.TimeoutError, ServerTimeoutError) as e:
            self._logger.warning(f"Timeout while getting stats: {e}")
            # Return cached data if available
            if self.last_state is not None:
                self._logger.info("Returning cached data due to timeout")
                return self.last_state
            raise OigCloudTimeoutError(f"API timeout: {e}") from e
        except ClientConnectorError as e:
            self._logger.warning(f"Connection error while getting stats: {e}")
            if self.last_state is not None:
                self._logger.info("Returning cached data due to connection error")
                return self.last_state
            raise OigCloudConnectionError(f"Connection error: {e}") from e
        except Exception as e:
            self._logger.error(f"Unexpected error: {e}")
            if self.last_state is not None:
                self._logger.info("Returning cached data due to unexpected error")
                return self.last_state
            raise OigCloudApiError(f"Failed to get stats: {e}") from e

    async def _try_get_stats(self, dependent: bool = False) -> Optional[Dict[str, Any]]:
        """Try to get stats with proper error handling."""
        try:
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
                        return result
                    else:
                        raise ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=f"Failed to fetch stats, status {response.status}",
                        )
        except (asyncio.TimeoutError, ServerTimeoutError) as e:
            self._logger.warning(f"Timeout getting stats from {url}: {e}")
            raise
        except ClientConnectorError as e:
            self._logger.warning(f"Connection error getting stats from {url}: {e}")
            raise

    async def set_box_mode(self, mode: str) -> bool:
        """Set box mode (Home 1, Home 2, etc.)."""
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("set_mode") as span:
                try:
                    self._logger.debug(f"Setting box mode to {mode}")
                    return await self.set_box_params_internal("box_prms", "mode", mode)
                except Exception as e:
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e
        else:
            try:
                self._logger.debug(f"Setting box mode to {mode}")
                return await self.set_box_params_internal("box_prms", "mode", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_grid_delivery_limit(self, limit: int) -> bool:
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("set_grid_delivery_limit") as span:
                try:
                    self._logger.debug(f"Setting grid delivery limit to {limit}")
                    return await self.set_box_params_internal(
                        "invertor_prm1", "p_max_feed_grid", str(limit)
                    )
                except Exception as e:
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e
        else:
            try:
                self._logger.debug(f"Setting grid delivery limit to {limit}")
                return await self.set_box_params_internal(
                    "invertor_prm1", "p_max_feed_grid", str(limit)
                )
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_boiler_mode(self, mode: str) -> bool:
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("set_boiler_mode") as span:
                try:
                    self._logger.debug(f"Setting boiler mode to {mode}")
                    return await self.set_box_params_internal(
                        "boiler_prms", "manual", mode
                    )
                except Exception as e:
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e
        else:
            try:
                self._logger.debug(f"Setting boiler mode to {mode}")
                return await self.set_box_params_internal("boiler_prms", "manual", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_ssr_rele_1(self, mode: str) -> bool:
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("set_ssr_rele_1") as span:
                try:
                    self._logger.debug(f"Setting SSR 1 to {mode}")
                    return await self.set_box_params_internal(
                        "boiler_prms", "ssr0", mode
                    )
                except Exception as e:
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e
        else:
            try:
                self._logger.debug(f"Setting SSR 1 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr0", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_ssr_rele_2(self, mode: str) -> bool:
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("set_ssr_rele_2") as span:
                try:
                    self._logger.debug(f"Setting SSR 2 to {mode}")
                    return await self.set_box_params_internal(
                        "boiler_prms", "ssr1", mode
                    )
                except Exception as e:
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e
        else:
            try:
                self._logger.debug(f"Setting SSR 2 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr1", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_ssr_rele_3(self, mode: str) -> bool:
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("set_ssr_rele_3") as span:
                try:
                    self._logger.debug(f"Setting SSR 3 to {mode}")
                    return await self.set_box_params_internal(
                        "boiler_prms", "ssr2", mode
                    )
                except Exception as e:
                    self._logger.error(f"Error: {e}", stack_info=True)
                    raise e
        else:
            try:
                self._logger.debug(f"Setting SSR 3 to {mode}")
                return await self.set_box_params_internal("boiler_prms", "ssr2", mode)
            except Exception as e:
                self._logger.error(f"Error: {e}", stack_info=True)
                raise e

    async def set_box_params_internal(
        self, table: str, column: str, value: str
    ) -> bool:
        if _has_opentelemetry and tracer:
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
                        f"Sending mode request to {target_url} with {data.replace(str(self.box_id), 'xxxxxx')}"
                    )

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
        else:
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
                    f"Sending mode request to {target_url} with {data.replace(str(self.box_id), 'xxxxxx')}"
                )

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
        if _has_opentelemetry and tracer:
            with tracer.start_as_current_span("set_grid_delivery") as span:
                try:
                    if self._no_telemetry:
                        raise OigCloudApiError(
                            "Tato funkce je ve vývoji a proto je momentálně dostupná pouze pro systémy s aktivní telemetrií."
                        )

                    self._logger.debug(f"Setting grid delivery to mode {mode}")

                    if not self.box_id:
                        raise OigCloudApiError(
                            "Box ID not available, fetch stats first"
                        )

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

                        self._logger.info(
                            f"Sending grid delivery request to {target_url} for {data.replace(str(self.box_id), 'xxxxxx')}"
                        )

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
        else:
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

                    self._logger.info(
                        f"Sending grid delivery request to {target_url} for {data.replace(str(self.box_id), 'xxxxxx')}"
                    )

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

    async def set_battery_formating(self, mode: str, limit: int) -> bool:
        if _has_opentelemetry and tracer:
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
                            f"Sending formatting battery request to {target_url} with {data.replace(str(self.box_id), 'xxxxxx')}"
                        )

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
        else:
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
                        f"Sending formatting battery request to {target_url} with {data.replace(str(self.box_id), 'xxxxxx')}"
                    )

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

    async def get_extended_stats(self, name: str, from_date: str, to_date: str) -> Any:
        """Get extended statistics from OIG Cloud API with detailed debugging."""
        try:
            self._logger.info(f"=== EXTENDED STATS DEBUG START ===")
            self._logger.info(
                f"Requesting extended stats: name='{name}', from_date='{from_date}', to_date='{to_date}'"
            )
            self._logger.info(f"Box ID: {self.box_id}")
            self._logger.info(f"PHP Session ID present: {bool(self._phpsessid)}")

            async with self.get_session() as session:
                url = self._base_url + "json2.php"
                self._logger.info(f"Request URL: {url}")

                # Zkusíme různé formáty payload
                payloads_to_try = [
                    # Původní formát
                    {"name": name, "range": f"{from_date},{to_date},0"},
                    # Alternativní formáty
                    {"type": name, "date_from": from_date, "date_to": to_date},
                    {"stat_type": name, "from": from_date, "to": to_date},
                    {"name": name, "from_date": from_date, "to_date": to_date},
                ]

                for i, payload in enumerate(payloads_to_try):
                    self._logger.info(f"Trying payload format {i+1}: {payload}")

                    headers = {"Content-Type": "application/json"}

                    async with session.post(
                        url, json=payload, headers=headers
                    ) as response:
                        self._logger.info(f"Response status: {response.status}")
                        self._logger.info(f"Response headers: {dict(response.headers)}")

                        # Přečteme response text pro debugging
                        response_text = await response.text()
                        self._logger.info(
                            f"Response text (first 500 chars): {response_text[:500]}"
                        )

                        if response.status == 200:
                            try:
                                # Pokusíme se parsovat jako JSON
                                result = (
                                    json.loads(response_text) if response_text else {}
                                )
                                self._logger.info(
                                    f"Successfully parsed JSON with payload format {i+1}"
                                )
                                self._logger.info(
                                    f"Result type: {type(result)}, length: {len(str(result))}"
                                )
                                return result
                            except json.JSONDecodeError as e:
                                self._logger.warning(
                                    f"Failed to parse JSON with payload {i+1}: {e}"
                                )
                                continue

                        elif response.status == 500:
                            self._logger.error(f"HTTP 500 with payload {i+1}")
                            self._logger.error(
                                f"Server error response: {response_text}"
                            )

                            # Pokračujeme s dalším formátem
                            continue

                        elif response.status == 401:
                            self._logger.warning(
                                f"Authentication failed, attempting re-auth"
                            )
                            if await self.authenticate():
                                self._logger.info("Re-authentication successful")
                                # Rekurzivní volání po re-auth
                                return await self.get_extended_stats(
                                    name, from_date, to_date
                                )
                            else:
                                self._logger.error("Re-authentication failed")
                                return {}

                        else:
                            self._logger.error(
                                f"Unexpected status {response.status} with payload {i+1}"
                            )

                # Pokud žádný formát nefungoval
                self._logger.error(
                    f"All payload formats failed for extended stats '{name}'"
                )
                return {}

        except Exception as e:
            self._logger.error(
                f"Exception in get_extended_stats for '{name}': {e}", exc_info=True
            )
            return {}
        finally:
            self._logger.info(f"=== EXTENDED STATS DEBUG END ===")

    async def debug_extended_stats_api(self) -> Dict[str, Any]:
        """Debug method to test extended stats API endpoints."""
        try:
            self._logger.info("=== DEBUGGING EXTENDED STATS API ===")

            async with self.get_session() as session:
                base_url = self._base_url + "json2.php"

                # Test 1: Prázdný POST request
                self._logger.info("Test 1: Empty POST request")
                async with session.post(base_url) as response:
                    text = await response.text()
                    self._logger.info(
                        f"Empty POST: Status {response.status}, Response: {text[:200]}"
                    )

                # Test 2: GET request
                self._logger.info("Test 2: GET request")
                async with session.get(base_url) as response:
                    text = await response.text()
                    self._logger.info(
                        f"GET: Status {response.status}, Response: {text[:200]}"
                    )

                # Test 3: Minimální payload
                self._logger.info("Test 3: Minimal payload")
                minimal_payload = {"test": "true"}
                async with session.post(base_url, json=minimal_payload) as response:
                    text = await response.text()
                    self._logger.info(
                        f"Minimal: Status {response.status}, Response: {text[:200]}"
                    )

                # Test 4: Zkusit hlavní JSON endpoint
                main_url = self._base_url + "json.php"
                self._logger.info("Test 4: Main JSON endpoint")
                async with session.get(main_url) as response:
                    text = await response.text()
                    self._logger.info(
                        f"Main JSON: Status {response.status}, Response: {text[:200]}"
                    )

                return {"debug": "completed"}

        except Exception as e:
            self._logger.error(f"Debug extended stats failed: {e}", exc_info=True)
            return {}

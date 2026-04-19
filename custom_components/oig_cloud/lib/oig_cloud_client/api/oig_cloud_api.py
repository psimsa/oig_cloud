import asyncio
import datetime
import json
import logging
import ssl
import time
from typing import Any, Dict, Optional

import aiohttp
import certifi
from aiohttp import (
    ClientConnectorError,
    ClientResponseError,
    ClientTimeout,
    ServerTimeoutError,
    TCPConnector,
)
from yarl import URL

from ..models import OigCloudData

# Conditional import of opentelemetry
_logger = logging.getLogger(__name__)


def _extract_response_message(response_json: Any) -> str:
    if (
        isinstance(response_json, list)
        and response_json
        and isinstance(response_json[0], list)
        and len(response_json[0]) > 2
        and isinstance(response_json[0][2], str)
    ):
        return response_json[0][2]
    if isinstance(response_json, dict):
        message = response_json.get("message")
        if isinstance(message, str):
            return message
    return str(response_json)


try:
    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)
    _has_opentelemetry = True
except ImportError:
    _logger.debug("OpenTelemetry not available - using ServiceShield telemetry instead")
    tracer = None  # type: ignore
    _has_opentelemetry = False

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
    _base_url: str = "https://portal.oigpower.cz/"
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
        timeout: int = 30,
    ) -> None:
        """Initialize the API client.

        Args:
            username: OIG Cloud username
            password: OIG Cloud password
            no_telemetry: Disable telemetry
            timeout: Request timeout in seconds
        """
        self._no_telemetry: bool = no_telemetry
        self._logger: logging.Logger = logging.getLogger(__name__)
        self._username: str = username
        self._password: str = password
        self._phpsessid: Optional[str] = None
        self._timeout: ClientTimeout = ClientTimeout(total=timeout)

        self._last_update: datetime.datetime = datetime.datetime(1, 1, 1, 0, 0)
        self.box_id: Optional[str] = None
        self.last_state: Optional[Dict[str, Any]] = None
        self.last_parsed_state: Optional[OigCloudData] = None

        # ETag cache: per-endpoint storage
        # Structure: {endpoint: {"etag": str|None, "data": Any|None, "ts": float}}
        self._cache: Dict[str, Dict[str, Any]] = {}

        # SSL handling modes:
        # 0 = normal SSL
        # 1 = SSL with cached intermediate cert (for broken chain)
        # 2 = SSL disabled (last resort)
        # Prefer intermediate cert by default to avoid broken-chain warnings.
        self._ssl_mode: int = 1
        self._ssl_context_with_intermediate: Optional[ssl.SSLContext] = None

        self._logger.debug(
            "OigCloudApi initialized (ETag support enabled, timing controlled by coordinator)"
        )

    # Certum DV TLS G2 R39 CA - intermediate certificate for oigpower.cz
    # Downloaded from: http://certumdvtlsg2r39ca.repository.certum.pl/certumdvtlsg2r39ca.cer
    # This is needed because OIG server doesn't send the intermediate cert in TLS handshake
    _CERTUM_INTERMEDIATE_CERT: str = """-----BEGIN CERTIFICATE-----
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
8FpPkganuCwy++7umTkM7+Q=
-----END CERTIFICATE-----"""

    def _create_ssl_context_with_intermediate(self) -> ssl.SSLContext:
        """Create SSL context with cached intermediate certificate."""
        ctx = ssl.create_default_context(cafile=certifi.where())
        # Add the intermediate certificate
        ctx.load_verify_locations(cadata=self._CERTUM_INTERMEDIATE_CERT)
        return ctx

    async def _ensure_ssl_context_with_intermediate(self) -> None:
        """Prepare SSL context without blocking the event loop."""
        if self._ssl_context_with_intermediate is not None:
            return
        self._logger.info(
            "🔐 Creating SSL context with Certum intermediate certificate"
        )
        self._ssl_context_with_intermediate = await asyncio.to_thread(
            self._create_ssl_context_with_intermediate
        )

    def _get_ssl_context_with_intermediate(self) -> ssl.SSLContext:
        if self._ssl_context_with_intermediate is None:
            raise RuntimeError("SSL context not initialized for intermediate cert")
        return self._ssl_context_with_intermediate

    def _get_connector(self) -> TCPConnector:
        """Get TCP connector based on current SSL mode.

        SSL modes:
        0 = normal SSL (default)
        1 = SSL with cached intermediate cert (for broken chain)
        2 = SSL disabled (last resort)
        """
        if self._ssl_mode == 0:
            # Normal SSL verification
            return TCPConnector()
        elif self._ssl_mode == 1:
            # SSL with intermediate cert
            return TCPConnector(ssl=self._get_ssl_context_with_intermediate())
        else:
            # SSL disabled
            return TCPConnector(ssl=False)

    async def authenticate(self) -> bool:
        """Authenticate with the OIG Cloud API."""
        return await self._authenticate_internal()

    async def _authenticate_internal(self) -> bool:
        """Internal authentication method with SSL fallback.

        Tries 3 SSL modes in order:
        1. Normal SSL verification
        2. SSL with cached intermediate certificate (fixes broken chain)
        3. SSL disabled (last resort)
        """
        login_command: Dict[str, str] = {
            "email": self._username,
            "password": self._password,
        }
        self._logger.debug("Authenticating with OIG Cloud")

        # Try up to 3 SSL modes
        max_ssl_mode = 2
        start_mode = self._ssl_mode

        for mode in range(start_mode, max_ssl_mode + 1):
            self._ssl_mode = mode
            try:
                if mode == 1:
                    await self._ensure_ssl_context_with_intermediate()
                connector = self._get_connector()
                async with aiohttp.ClientSession(
                    timeout=self._timeout, connector=connector
                ) as session:
                    data: str = json.dumps(login_command)
                    headers: Dict[str, str] = {"Content-Type": "application/json"}

                    url: str = self._base_url + self._login_url
                    async with session.post(url, data=data, headers=headers) as response:
                        responsecontent: str = await response.text()
                        if response.status == 200 and responsecontent == '[[2,"",false]]':
                            cookie_base = URL(self._base_url)
                            cookie = session.cookie_jar.filter_cookies(cookie_base).get(
                                "PHPSESSID"
                            )
                            if cookie is not None:
                                self._phpsessid = cookie.value
                            if mode > 0:
                                mode_names = ["normal", "intermediate cert", "disabled"]
                                self._logger.info(
                                    f"✅ Authentication successful with SSL mode: {mode_names[mode]}"
                                )
                            return True
                        self._logger.debug(
                            "Authentication attempt failed for %s status=%s body=%s",
                            url,
                            response.status,
                            responsecontent,
                        )
                    raise OigCloudAuthError("Authentication failed")

            except (asyncio.TimeoutError, ServerTimeoutError) as e:
                self._logger.error(f"Authentication timeout: {e}")
                raise OigCloudTimeoutError(f"Authentication timeout: {e}") from e
            except ClientConnectorError as e:
                # Check if this is an SSL certificate error
                error_str = str(e)
                if "SSL" in error_str or "certificate" in error_str.lower():
                    if mode < max_ssl_mode:
                        mode_names = ["normal", "intermediate cert", "disabled"]
                        self._logger.warning(
                            f"🔓 SSL error with mode '{mode_names[mode]}', "
                            f"trying '{mode_names[mode + 1]}'"
                        )
                        continue  # Try next SSL mode
                self._logger.error(f"Connection error during authentication: {e}")
                raise OigCloudConnectionError(f"Connection error: {e}") from e
            except OigCloudAuthError:
                raise
            except Exception as e:
                self._logger.error(f"Unexpected error during authentication: {e}")
                raise OigCloudAuthError(f"Authentication failed: {e}") from e

        # Should not reach here, but just in case
        raise OigCloudAuthError("Authentication failed after all SSL fallbacks")

    def get_session(self) -> aiohttp.ClientSession:
        """Get a session with authentication cookies and browser-like headers."""
        if not self._phpsessid:
            raise OigCloudAuthError("Not authenticated, call authenticate() first")

        # Browser-like headers to simulate real Chrome browser on Android
        headers = {
            "Cookie": f"PHPSESSID={self._phpsessid}",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/141.0.0.0 Mobile Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Referer": "https://portal.oigpower.cz/",
            "Origin": "https://portal.oigpower.cz",
            "Sec-Ch-Ua": '"Not)A;Brand";v="99", "Google Chrome";v="141", "Chromium";v="141"',
            "Sec-Ch-Ua-Mobile": "?1",
            "Sec-Ch-Ua-Platform": '"Android"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        # Use SSL mode determined during authentication
        connector = self._get_connector()
        return aiohttp.ClientSession(
            headers=headers, timeout=self._timeout, connector=connector
        )

    def _update_cache(
        self, endpoint: str, response: aiohttp.ClientResponse, data: Any
    ) -> None:
        """Update ETag cache for endpoint.

        Args:
            endpoint: API endpoint path (e.g., 'json.php')
            response: aiohttp response object
            data: Parsed response data
        """
        etag = response.headers.get("ETag")
        if etag:
            self._logger.debug(f"💾 Caching ETag for {endpoint}: {etag[:20]}...")

        self._cache[endpoint] = {
            "etag": etag,
            "data": data,
            "ts": time.time(),
        }

    async def get_stats(self) -> Optional[Dict[str, Any]]:
        """Get stats from the OIG Cloud API.

        Note: No internal caching - coordinator controls timing.
        last_state is only used for timeout fallback.
        """
        async with lock:
            return await self._get_stats_internal()

    async def _get_stats_internal(self) -> Optional[Dict[str, Any]]:
        """Internal get stats method with proper error handling."""
        try:
            to_return = await self._try_get_stats()
            self._logger.debug("Stats retrieved successfully")
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
        """Try to get stats with proper error handling and ETag support."""
        endpoint = "json.php"

        try:
            async with self.get_session() as session:
                url: str = self._base_url + self._get_stats_url

                # Prepare headers with If-None-Match if we have cached ETag
                extra_headers: Dict[str, str] = {}
                cached = self._cache.get(endpoint)
                if cached and cached.get("etag"):
                    extra_headers["If-None-Match"] = cached["etag"]
                    self._logger.debug(
                        f"📋 ETag hit → If-None-Match={cached['etag'][:20]}..."
                    )

                self._logger.debug(f"Getting stats from {url}")
                async with session.get(url, headers=extra_headers) as response:
                    # Debug: log response headers
                    etag_header = response.headers.get("ETag")
                    self._logger.debug(
                        f"Response status: {response.status}, ETag header: {etag_header}"
                    )

                    # Handle 304 Not Modified - return cached data
                    if response.status == 304:
                        if cached and cached.get("data") is not None:
                            self._logger.debug(
                                "✅ 304 Not Modified → using cached data"
                            )
                            return cached["data"]
                        else:
                            self._logger.warning(
                                "⚠️  304 received but no cached data available"
                            )
                            # Fallback: retry without If-None-Match
                            async with session.get(url) as retry_response:
                                if retry_response.status == 200:
                                    retry_data = await retry_response.json()
                                    if isinstance(retry_data, dict):
                                        self._update_cache(endpoint, retry_response, retry_data)
                                        return retry_data
                                    if not dependent:
                                        self._logger.info("Retrying authentication")
                                        if await self.authenticate():
                                            return await self._try_get_stats(True)
                                    return None
                                else:
                                    raise ClientResponseError(
                                        request_info=retry_response.request_info,
                                        history=retry_response.history,
                                        status=retry_response.status,
                                        message=f"Failed to fetch stats, status {retry_response.status}",
                                    )

                    if response.status == 200:
                        response_data = await response.json()

                        if not isinstance(response_data, dict) and not dependent:
                            self._logger.info("Retrying authentication")
                            if await self.authenticate():
                                return await self._try_get_stats(True)
                            return None

                        if isinstance(response_data, dict):
                            # Update cache with new data and ETag
                            self._update_cache(endpoint, response, response_data)
                            return response_data
                        return None
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
        try:
            self._logger.debug(f"Setting box mode to {mode}")
            return await self.set_box_params_internal("box_prms", "mode", mode)
        except Exception as e:
            self._logger.error(f"Error: {e}", stack_info=True)
            raise e

    async def set_box_prm2_app(self, value: int) -> bool:
        """Set box_prm2.app value (supplementary mode bitmask: 0-3)."""
        try:
            self._logger.debug(f"Setting box_prm2.app to {value}")
            return await self.set_box_params_internal("box_prm2", "app", str(value))
        except Exception as e:
            self._logger.error(f"Error setting box_prm2.app: {e}", stack_info=True)
            raise e

    async def set_grid_delivery_limit(self, limit: int) -> bool:
        """Set grid delivery limit."""
        try:
            self._logger.debug(f"Setting grid delivery limit to {limit}")
            return await self.set_box_params_internal(
                "invertor_prm1", "p_max_feed_grid", str(limit)
            )
        except Exception as e:
            self._logger.error(f"Error: {e}", stack_info=True)
            raise e

    async def set_boiler_mode(self, mode: str) -> bool:
        """Set boiler mode."""
        try:
            self._logger.debug(f"Setting boiler mode to {mode}")
            return await self.set_box_params_internal("boiler_prms", "manual", mode)
        except Exception as e:
            self._logger.error(f"Error: {e}", stack_info=True)
            raise e

    async def set_ssr_rele_1(self, mode: str) -> bool:
        """Set SSR relay 1 mode."""
        try:
            self._logger.debug(f"Setting SSR 1 to {mode}")
            return await self.set_box_params_internal("boiler_prms", "ssr0", mode)
        except Exception as e:
            self._logger.error(f"Error: {e}", stack_info=True)
            raise e

    async def set_ssr_rele_2(self, mode: str) -> bool:
        """Set SSR relay 2 mode."""
        try:
            self._logger.debug(f"Setting SSR 2 to {mode}")
            return await self.set_box_params_internal("boiler_prms", "ssr1", mode)
        except Exception as e:
            self._logger.error(f"Error: {e}", stack_info=True)
            raise e

    async def set_ssr_rele_3(self, mode: str) -> bool:
        """Set SSR relay 3 mode."""
        try:
            self._logger.debug(f"Setting SSR 3 to {mode}")
            return await self.set_box_params_internal("boiler_prms", "ssr2", mode)
        except Exception as e:
            self._logger.error(f"Error: {e}", stack_info=True)
            raise e

    async def set_box_params_internal(
        self, table: str, column: str, value: str
    ) -> bool:
        """Internal method to set box parameters."""
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

            self._logger.debug(
                f"Sending mode request to {target_url} with {data.replace(str(self.box_id), 'xxxxxx')}"
            )

            async with session.post(
                target_url,
                data=data,
                headers={"Content-Type": "application/json"},
            ) as response:
                response_content: str = await response.text()
                if response.status == 200:
                    response_json = json.loads(response_content)
                    message = _extract_response_message(response_json)
                    self._logger.info(f"Response: {message}")
                    return True
                else:
                    raise Exception(
                        f"Error setting mode: {response.status}",
                        response_content,
                    )

    async def set_grid_delivery(self, mode: int) -> bool:
        """Set grid delivery mode."""
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
        """Set battery formatting parameters."""
        try:
            self._logger.debug(f"Setting formatting battery to {limit} percent")
            async with self.get_session() as session:
                data: str = json.dumps(
                    {
                        "id_device": self.box_id,
                        "column": "bat_ac",
                        "value": limit,
                    }
                )

                _nonce: int = int(time.time() * 1000)
                target_url: str = (
                    f"{self._base_url}{self._set_batt_formating_url}?_nonce={_nonce}"
                )

                self._logger.debug(
                    f"Sending formatting battery request to {target_url} with {data.replace(str(self.box_id), 'xxxxxx')}"
                )

                async with session.post(
                    target_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response_content: str = await response.text()
                    if response.status == 200:
                        response_json = json.loads(response_content)
                        message = _extract_response_message(response_json)
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

    async def set_formating_mode(self, mode: str) -> bool:
        """Set battery formatting mode."""
        try:
            self._logger.debug(f"Setting battery formatting mode to {mode}")

            async with self.get_session() as session:
                data: str = json.dumps(
                    {
                        "bat_ac": mode,
                    }
                )

                _nonce: int = int(time.time() * 1000)
                target_url: str = (
                    f"{self._base_url}{self._set_batt_formating_url}?_nonce={_nonce}"
                )

                self._logger.info(f"Sending battery formatting request to {target_url}")

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
            self._logger.error(
                f"Error setting battery formatting mode: {e}", stack_info=True
            )
            raise OigCloudApiError(f"Failed to set battery formatting mode: {e}") from e

    async def get_extended_stats(
        self, name: str, from_date: str, to_date: str
    ) -> Dict[str, Any]:
        """Get extended statistics with ETag support."""
        endpoint = f"json2.php:{name}"  # Per-name caching

        try:
            self._logger.debug(
                f"Getting extended stats '{name}' from {from_date} to {to_date}"
            )

            async with self.get_session() as session:
                url: str = self._base_url + "json2.php"

                # Prepare headers with If-None-Match if we have cached ETag
                extra_headers: Dict[str, str] = {"Content-Type": "application/json"}
                cached = self._cache.get(endpoint)
                if cached and cached.get("etag"):
                    extra_headers["If-None-Match"] = cached["etag"]
                    self._logger.debug(
                        f"📋 ETag hit for '{name}' → If-None-Match={cached['etag'][:20]}..."
                    )

                # Původní payload formát
                payload: Dict[str, str] = {
                    "name": name,
                    "range": f"{from_date},{to_date},0",
                }

                async with session.post(
                    url, json=payload, headers=extra_headers
                ) as response:
                    # Handle 304 Not Modified
                    if response.status == 304:
                        if cached and cached.get("data") is not None:
                            self._logger.debug(
                                f"✅ 304 Not Modified for '{name}' → using cached data"
                            )
                            return cached["data"]
                        else:
                            self._logger.warning(
                                f"⚠️  304 received for '{name}' but no cached data available"
                            )
                            # Fallback without If-None-Match
                            async with session.post(
                                url,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                            ) as retry_response:
                                if retry_response.status == 200:
                                    retry_data = await retry_response.json()
                                    if isinstance(retry_data, dict):
                                        self._update_cache(endpoint, retry_response, retry_data)
                                        return retry_data
                                return {}

                    if response.status == 200:
                        try:
                            response_data = await response.json()
                            if not isinstance(response_data, dict):
                                return {}

                            # Update cache with new data and ETag
                            self._update_cache(endpoint, response, response_data)

                            self._logger.debug(
                                f"Extended stats '{name}' retrieved successfully, data size: {len(str(response_data))}"
                            )
                            return response_data
                        except Exception as e:
                            self._logger.error(
                                f"Failed to parse JSON response for {name}: {e}"
                            )
                            return {}
                    elif response.status == 401:
                        self._logger.warning(
                            f"Authentication failed for extended stats '{name}', retrying authentication"
                        )
                        if await self.authenticate():
                            return await self.get_extended_stats(
                                name, from_date, to_date
                            )
                        return {}
                    else:
                        self._logger.warning(
                            f"HTTP {response.status} error fetching extended stats for {name}"
                        )
                        return {}

        except Exception as e:
            self._logger.error(f"Error in get_extended_stats for '{name}': {e}")
            return {}

    async def get_notifications(
        self, device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get notifications from OIG Cloud - similar to get_extended_stats."""
        try:
            if device_id is None:
                device_id = self.box_id

            if not device_id:
                self._logger.warning("No device ID available for notifications")
                return {"notifications": [], "bypass_status": False}

            self._logger.debug(f"Getting notifications for device {device_id}")

            async with self.get_session() as session:
                nonce = int(time.time() * 1000)
                url = f"{self._base_url}inc/php/scripts/Controller.Call.php?id=2&selector_id=ctrl-notifs&_nonce={nonce}"

                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; OIG-HA-Integration)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "cs,en;q=0.5",
                    "Referer": f"{self._base_url}",
                    "X-Requested-With": "XMLHttpRequest",
                }

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        content = await response.text()
                        self._logger.debug(
                            f"Notifications content length: {len(content)}"
                        )

                        # Check for empty response (authentication failed)
                        if (
                            '"folder-list">  </div>' in content
                            or '<div class="folder-list">  </div>' in content
                        ):
                            self._logger.warning(
                                "Empty notification list - authentication may have failed"
                            )
                            return {"notifications": [], "bypass_status": False}

                        # Return raw content for parsing by notification manager
                        return {
                            "content": content,
                            "status": "success",
                            "device_id": device_id,
                        }

                    elif response.status == 401:
                        self._logger.warning(
                            "Authentication failed for notifications, retrying authentication"
                        )
                        if await self.authenticate():
                            return await self.get_notifications(device_id)
                        return {
                            "notifications": [],
                            "bypass_status": False,
                            "error": "auth_failed",
                        }
                    else:
                        self._logger.warning(
                            f"HTTP {response.status} error fetching notifications"
                        )
                        return {
                            "notifications": [],
                            "bypass_status": False,
                            "error": f"http_{response.status}",
                        }

        except (asyncio.TimeoutError, ServerTimeoutError) as e:
            self._logger.warning(f"Timeout while getting notifications: {e}")
            return {"notifications": [], "bypass_status": False, "error": "timeout"}
        except ClientConnectorError as e:
            self._logger.warning(f"Connection error while getting notifications: {e}")
            return {"notifications": [], "bypass_status": False, "error": "connection"}
        except Exception as e:
            self._logger.error(f"Error in get_notifications: {e}")
            return {"notifications": [], "bypass_status": False, "error": str(e)}

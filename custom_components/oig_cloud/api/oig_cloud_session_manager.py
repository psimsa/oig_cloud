"""Session manager wrapper for OigCloudApi with TTL tracking and retry logic.

This wrapper does NOT inject sessions into OigCloudApi (which manages its own sessions).
Instead, it wraps API calls to provide:
- Session TTL tracking and automatic re-authentication
- 401 retry logic with exponential backoff
- Rate limiting protection
- Detailed logging for debugging
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from .oig_cloud_api import OigCloudApi, OigCloudApiError, OigCloudAuthError

from ..shared.logging import _redact_sensitive
_LOGGER = logging.getLogger(__name__)

# Session TTL: 30 minut (bezpečná rezerva)
SESSION_TTL = timedelta(minutes=30)

# Rate limiting: max 1 request per second
MIN_REQUEST_INTERVAL = timedelta(seconds=1)


class OigCloudSessionManager:
    """Wrapper around OigCloudApi for session management without session injection."""

    def __init__(self, api: OigCloudApi) -> None:
        """Initialize session manager.

        Args:
            api: OigCloudApi instance (already configured with credentials)
        """
        self._api = api
        self._last_auth_time: Optional[datetime] = None
        self._last_request_time: Optional[datetime] = None
        self._auth_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()

        # Statistics tracking
        self._stats: Dict[str, Any] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "auth_count": 0,
            "retry_count": 0,
            "rate_limited_count": 0,
            "session_created": datetime.now(),
        }

        _LOGGER.info(
            "🔧 SessionManager initialized (wrapper mode, no session injection)"
        )
        _LOGGER.info(f"📊 Session TTL: {SESSION_TTL.total_seconds() / 60:.0f} minutes")
        _LOGGER.info(
            f"⏱️  Rate limit: {MIN_REQUEST_INTERVAL.total_seconds():.1f}s between requests"
        )

    @property
    def api(self) -> OigCloudApi:
        """Get underlying API instance."""
        return self._api

    async def _log_api_session_info(self) -> None:
        """Log information about API session configuration and headers."""
        try:
            base_url = getattr(self._api, "_base_url", "https://portal.oigpower.cz/")
            _LOGGER.info(f"🌐 Base URL: {base_url}")

            session = self._open_debug_session()
            if session:
                try:
                    self._log_session_headers(session)
                finally:
                    await session.close()
            else:
                _LOGGER.debug("No session object available from get_session()")

            # Log known API endpoints
            _LOGGER.info("Known API endpoints:")
            _LOGGER.info(f"   Login: {base_url}/login")
            _LOGGER.info(f"   Stats: {base_url}/api/get_stats")
            _LOGGER.info(f"   Extended: {base_url}/api/get_extended_stats")

        except Exception as e:
            _LOGGER.debug(f"Error logging API session info: {e}")

    def _open_debug_session(self) -> Optional[Any]:
        try:
            return self._api.get_session()
        except Exception as e:
            _LOGGER.warning(f"Could not inspect session headers: {e}", exc_info=True)
            return None

    def _log_session_headers(self, session: Any) -> None:
        """Session headers nejsou logovány (citlivé údaje)."""
        headers = self._extract_session_headers(session)
        if headers:
            for key, value in headers.items():
                _LOGGER.debug("Session header: %s = %s", key, _redact_sensitive(value))

        _LOGGER.debug(
            "Could not find headers in session object, checking attributes..."
        )
        _LOGGER.debug(
            "Session attributes: %s",
            [attr for attr in dir(session) if "header" in attr.lower()],
        )

    @staticmethod
    def _extract_session_headers(session: Any) -> Optional[Dict[str, str]]:
        if hasattr(session, "_default_headers") and session._default_headers:
            return dict(session._default_headers)
        if hasattr(session, "_connector") and hasattr(session._connector, "_default_headers"):
            return dict(session._connector._default_headers)
        return None

    def _is_session_expired(self) -> bool:
        """Check if session TTL has expired."""
        if self._last_auth_time is None:
            return True

        elapsed = datetime.now() - self._last_auth_time
        is_expired = elapsed > SESSION_TTL

        if is_expired:
            _LOGGER.debug(
                f"⏰ Session expired (age: {elapsed.total_seconds() / 60:.1f}min)"
            )

        return is_expired

    async def _ensure_auth(self) -> None:
        """Ensure API is authenticated, re-authenticate if session expired."""
        async with self._auth_lock:
            if self._is_session_expired():
                self._stats["auth_count"] += 1
                auth_num = self._stats["auth_count"]

                _LOGGER.info(
                    f"🔐 Authentication #{auth_num} starting (session expired or first auth)"
                )

                try:
                    # Log PHPSESSID before auth
                    old_session = getattr(self._api, "_phpsessid", None)
                    if old_session:
                        _LOGGER.debug("📝 Old PHPSESSID detected (not logged for security)")

                    # Log authentication URL
                    base_url = getattr(self._api, "_base_url", None)
                    if base_url:
                        _LOGGER.info(f"🌐 Auth URL: {base_url}/login")

                    await self._api.authenticate()
                    self._last_auth_time = datetime.now()

                    # Log PHPSESSID after auth (NOT logged for security)
                    new_session = getattr(self._api, "_phpsessid", None)
                    if new_session:
                        _LOGGER.debug("🍪 New PHPSESSID created (not logged for security)")

                    # Try to inspect session headers (if API creates session)
                    await self._log_api_session_info()

                    _LOGGER.info(
                        f"✅ Authentication #{auth_num} successful, session valid until {(datetime.now() + SESSION_TTL).strftime('%H:%M:%S')}"
                    )
                except Exception as e:
                    _LOGGER.error(f"❌ Authentication #{auth_num} failed: {e}")
                    raise
            else:
                # At this point _last_auth_time is not None because _is_session_expired() returned False
                last_auth = self._last_auth_time
                assert last_auth is not None
                elapsed = datetime.now() - last_auth
                remaining = SESSION_TTL - elapsed
                _LOGGER.debug(
                    f"✓ Session still valid (age: {elapsed.total_seconds() / 60:.1f}min, "
                    f"remaining: {remaining.total_seconds() / 60:.1f}min)"
                )

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        async with self._request_lock:
            if self._last_request_time is not None:
                elapsed = datetime.now() - self._last_request_time
                if elapsed < MIN_REQUEST_INTERVAL:
                    self._stats["rate_limited_count"] += 1
                    sleep_time = (MIN_REQUEST_INTERVAL - elapsed).total_seconds()
                    _LOGGER.debug(
                        f"⏸️  Rate limiting: sleeping {sleep_time:.2f}s (total rate-limited: {self._stats['rate_limited_count']})"
                    )
                    await asyncio.sleep(sleep_time)

            self._last_request_time = datetime.now()

    async def _call_with_retry(
        self, method: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        """Call API method with automatic retry on 401 errors.

        Args:
            method: API method to call
            *args: Positional arguments for method
            **kwargs: Keyword arguments for method

        Returns:
            Result from API method

        Raises:
            Exception: If all retry attempts fail
        """
        max_retries = 2
        self._stats["total_requests"] += 1
        request_num = self._stats["total_requests"]

        for attempt in range(max_retries):
            try:
                # Ensure authenticated before request
                await self._ensure_auth()

                # Rate limiting
                await self._rate_limit()

                # Call actual API method
                method_name = method.__name__

                # Log URL endpoint based on method name
                endpoint_map = {
                    "get_stats": "/api/get_stats",
                    "get_extended_stats": "/api/get_extended_stats",
                    "set_battery_working_mode": "/api/set_battery_working_mode",
                    "set_grid_delivery": "/api/set_grid_delivery",
                    "set_boiler_mode": "/api/set_boiler_mode",
                    "format_battery": "/api/format_battery",
                    "set_battery_capacity": "/api/set_battery_capacity",
                    "set_box_mode": "/api/set_box_mode",
                    "set_grid_delivery_limit": "/api/set_grid_delivery_limit",
                    "set_formating_mode": "/api/set_formating_mode",
                }
                endpoint = endpoint_map.get(method_name, "/api/unknown")

                _LOGGER.debug(
                    f"📡 Request #{request_num}: {method_name}() → {endpoint} (attempt {attempt + 1}/{max_retries})"
                )

                # Log request parameters if any
                if args:
                    _LOGGER.debug(f"   📝 Args: {args}")

                result = await method(*args, **kwargs)

                self._stats["successful_requests"] += 1
                _LOGGER.debug(
                    f"✅ Request #{request_num}: {method_name}() successful "
                    f"(success rate: {self._stats['successful_requests']}/{self._stats['total_requests']})"
                )
                return result

            except OigCloudAuthError as e:
                self._stats["retry_count"] += 1
                _LOGGER.warning(
                    f"⚠️  Request #{request_num}: Auth error on attempt {attempt + 1}/{max_retries}: {e}"
                )

                if attempt < max_retries - 1:
                    # Force re-authentication on next attempt
                    self._last_auth_time = None
                    backoff = 2**attempt
                    _LOGGER.info(
                        f"🔄 Retrying in {backoff}s (retry #{self._stats['retry_count']})"
                    )
                    await asyncio.sleep(backoff)
                else:
                    self._stats["failed_requests"] += 1
                    _LOGGER.error(
                        f"❌ Request #{request_num}: All {max_retries} attempts failed "
                        f"(fail rate: {self._stats['failed_requests']}/{self._stats['total_requests']})"
                    )
                    raise

            except Exception as e:
                self._stats["failed_requests"] += 1
                _LOGGER.error(
                    f"❌ Request #{request_num}: Unexpected error in {method.__name__}: {e}"
                )
                raise

    # Wrapped API methods - delegate to underlying API with retry logic

    async def get_stats(self) -> Dict[str, Any]:
        """Get current statistics with retry logic."""
        return await self._call_with_retry(self._api.get_stats)

    async def get_extended_stats(
        self,
        data_type: str,
        from_date: str,
        to_date: str,
    ) -> Dict[str, Any]:
        """Get extended statistics with retry logic.

        Args:
            data_type: Type of data (e.g., 'batt', 'fve', 'grid', 'load')
            from_date: Start date in format YYYY-MM-DD
            to_date: End date in format YYYY-MM-DD
        """
        return await self._call_with_retry(
            self._api.get_extended_stats,
            data_type,
            from_date,
            to_date,
        )

    async def set_battery_working_mode(
        self,
        box_sn: str,
        mode: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Set battery working mode with retry logic."""
        method: Callable[..., Awaitable[Any]] = getattr(
            self._api, "set_battery_working_mode"
        )
        return await self._call_with_retry(
            method,
            box_sn,
            mode,
            start_time,
            end_time,
        )

    async def set_grid_delivery(
        self,
        delivery_mode: int,
    ) -> Dict[str, Any]:
        """Set grid delivery mode with retry logic."""
        return await self._call_with_retry(
            self._api.set_grid_delivery,
            delivery_mode,
        )

    async def set_boiler_mode(
        self,
        mode: int,
    ) -> Dict[str, Any]:
        """Set boiler mode with retry logic."""
        return await self._call_with_retry(
            self._api.set_boiler_mode,
            mode,
        )

    async def format_battery(
        self,
        command: int,
    ) -> Dict[str, Any]:
        """Format battery with retry logic."""
        method: Callable[..., Awaitable[Any]] = getattr(self._api, "format_battery")
        return await self._call_with_retry(
            method,
            command,
        )

    async def set_battery_capacity(
        self,
        capacity_ah: float,
    ) -> Dict[str, Any]:
        """Set battery capacity with retry logic."""
        method: Callable[..., Awaitable[Any]] = getattr(
            self._api, "set_battery_capacity"
        )
        return await self._call_with_retry(
            method,
            capacity_ah,
        )

    async def set_box_mode(
        self,
        mode_value: str,
    ) -> Dict[str, Any]:
        """Set box mode with retry logic."""
        return await self._call_with_retry(
            self._api.set_box_mode,
            mode_value,
        )

    async def set_box_prm2_app(self, value: int) -> Dict[str, Any]:
        """Set box_prm2.app with retry logic."""
        return await self._call_with_retry(self._api.set_box_prm2_app, value)

    async def set_grid_delivery_limit(
        self,
        limit: int,
    ) -> bool:
        """Set grid delivery limit with retry logic."""
        return await self._call_with_retry(
            self._api.set_grid_delivery_limit,
            limit,
        )

    async def set_formating_mode(
        self,
        mode: str,
    ) -> Dict[str, Any]:
        """Set formatting mode with retry logic."""
        return await self._call_with_retry(
            self._api.set_formating_mode,
            mode,
        )

    async def close(self) -> None:
        """Cleanup resources and log final statistics."""
        await asyncio.sleep(0)
        uptime = datetime.now() - self._stats["session_created"]

        _LOGGER.info("=" * 60)
        _LOGGER.info("📊 SESSION MANAGER FINAL STATISTICS")
        _LOGGER.info("=" * 60)
        _LOGGER.info(f"⏱️  Session uptime: {uptime}")
        _LOGGER.info(f"🔐 Total authentications: {self._stats['auth_count']}")
        _LOGGER.info(f"📡 Total requests: {self._stats['total_requests']}")
        _LOGGER.info(f"✅ Successful requests: {self._stats['successful_requests']}")
        _LOGGER.info(f"❌ Failed requests: {self._stats['failed_requests']}")
        _LOGGER.info(f"🔄 Retry count: {self._stats['retry_count']}")
        _LOGGER.info(f"⏸️  Rate limited: {self._stats['rate_limited_count']}")

        if self._stats["total_requests"] > 0:
            success_rate = (
                self._stats["successful_requests"] / self._stats["total_requests"]
            ) * 100
            _LOGGER.info(f"📈 Success rate: {success_rate:.1f}%")

            if uptime.total_seconds() > 0:
                req_per_min = (
                    self._stats["total_requests"] / uptime.total_seconds()
                ) * 60
                _LOGGER.info(f"⚡ Request rate: {req_per_min:.2f} req/min")

        _LOGGER.info("=" * 60)
        _LOGGER.debug("SessionManager closing")

        # OigCloudApi handles its own session cleanup
        self._last_auth_time = None
        self._last_request_time = None

    def get_statistics(self) -> Dict[str, Any]:
        """Get current session statistics.

        Returns:
            Dictionary with session statistics
        """
        uptime = datetime.now() - self._stats["session_created"]

        stats = dict(self._stats)
        stats["uptime_seconds"] = uptime.total_seconds()
        stats["uptime_str"] = str(uptime)

        if self._last_auth_time:
            session_age = datetime.now() - self._last_auth_time
            stats["current_session_age_seconds"] = session_age.total_seconds()
            stats["current_session_age_minutes"] = session_age.total_seconds() / 60
            stats["session_expires_in_minutes"] = (
                SESSION_TTL - session_age
            ).total_seconds() / 60

        if self._stats["total_requests"] > 0:
            stats["success_rate_percent"] = (
                self._stats["successful_requests"] / self._stats["total_requests"]
            ) * 100
            stats["requests_per_minute"] = (
                self._stats["total_requests"] / uptime.total_seconds()
            ) * 60

        return stats

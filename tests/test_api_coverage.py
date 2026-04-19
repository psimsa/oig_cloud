"""Tests to increase coverage for OigCloudApi.

Target: custom_components/oig_cloud/api/oig_cloud_api.py >= 80%
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
import pytest

from custom_components.oig_cloud.api.oig_cloud_api import (
    OigCloudApi,
    OigCloudApiError,
    OigCloudAuthError,
    lock,
)


@pytest.fixture
def api():
    mock_hass = MagicMock()
    inst = OigCloudApi("user", "pass", False, mock_hass)
    inst._logger = MagicMock()
    return inst


@pytest.fixture
def sample_stats():
    return {
        "dev01": {
            "ac_in": {
                "aci_vr": 230.0,
                "aci_vs": 230.0,
                "aci_vt": 230.0,
                "aci_wr": 0.0,
                "aci_ws": 0.0,
                "aci_wt": 0.0,
                "aci_f": 50.0,
            },
            "ac_out": {"aco_p": 0.0},
            "actual": {
                "aci_wr": 0.0,
                "aci_ws": 0.0,
                "aci_wt": 0.0,
                "aco_p": 0.0,
                "fv_p1": 0.0,
                "fv_p2": 0.0,
                "bat_p": 0.0,
                "bat_c": 0.0,
                "viz": 0,
            },
            "batt": {"bat_c": 50},
            "dc_in": {"fv_proc": 0.0, "fv_p1": 0.0, "fv_p2": 0.0},
            "box_prms": {
                "bat_ac": 0,
                "p_fve": 0.0,
                "p_bat": 0.0,
                "mode": 0,
                "mode1": 0,
                "crct": 0,
                "crcte": 0,
            },
            "invertor_prms": {"to_grid": 0},
            "invertor_prm1": {"p_max_feed_grid": 0},
        }
    }


def _make_response(status=200, text='[[0,2,"OK"]]', json_data=None):
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.text = AsyncMock(return_value=text)
    if json_data is not None:
        mock_response.json = AsyncMock(return_value=json_data)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)
    return mock_response


def _make_session(response):
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=response)
    mock_session.get = MagicMock(return_value=response)
    mock_session.cookie_jar = Mock()
    mock_session_cls = MagicMock()
    mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_session_cls


class TestAuthenticate:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_authenticate_success(self, mock_tracer, mock_session_cls, api):
        mock_response = _make_response(status=200, text='[[2,"",false]]')
        mock_cookie = Mock()
        mock_cookie.value = "sess_123"
        mock_jar = Mock()
        mock_jar.filter_cookies.return_value = {"PHPSESSID": mock_cookie}

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.cookie_jar = mock_jar
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await api.authenticate()
        assert result is True
        assert api._phpsessid == "sess_123"

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_authenticate_wrong_response(self, mock_tracer, mock_session_cls, api):
        mock_response = _make_response(status=200, text='[[1,"bad",true]]')
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudAuthError):
            await api.authenticate()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_authenticate_http_error(self, mock_tracer, mock_session_cls, api):
        mock_response = _make_response(status=500, text="Server Error")
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudAuthError):
            await api.authenticate()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_authenticate_unexpected_exception(self, mock_tracer, mock_session_cls, api):
        mock_session_cls.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("boom"))
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudAuthError, match="boom"):
            await api.authenticate()


class TestGetSession:
    async def test_get_session_without_auth(self, api):
        api._phpsessid = None
        with pytest.raises(OigCloudAuthError):
            api.get_session()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    async def test_get_session_returns_session(self, mock_session_cls, api):
        api._phpsessid = "sess_abc"
        sess = api.get_session()
        assert sess is not None
        mock_session_cls.assert_called_once_with(headers={"Cookie": "PHPSESSID=sess_abc"})


class TestGetStats:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_uses_cache(self, mock_tracer, mock_session_cls, api):
        api._last_update = datetime.now()
        api.last_state = {"cached": True}

        result = await api.get_stats()
        assert result == {"cached": True}
        mock_session_cls.assert_not_called()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_fetches_and_sets_box_id(self, mock_tracer, mock_session_cls, api, sample_stats):
        api._phpsessid = "sess"
        api._last_update = datetime(1, 1, 1)

        mock_response = _make_response(status=200, json_data=sample_stats)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await api.get_stats()
        assert result == sample_stats
        assert api.box_id == "dev01"
        assert api.last_state == sample_stats
        assert api.last_parsed_state is not None

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_auth_retry_then_success(self, mock_tracer, mock_session_cls, api, sample_stats):
        api._phpsessid = "sess"
        api._last_update = datetime(1, 1, 1)

        with patch.object(api, "get_stats_internal", side_effect=[
            OigCloudAuthError("expired"),
            sample_stats,
        ]) as mock_internal:
            with patch.object(api, "authenticate", return_value=True) as mock_auth:
                result = await api.get_stats()
                assert result == sample_stats
                mock_auth.assert_called_once()
                assert mock_internal.call_count == 2

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_auth_retry_fails(self, mock_tracer, mock_session_cls, api):
        api._phpsessid = "sess"
        api._last_update = datetime(1, 1, 1)

        with patch.object(api, "get_stats_internal", side_effect=OigCloudAuthError("expired")):
            with patch.object(api, "authenticate", return_value=False):
                with pytest.raises(OigCloudAuthError):
                    await api.get_stats()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_unexpected_error(self, mock_tracer, mock_session_cls, api):
        api._phpsessid = "sess"
        api._last_update = datetime(1, 1, 1)

        with patch.object(api, "get_stats_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(OigCloudApiError, match="boom"):
                await api.get_stats()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_parse_error(self, mock_tracer, mock_session_cls, api):
        api._phpsessid = "sess"
        api._last_update = datetime(1, 1, 1)

        bad_data = {"dev01": {"ac_in": {"aci_vr": 1, "aci_vs": 1, "aci_vt": 1, "aci_wr": 1, "aci_ws": 1, "aci_wt": 1, "aci_f": 1}, "ac_out": {"aco_p": 1}, "actual": {"aci_wr": 1, "aci_ws": 1, "aci_wt": 1, "aco_p": 1, "fv_p1": 1, "fv_p2": 1, "bat_p": 1, "bat_c": 1, "viz": 1}, "batt": {}, "dc_in": {}, "box_prms": {"bat_ac": 1, "p_fve": 1, "p_bat": 1, "mode": 1, "mode1": 1, "crct": 1, "crcte": 1}, "invertor_prms": {"to_grid": 1}, "invertor_prm1": {"p_max_feed_grid": 1}}}

        mock_response = _make_response(status=200, json_data=bad_data)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await api.get_stats()
        assert result == bad_data
        assert api.last_parsed_state is not None
        api._logger.warning.assert_not_called()


class TestGetStatsInternal:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_internal_non_dict_then_retry(self, mock_tracer, mock_session_cls, api, sample_stats):
        api._phpsessid = "sess"

        resp1 = _make_response(status=200, json_data="not a dict")
        resp2 = _make_response(status=200, json_data=sample_stats)

        sess1 = MagicMock()
        sess1.get = MagicMock(return_value=resp1)
        sess2 = MagicMock()
        sess2.get = MagicMock(return_value=resp2)

        mock_session_cls.return_value.__aenter__ = AsyncMock(side_effect=[sess1, sess2])
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(api, "authenticate", return_value=True):
            result = await api.get_stats_internal()
            assert result == sample_stats

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_internal_non_dict_retry_also_bad(self, mock_tracer, mock_session_cls, api):
        api._phpsessid = "sess"

        resp1 = _make_response(status=200, json_data="not a dict")
        resp2 = _make_response(status=200, json_data="still not a dict")

        sess1 = MagicMock()
        sess1.get = MagicMock(return_value=resp1)
        sess2 = MagicMock()
        sess2.get = MagicMock(return_value=resp2)

        mock_session_cls.return_value.__aenter__ = AsyncMock(side_effect=[sess1, sess2])
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(api, "authenticate", return_value=True):
            result = await api.get_stats_internal()
            assert result == {}

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_internal_http_error(self, mock_tracer, mock_session_cls, api):
        api._phpsessid = "sess"

        resp = _make_response(status=503, json_data={})
        sess = MagicMock()
        sess.get = MagicMock(return_value=resp)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=sess)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudApiError, match="503"):
            await api.get_stats_internal()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_internal_dependent_no_retry(self, mock_tracer, mock_session_cls, api):
        api._phpsessid = "sess"

        resp = _make_response(status=200, json_data="not a dict")
        sess = MagicMock()
        sess.get = MagicMock(return_value=resp)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=sess)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await api.get_stats_internal(dependent=True)
        assert result == "not a dict"


class TestSetModes:
    async def test_set_box_mode_success(self, api):
        with patch.object(api, "set_box_params_internal", return_value=True) as m:
            result = await api.set_box_mode("2")
            assert result is True
            m.assert_called_once_with("box_prms", "mode", "2")

    async def test_set_box_mode_error(self, api):
        with patch.object(api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(OigCloudApiError, match="boom"):
                await api.set_box_mode("2")

    async def test_set_boiler_mode_success(self, api):
        with patch.object(api, "set_box_params_internal", return_value=True) as m:
            result = await api.set_boiler_mode("1")
            assert result is True
            m.assert_called_once_with("boiler_prms", "manual", "1")

    async def test_set_boiler_mode_error(self, api):
        with patch.object(api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(OigCloudApiError, match="boom"):
                await api.set_boiler_mode("1")

    async def test_set_grid_delivery_limit_success(self, api):
        with patch.object(api, "set_box_params_internal", return_value=True) as m:
            result = await api.set_grid_delivery_limit(5000)
            assert result is True
            m.assert_called_once_with("invertor_prm1", "p_max_feed_grid", 5000)

    async def test_set_grid_delivery_limit_error(self, api):
        with patch.object(api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(OigCloudApiError, match="boom"):
                await api.set_grid_delivery_limit(5000)

    async def test_set_box_prm2_app_success(self, api):
        with patch.object(api, "set_box_params_internal", return_value=True) as m:
            result = await api.set_box_prm2_app(2)
            assert result is True
            m.assert_called_once_with("box_prm2", "app", "2")

    async def test_set_box_prm2_app_error(self, api):
        with patch.object(api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(OigCloudApiError, match="boom"):
                await api.set_box_prm2_app(2)


class TestSetBoxParamsInternal:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_box_params_internal_success(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        api.box_id = "box01"
        mock_time.time.return_value = 1000.0

        mock_response = _make_response(status=200, text='[[0,2,"OK"]]')
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await api.set_box_params_internal("box_prms", "mode", "1")
        assert result is True

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_box_params_internal_no_box_id(self, mock_tracer, api):
        api.box_id = None
        with pytest.raises(OigCloudApiError, match="Box ID"):
            await api.set_box_params_internal("t", "c", "v")

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_box_params_internal_http_error(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        api.box_id = "box01"
        mock_time.time.return_value = 1000.0

        mock_response = _make_response(status=400, text="Bad Request")
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudApiError, match="400"):
            await api.set_box_params_internal("t", "c", "v")


class TestSetGridDelivery:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_grid_delivery_success(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        api.box_id = "box01"
        api._no_telemetry = False
        mock_time.time.return_value = 1000.0

        mock_response = _make_response(status=200, text='[[0,2,"OK"]]')
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await api.set_grid_delivery(1)
        assert result is True

    async def test_set_grid_delivery_no_telemetry(self, api):
        api._no_telemetry = True
        with pytest.raises(OigCloudApiError, match="telemetri"):
            await api.set_grid_delivery(1)

    async def test_set_grid_delivery_no_box_id(self, api):
        api._no_telemetry = False
        api.box_id = None
        api._phpsessid = "sess"
        with pytest.raises(OigCloudApiError, match="Box ID"):
            await api.set_grid_delivery(1)

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_grid_delivery_http_error(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        api.box_id = "box01"
        api._no_telemetry = False
        mock_time.time.return_value = 1000.0

        mock_response = _make_response(status=403, text="Forbidden")
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudApiError, match="403"):
            await api.set_grid_delivery(1)

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_grid_delivery_unexpected_error(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        api.box_id = "box01"
        api._no_telemetry = False
        mock_time.time.return_value = 1000.0

        mock_session_cls.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("boom"))
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudApiError, match="boom"):
            await api.set_grid_delivery(1)


class TestSetFormatingMode:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_formating_mode_success(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        mock_time.time.return_value = 1000.0

        mock_response = _make_response(status=200, text='[[0,2,"OK"]]')
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await api.set_formating_mode("1")
        assert result is True

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_formating_mode_http_error(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        mock_time.time.return_value = 1000.0

        mock_response = _make_response(status=500, text="Internal Server Error")
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudApiError, match="500"):
            await api.set_formating_mode("1")

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_formating_mode_unexpected_error(self, mock_tracer, mock_time, mock_session_cls, api):
        api._phpsessid = "sess"
        mock_time.time.return_value = 1000.0

        mock_session_cls.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("boom"))
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(OigCloudApiError, match="boom"):
            await api.set_formating_mode("1")


class TestGetData:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_data_success(self, mock_tracer, api, sample_stats):
        with patch.object(api, "get_stats", return_value=sample_stats) as m:
            result = await api.get_data()
            assert result == sample_stats
            m.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_data_empty(self, mock_tracer, api):
        with patch.object(api, "get_stats", return_value={}) as m:
            result = await api.get_data()
            assert result == {}
            m.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_data_raises(self, mock_tracer, api):
        with patch.object(api, "get_stats", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await api.get_data()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_typed_data_success(self, mock_tracer, api, sample_stats):
        with patch.object(api, "get_stats", return_value=sample_stats) as m:
            result = await api.get_typed_data()
            assert result is not None
            assert "dev01" in result.devices
            m.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_typed_data_empty(self, mock_tracer, api):
        with patch.object(api, "get_stats", return_value={}) as m:
            result = await api.get_typed_data()
            assert result is None
            m.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_typed_data_raises(self, mock_tracer, api):
        with patch.object(api, "get_stats", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await api.get_typed_data()


class TestInit:
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_init_sets_defaults(self, mock_tracer):
        mock_hass = MagicMock()
        api = OigCloudApi("u", "p", True, mock_hass)
        assert api._username == "u"
        assert api._password == "p"
        assert api._no_telemetry is True
        assert api._phpsessid is None
        assert api.box_id is None
        assert api.last_state is None
        assert api.last_parsed_state is None

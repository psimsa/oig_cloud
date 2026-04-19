from unittest.mock import MagicMock, patch

import pytest

from custom_components.oig_cloud.shared.logging import (
    _redact_sensitive,
    setup_otel_logging,
)


class TestRedactSensitive:
    def test_redacts_long_string(self) -> None:
        assert _redact_sensitive("supersecret1234") == "****1234"

    def test_redacts_exactly_show_chars(self) -> None:
        assert _redact_sensitive("abcd", show_chars=4) == "****"

    def test_redacts_shorter_than_show_chars(self) -> None:
        assert _redact_sensitive("abc", show_chars=4) == "****"

    def test_redacts_empty_string(self) -> None:
        assert _redact_sensitive("") == "****"

    def test_redacts_non_string(self) -> None:
        assert _redact_sensitive(str(12345)) == "****2345"

    def test_custom_show_chars(self) -> None:
        assert _redact_sensitive("hello_world", show_chars=5) == "****world"

    def test_show_chars_zero(self) -> None:
        assert _redact_sensitive("anything", show_chars=0) == "****anything"


class TestSetupOtelLogging:
    @patch("custom_components.oig_cloud.shared.logging.get_resource")
    @patch("custom_components.oig_cloud.shared.logging.LoggerProvider")
    @patch("custom_components.oig_cloud.shared.logging.set_logger_provider")
    @patch("custom_components.oig_cloud.shared.logging.OTLPLogExporter")
    @patch("custom_components.oig_cloud.shared.logging.BatchLogRecordProcessor")
    @patch("custom_components.oig_cloud.shared.logging.LoggingHandler")
    @patch("custom_components.oig_cloud.shared.logging.logging")
    def test_setup_otel_logging(
        self,
        mock_logging_module: MagicMock,
        mock_logging_handler: MagicMock,
        mock_batch_processor: MagicMock,
        mock_otlp_exporter: MagicMock,
        mock_set_logger_provider: MagicMock,
        mock_logger_provider_cls: MagicMock,
        mock_get_resource: MagicMock,
    ) -> None:
        fake_resource = MagicMock()
        mock_get_resource.return_value = fake_resource

        fake_logger_provider = MagicMock()
        mock_logger_provider_cls.return_value = fake_logger_provider

        fake_exporter = MagicMock()
        mock_otlp_exporter.return_value = fake_exporter

        fake_processor = MagicMock()
        mock_batch_processor.return_value = fake_processor

        fake_handler = MagicMock()
        mock_logging_handler.return_value = fake_handler

        result = setup_otel_logging(email_hash="hash123", hass_id="hass456")

        mock_get_resource.assert_called_once_with("hash123", "hass456")
        mock_logger_provider_cls.assert_called_once_with(resource=fake_resource)
        mock_set_logger_provider.assert_called_once_with(fake_logger_provider)
        mock_otlp_exporter.assert_called_once()
        fake_logger_provider.add_log_record_processor.assert_called_once_with(
            fake_processor
        )
        mock_logging_handler.assert_called_once_with(
            level=mock_logging_module.NOTSET,
            logger_provider=fake_logger_provider,
        )
        assert result is fake_handler

    @patch("custom_components.oig_cloud.shared.logging.get_resource")
    @patch("custom_components.oig_cloud.shared.logging.LoggerProvider")
    @patch("custom_components.oig_cloud.shared.logging.set_logger_provider")
    @patch("custom_components.oig_cloud.shared.logging.OTLPLogExporter")
    @patch("custom_components.oig_cloud.shared.logging.BatchLogRecordProcessor")
    @patch("custom_components.oig_cloud.shared.logging.LoggingHandler")
    @patch("custom_components.oig_cloud.shared.logging.logging")
    def test_setup_otel_logging_exporter_args(
        self,
        mock_logging_module: MagicMock,
        mock_logging_handler: MagicMock,
        mock_batch_processor: MagicMock,
        mock_otlp_exporter: MagicMock,
        mock_set_logger_provider: MagicMock,
        mock_logger_provider_cls: MagicMock,
        mock_get_resource: MagicMock,
    ) -> None:
        from grpc import Compression
        from custom_components.oig_cloud.const import (
            OT_ENDPOINT,
            OT_HEADERS,
            OT_INSECURE,
        )

        fake_resource = MagicMock()
        mock_get_resource.return_value = fake_resource

        fake_logger_provider = MagicMock()
        mock_logger_provider_cls.return_value = fake_logger_provider

        fake_exporter = MagicMock()
        mock_otlp_exporter.return_value = fake_exporter

        fake_handler = MagicMock()
        mock_logging_handler.return_value = fake_handler

        setup_otel_logging(email_hash="a", hass_id="b")

        call_kwargs = mock_otlp_exporter.call_args.kwargs
        assert call_kwargs["endpoint"] == OT_ENDPOINT
        assert call_kwargs["insecure"] == OT_INSECURE
        assert call_kwargs["headers"] == OT_HEADERS
        assert call_kwargs["compression"] == Compression(2)

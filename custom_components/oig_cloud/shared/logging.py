import logging
from typing import Dict, Any

_LOGGER = logging.getLogger(__name__)

try:
    from grpc import Compression
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
        OTLPLogExporter,
    )
    from opentelemetry._logs import set_logger_provider

    _has_opentelemetry = True
except ImportError:
    _LOGGER.warning(
        "OpenTelemetry není nainstalován. Pro povolení telemetrie je nutné ručně nainstalovat balíček: pip install opentelemetry-exporter-otlp-proto-grpc==1.31.0"
    )
    _has_opentelemetry = False
    # Dummy definitions
    LoggerProvider = None  # type: ignore
    LoggingHandler = None  # type: ignore
    BatchLogRecordProcessor = None  # type: ignore
    OTLPLogExporter = None  # type: ignore
    set_logger_provider = None  # type: ignore
    Compression = None  # type: ignore

from ..const import OT_ENDPOINT, OT_HEADERS, OT_INSECURE
from .shared import get_resource


def setup_otel_logging(email_hash: str, hass_id: str) -> Any:
    if not _has_opentelemetry:
        _LOGGER.warning("OpenTelemetry není dostupný, vrací se dummy logging handler")
        return logging.NullHandler()

    try:
        resource = get_resource(email_hash, hass_id)

        logger_provider: LoggerProvider = LoggerProvider(resource=resource)
        set_logger_provider(logger_provider)

        exporter: OTLPLogExporter = OTLPLogExporter(
            endpoint=OT_ENDPOINT,
            insecure=OT_INSECURE,
            headers=OT_HEADERS,
            compression=Compression(2),
        )

        logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        logging_handler: LoggingHandler = LoggingHandler(
            level=logging.NOTSET, logger_provider=logger_provider
        )
        return logging_handler
    except Exception as e:
        _LOGGER.error(
            f"Chyba při nastavování OpenTelemetry loggingu: {e}", exc_info=True
        )
        return logging.NullHandler()

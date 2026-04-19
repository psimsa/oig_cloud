from grpc import Compression
import logging
from typing import Dict

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter,
)

from opentelemetry._logs import set_logger_provider

from ..const import OT_ENDPOINT, OT_HEADERS, OT_INSECURE
from .shared import get_resource


def _redact_sensitive(value: str, show_chars: int = 4) -> str:
    """Redact most of a sensitive string value for logging.

    Args:
        value: The sensitive value to redact.
        show_chars: Number of characters to show at the end (default 4).

    Returns:
        Redacted string like "****last4".
    """
    if not isinstance(value, str) or len(value) <= show_chars:
        return "****"
    return f"****{value[-show_chars:]}"


def setup_otel_logging(email_hash: str, hass_id: str) -> LoggingHandler:
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

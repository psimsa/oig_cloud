from grpc import Compression
import logging
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter,
)

from opentelemetry._logs import set_logger_provider

from custom_components.oig_cloud.const import OT_ENDPOINT, OT_HEADERS, OT_INSECURE
from custom_components.oig_cloud.shared.shared import get_resource


def setup_otel_logging(email_hash: str, hass_id: str) -> LoggingHandler:
    resource = get_resource(email_hash, hass_id)

    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)

    exporter = OTLPLogExporter(
        endpoint=OT_ENDPOINT,
        insecure=OT_INSECURE,
        headers=OT_HEADERS,
        compression=Compression(2),
    )

    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    logging_handler = LoggingHandler(
        level=logging.NOTSET, logger_provider=logger_provider
    )
    return logging_handler

from grpc import Compression
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry._logs import set_logger_provider

from ..const import OT_RESOURCE, OT_ENDPOINT, OT_HEADERS, OT_INSECURE

import logging

logger_provider = LoggerProvider(resource=OT_RESOURCE)
set_logger_provider(logger_provider)

exporter = OTLPLogExporter(
    endpoint=OT_ENDPOINT, insecure=OT_INSECURE, headers=OT_HEADERS, compression=Compression(2)
)

logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
LOGGING_HANDLER = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)

import logging
from typing import Dict, Any

_LOGGER = logging.getLogger(__name__)

try:
    from grpc import Compression
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource

    _has_opentelemetry = True
except ImportError:
    _LOGGER.warning(
        "OpenTelemetry není nainstalován. Pro povolení telemetrie je nutné ručně nainstalovat balíček: pip install opentelemetry-exporter-otlp-proto-grpc==1.31.0"
    )
    _has_opentelemetry = False
    # Dummy definitions
    trace = None  # type: ignore
    Resource = None  # type: ignore
    TracerProvider = None  # type: ignore
    BatchSpanProcessor = None  # type: ignore
    OTLPSpanExporter = None  # type: ignore
    Compression = None  # type: ignore

from ..const import OT_ENDPOINT, OT_HEADERS, OT_INSECURE
from .shared import get_resource


def setup_tracer(module_name: str) -> Any:
    """Set up and return a tracer for the given module.

    Args:
        module_name: The name of the module to trace

    Returns:
        A tracer instance for the module or None if OpenTelemetry is not available
    """
    if not _has_opentelemetry or trace is None:
        _LOGGER.debug(
            f"OpenTelemetry not available, returning dummy tracer for {module_name}"
        )
        return None
    return trace.get_tracer(module_name)


def setup_tracing(email_hash: str, hass_id: str) -> None:
    """Set up tracing with the OpenTelemetry exporter.

    Args:
        email_hash: Hash of the user's email address
        hass_id: Home Assistant instance ID
    """
    if not _has_opentelemetry:
        _LOGGER.warning("OpenTelemetry není dostupný, telemetrie nebude fungovat")
        return

    try:
        resource: Resource = get_resource(email_hash, hass_id)

        trace_provider: TracerProvider = TracerProvider(resource=resource)

        trace_processor: BatchSpanProcessor = BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=OT_ENDPOINT,
                insecure=OT_INSECURE,
                headers=OT_HEADERS,
                compression=Compression(2),
            )
        )

        trace.set_tracer_provider(trace_provider)
        trace_provider.add_span_processor(trace_processor)
    except Exception as e:
        _LOGGER.error(f"Chyba při nastavování telemetrie: {e}", exc_info=True)

from grpc import Compression
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..const import OT_RESOURCE, OT_ENDPOINT, OT_HEADERS, OT_INSECURE

trace_provider = TracerProvider(resource=OT_RESOURCE)

trace_processor = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint=OT_ENDPOINT,
        insecure=OT_INSECURE,
        headers=OT_HEADERS,
        compression=Compression(2),
    )
)

trace.set_tracer_provider(trace_provider)

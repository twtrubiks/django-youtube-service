"""OpenTelemetry configuration — called once at startup via settings.py."""

import logging
import os

logger = logging.getLogger(__name__)


def configure_opentelemetry():
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otel_endpoint:
        return  # OTel disabled when no endpoint configured

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but OpenTelemetry packages are not installed. "
            "Install with: pip install -r requirements-otel.txt"
        )
        return

    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "streamcraft")})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otel_endpoint)))
    trace.set_tracer_provider(provider)

    DjangoInstrumentor().instrument()
    CeleryInstrumentor().instrument()

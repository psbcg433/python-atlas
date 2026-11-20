"""OpenTelemetry tracing: auto-instrumented FastAPI spans plus our own, sent to an exporter.

Each app gets its own TracerProvider (on app.state), instead of the process-global one, so
tests and notebooks can build many apps. NOTES_OTEL_EXPORTER picks where spans go:
"none" (default), "console", "otlp" (an OpenTelemetry Collector, Jaeger, Tempo...) or
"memory" (kept on app.state.span_exporter, for tests).
"""

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer

from notes_api import __version__
from notes_api.core.config import Settings

NOT_TRACED = "health,metrics"  # comma-separated URL patterns the instrumentation skips


def make_exporter(settings: Settings) -> SpanExporter | None:
    """The span exporter the settings ask for (None: tracing off)."""
    if settings.otel_exporter == "console":
        return ConsoleSpanExporter()
    if settings.otel_exporter == "memory":
        return InMemorySpanExporter()
    if settings.otel_exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(endpoint=settings.otel_endpoint, timeout=5)
    return None


def install_tracing(app: FastAPI, settings: Settings) -> Tracer:
    """Instrument the app (call it last: the tracing middleware must be the outermost)."""
    resource = Resource.create(
        {
            "service.name": "notes-api",
            "service.version": __version__,
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = make_exporter(settings)
    if exporter is not None:
        # Batch in production (spans leave in the background); one by one for tests and demos
        batched = settings.otel_exporter == "otlp"
        provider.add_span_processor(
            BatchSpanProcessor(exporter) if batched else SimpleSpanProcessor(exporter)
        )
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=NOT_TRACED)
    app.state.tracer_provider = provider
    app.state.span_exporter = exporter
    return provider.get_tracer("notes_api")

"""
WeatherChatPython - a simple console app that asks a Claude model on
Azure AI Foundry about the weather, with OTEL telemetry exported to
Application Insights.

Uses the AnthropicFoundry client from the Anthropic Python SDK, which
natively talks to Azure AI Foundry endpoints, combined with the
opentelemetry-instrumentation-anthropic package that emits:
  - gen_ai.usage.cache_creation.input_tokens
  - gen_ai.usage.cache_read.input_tokens
as span attributes.
"""

import os
import sys

from anthropic import AnthropicFoundry, APIError
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from azure.monitor.opentelemetry.exporter import (
    AzureMonitorTraceExporter,
    AzureMonitorMetricExporter,
)
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Your Azure AI Foundry resource name (the part before .services.ai.azure.com)
# Override with ANTHROPIC_FOUNDRY_RESOURCE env var if you prefer.
FOUNDRY_RESOURCE = os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE", "your-foundry-resource")

# The Claude model deployed on your Foundry resource
MODEL_NAME = os.environ.get("FOUNDRY_MODEL_NAME", "claude-sonnet-4-20250514")

APP_INSIGHTS_CONNECTION_STRING = (
    "InstrumentationKey=cfbc4eae-b34d-47e1-91b8-6bb19d315373;"
    "IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;"
    "LiveEndpoint=https://eastus.livediagnostics.monitor.azure.com/;"
    "ApplicationId=9ebafd11-a230-44bb-bc57-4cdcc42646a8"
)


def setup_telemetry():
    """Configure OpenTelemetry tracing & metrics with Azure Monitor export."""

    # --- Tracing ---
    trace_exporter = AzureMonitorTraceExporter(
        connection_string=APP_INSIGHTS_CONNECTION_STRING,
    )
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    metric_exporter = AzureMonitorMetricExporter(
        connection_string=APP_INSIGHTS_CONNECTION_STRING,
    )
    metric_reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # --- Instrument Anthropic SDK ---
    # This automatically patches anthropic.Anthropic / AsyncAnthropic so that
    # every messages.create() call emits spans with:
    #   gen_ai.usage.input_tokens
    #   gen_ai.usage.output_tokens
    #   gen_ai.usage.cache_creation.input_tokens
    #   gen_ai.usage.cache_read.input_tokens
    AnthropicInstrumentor().instrument()

    return tracer_provider, meter_provider


def main() -> int:
    tracer_provider, meter_provider = setup_telemetry()

    # ----- Resolve auth: API key or Azure AD --------------------------------
    api_key = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY", "").strip()
    azure_ad_token_provider = None

    if not api_key:
        # Try Azure AD (Entra) authentication via DefaultAzureCredential
        try:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            credential = DefaultAzureCredential()
            azure_ad_token_provider = get_bearer_token_provider(
                credential, "https://ai.azure.com/.default"
            )
            print("Using Azure AD (Entra) authentication.")
        except Exception:
            # Fall back to prompting for API key
            api_key = input("Enter your Foundry API key: ").strip()
            if not api_key:
                print("Error: An API key or Azure AD credential is required.", file=sys.stderr)
                return 1

    # ----- Create AnthropicFoundry client -----------------------------------
    client_kwargs = {"resource": FOUNDRY_RESOURCE}
    if azure_ad_token_provider:
        client_kwargs["azure_ad_token_provider"] = azure_ad_token_provider
    else:
        client_kwargs["api_key"] = api_key

    client = AnthropicFoundry(**client_kwargs)

    user_prompt = (
        "How do you call a person who wants to see before they can believe?"
    )

    print()
    print(f"You: {user_prompt}")
    print()

    try:
        message = client.messages.create(
            model=MODEL_NAME,
            max_tokens=1024,
            system="You are a helpful weather assistant.",
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        assistant_text = message.content[0].text
        print(f"Assistant: {assistant_text}")

        # Print cache token info if available
        if message.usage:
            cache_creation = getattr(
                message.usage, "cache_creation_input_tokens", None
            )
            cache_read = getattr(
                message.usage, "cache_read_input_tokens", None
            )
            if cache_creation is not None or cache_read is not None:
                print()
                print(f"  Cache creation tokens: {cache_creation or 0}")
                print(f"  Cache read tokens    : {cache_read or 0}")

    except APIError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 1

    # Flush telemetry before exit
    tracer_provider.force_flush()
    meter_provider.force_flush()

    print()
    print("Telemetry flushed to Application Insights.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
WeatherChatPython - a console app that uses a Microsoft Agent Framework (MAF)
Agent with tool calling to answer weather questions, with OTEL telemetry
(including agent spans) exported to Application Insights.

This is the Python equivalent of the .NET WeatherChatMAF project.
"""

import asyncio
import json
import os
import sys
from typing import Annotated

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor as BaseSpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.trace import StatusCode, SpanKind
from azure.monitor.opentelemetry.exporter import (
    AzureMonitorTraceExporter,
    AzureMonitorMetricExporter,
)

from agent_framework import Agent, AgentResponse, tool
from agent_framework.observability import enable_instrumentation
from agent_framework_openai import OpenAIChatClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENDPOINT = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project"
DEPLOYMENT_NAMES = [
    "deployment-gpt-5.4-mini",
    "deployment-gpt-4o",
    "deployment-gpt-4o-mini",
    "deployment-o4-mini",
    "deployment-Phi-4",
    "deployment-DeepSeek-R1",
    "deployment-Llama-3.3-70B-Instruct",
]

FAKE_MODE = False
USE_GLOBAL = False

# APP_INSIGHTS_CONNECTION_STRING = (
#     "InstrumentationKey=978264a8-7be3-47ac-8c4e-fe3e62866da2;"
#     "IngestionEndpoint=https://centraluseuap-0.in.applicationinsights.azure.com/;"
#     "LiveEndpoint=https://centraluseuap.livediagnostics.monitor.azure.com/;"
#     "ApplicationId=aec2eac5-dab8-400c-9fec-de7d03a0eec2"
# )  # genai-roi-test-11

APP_INSIGHTS_CONNECTION_STRING = (
    "InstrumentationKey=2ccfb7eb-f0b9-47aa-bf42-75b4f78c1e23;"
    "IngestionEndpoint=https://westcentralus-6.in.aimon.applicationinsights.azure.com/;"
    "LiveEndpoint=https://westcentralus.livediagnostics.aimon.monitor.azure.com/;"
    "AADAudience=https://monitor.azure.com/;"
    "ApplicationId=69c761e5-ed5d-4ab5-9132-fd27e7d39e2d"
 )  # genai-global-path-1

#APP_INSIGHTS_CONNECTION_STRING = (
#    "InstrumentationKey=2ccfb7eb-f0b9-47aa-bf42-75b4f78c1e23;"
#    "IngestionEndpoint=https://breeze.aimon.applicationinsights.io;"
#    "AADAudience=https://monitor.azure.com/;"
#    "ApplicationId=69c761e5-ed5d-4ab5-9132-fd27e7d39e2d"
#)  # genai-global-path-1 global


# ---------------------------------------------------------------------------
# Weather tool - exposes the weather function for the MAF agent
# ---------------------------------------------------------------------------
@tool(name="get_current_weather", description="Gets the current weather for a given location.")
def get_current_weather(
    location: Annotated[str, "The city and state, e.g. San Francisco, CA"],
    unit: Annotated[str, "The temperature unit (defaults to fahrenheit)"] = "fahrenheit",
) -> str:
    weather_data = {
        "Seattle, WA": (55, "Rainy"),
        "San Francisco, CA": (63, "Foggy"),
        "New York, NY": (72, "Sunny"),
    }

    temp_f, condition = weather_data.get(location, (68, "Partly cloudy"))

    if unit == "celsius":
        temp = int((temp_f - 32) * 5.0 / 9.0)
        unit_label = "\u00b0C"
    else:
        temp = temp_f
        unit_label = "\u00b0F"

    print(f'[Tool] get_current_weather("{location}", "{unit}")')

    return json.dumps({
        "location": location,
        "temperature": f"{temp}{unit_label}",
        "condition": condition,
    })


# ---------------------------------------------------------------------------
# Telemetry setup
# ---------------------------------------------------------------------------
class TestSpanProcessor(BaseSpanProcessor):
    """Stamps every span with test.agent and test.protocol attributes."""
    def __init__(self, agent_name: str, protocol: str):
        self._agent_name = agent_name
        self._protocol = protocol

    def on_start(self, span, parent_context=None):
        span.set_attribute("test.agent", self._agent_name)
        span.set_attribute("test.protocol", self._protocol)

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=None):
        return True


def setup_telemetry(connection_string: str):
    """Configure OpenTelemetry tracing & metrics with Azure Monitor export."""
    # --- Tracing ---
    trace_exporter = AzureMonitorTraceExporter(connection_string=connection_string)
    resource = Resource.create({
        "service.name": "WeatherChatPython",
    })
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(TestSpanProcessor("WeatherChatPython", "completions"))
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    metric_exporter = AzureMonitorMetricExporter(connection_string=connection_string)
    metric_reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # --- Enable MAF instrumentation ---
    enable_instrumentation()

    return tracer_provider, meter_provider


# ---------------------------------------------------------------------------
# Fake GenAI dependency - emits a span with all attributes that Breeze's
# GenAICostEnrichment reads for cost calculation.
# ---------------------------------------------------------------------------
def emit_fake_genai_dependency(tracer: trace.Tracer):
    with tracer.start_as_current_span(
        "chat deployment-gpt-5.4-mini", kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("fake_span", "true")
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", "deployment-gpt-5.4-mini")
        span.set_attribute("gen_ai.response.finish_reasons", "stop")
        span.set_attribute("gen_ai.response.id", "chatcmpl-DRlntxPA5EynvSpG4lxuG5c7q4l9B")
        span.set_attribute("gen_ai.response.model", "gpt-5.4-mini-2026-03-17")
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.usage.input_tokens", 44)
        span.set_attribute("gen_ai.usage.output_tokens", 38)

        span.set_attribute("server.address", ENDPOINT)
        span.set_attribute("server.port", 443)
        span.set_status(StatusCode.OK)

    print("[FakeGenAI] Emitted fake GenAI dependency span with cost-enrichment attributes.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    # Resolve App Insights connection string
    connection_string = APP_INSIGHTS_CONNECTION_STRING
    if USE_GLOBAL:
        parts = connection_string.split(";")
        parts = [
            p for p in parts
            if p and not p.strip().lower().startswith(("ingestionendpoint=", "liveendpoint="))
        ]
        connection_string = ";".join(parts)

    tracer_provider, meter_provider = setup_telemetry(connection_string)

    print("Enter your Azure OpenAI API key: ")
    print(f"AppInsights: {connection_string}")

    if FAKE_MODE:
        tracer = trace.get_tracer("FakeGenAI")
        emit_fake_genai_dependency(tracer)

        tracer_provider.force_flush()
        meter_provider.force_flush()
        return 0

    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")

    if not api_key.strip():
        print("Error: An API key is required.", file=sys.stderr)
        return 1

    # ----- Build one MAF agent per deployment --------------------------------
    agents = []
    for deployment in DEPLOYMENT_NAMES:
        client = OpenAIChatClient(
            model=deployment,
            api_key=api_key,
            azure_endpoint=ENDPOINT,
            api_version="2024-12-01-preview",
        )
        agent = Agent(
            client,
            instructions="You are a helpful weather assistant. Use the get_current_weather tool to look up weather information when asked.",
            name=f"WeatherAgent-{deployment}",
            description="A helpful weather assistant that can look up current weather.",
            tools=[get_current_weather],
        )
        agents.append((deployment, agent))

    user_prompt = "What's the weather like in Seattle and San Francisco?"

    print()
    print(f"You: {user_prompt}")
    print()

    # ----- Invoke all agents in parallel ------------------------------------
    async def run_agent(deployment: str, agent: Agent):
        try:
            response: AgentResponse = await agent.run(user_prompt)
            return deployment, response, None
        except Exception as ex:
            return deployment, None, ex

    results = await asyncio.gather(
        *(run_agent(deployment, agent) for deployment, agent in agents)
    )

    for deployment, response, error in results:
        print(f"--- [{deployment}] ---")
        if error is not None:
            print(f"  Error: {error}", file=sys.stderr)
            continue

        if response and response.messages:
            for message in response.messages:
                if message.role == "assistant" and message.text:
                    print(f"  Assistant: {message.text}")

        print()

    # Flush telemetry before exit
    tracer_provider.force_flush()
    meter_provider.force_flush()

    print()
    print("Telemetry flushed to Application Insights.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

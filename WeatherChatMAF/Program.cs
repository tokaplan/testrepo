using System.ClientModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using Azure.Core;
using Azure.Core.Pipeline;
using Azure.Monitor.OpenTelemetry.Exporter;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Azure.AI.OpenAI;
using OpenAI;
using OpenAI.Chat;
using OpenAI.Responses;
using OpenTelemetry;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

#pragma warning disable OPENAI001 // ResponsesClient is experimental

// ---------------------------------------------------------------------------
// WeatherChatMAF - a console app that uses a Microsoft Agent Framework (MAF)
// ChatClientAgent with tool calling to answer weather questions, with OTEL
// telemetry (including agent spans) exported to Application Insights.
// ---------------------------------------------------------------------------

const string endpoint = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project";
const string azureOpenAIEndpoint = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";
string[] deploymentNames = ["deployment-gpt-5.4-mini", "deployment-gpt-4o", "deployment-gpt-4o-mini", "deployment-o4-mini", "deployment-Phi-4", "deployment-DeepSeek-R1", "deployment-Llama-3.3-70B-Instruct"];
HashSet<string> noToolDeployments = ["deployment-Phi-4", "deployment-DeepSeek-R1"];
string runId = args.Length > 0 ? args[0] : Guid.NewGuid().ToString();

bool fakeMode = false;
bool useGlobal = false;

//const string appInsightsConnectionString = "InstrumentationKey=978264a8-7be3-47ac-8c4e-fe3e62866da2;IngestionEndpoint=https://centraluseuap-0.in.applicationinsights.azure.com/;LiveEndpoint=https://centraluseuap.livediagnostics.monitor.azure.com/;ApplicationId=aec2eac5-dab8-400c-9fec-de7d03a0eec2"; //genai-roi-test-11

string appInsightsConnectionString = "InstrumentationKey=2ccfb7eb-f0b9-47aa-bf42-75b4f78c1e23;IngestionEndpoint=https://westcentralus-6.in.aimon.applicationinsights.azure.com/;LiveEndpoint=https://westcentralus.livediagnostics.aimon.monitor.azure.com/;AADAudience=https://monitor.azure.com/;ApplicationId=69c761e5-ed5d-4ab5-9132-fd27e7d39e2d"; //genai-global-path-1
//string appInsightsConnectionString = "InstrumentationKey=2ccfb7eb-f0b9-47aa-bf42-75b4f78c1e23;IngestionEndpoint=https://breeze.aimon.applicationinsights.io;AADAudience=https://monitor.azure.com/;ApplicationId=69c761e5-ed5d-4ab5-9132-fd27e7d39e2d"; //genai-global-path-1 global

if (useGlobal)
{
    // Strip IngestionEndpoint and LiveEndpoint from the connection string at runtime
    var strippedParts = appInsightsConnectionString
        .Split(';', StringSplitOptions.RemoveEmptyEntries)
        .Where(part =>
        {
            var key = part.Split('=', 2)[0].Trim();
            return !key.Equals("IngestionEndpoint", StringComparison.OrdinalIgnoreCase)
                && !key.Equals("LiveEndpoint", StringComparison.OrdinalIgnoreCase);
        });
    appInsightsConnectionString = string.Join(";", strippedParts);
}

// Opt in to experimental OpenTelemetry for the OpenAI SDK
AppContext.SetSwitch("OpenAI.Experimental.EnableOpenTelemetry", true);

// ----- Configure OpenTelemetry tracing & metrics ---------------------------
const string FakeGenAISourceName = "FakeGenAI";
const string GenAISourceName = "WeatherChatMAF.GenAI";
ActivitySource fakeGenAISource = new(FakeGenAISourceName);

// Increase batch processor queue to avoid dropping spans during parallel execution
Environment.SetEnvironmentVariable("OTEL_BSP_MAX_QUEUE_SIZE", "10000");
Environment.SetEnvironmentVariable("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "1000");
Environment.SetEnvironmentVariable("OTEL_BSP_SCHEDULE_DELAY", "1000");

using var tracerProvider = Sdk.CreateTracerProviderBuilder()
    .ConfigureResource(r => r.AddService("WeatherChatMAF"))
    .AddProcessor(new TestAgentProcessor("WeatherChatMAF", runId))
    .AddSource("OpenAI.*")
    .AddSource("Microsoft.Agents.*")
    .AddSource("Experimental.Microsoft.Agents.AI")
    .AddSource("Microsoft.Extensions.AI.*")
    .AddSource(FakeGenAISourceName)
    .AddSource(GenAISourceName)
    .AddHttpClientInstrumentation()
    .AddAzureMonitorTraceExporter(o =>
    {
        o.ConnectionString = appInsightsConnectionString;
        o.SamplingRatio = 1.0f;
    })
    .Build();

using var meterProvider = Sdk.CreateMeterProviderBuilder()
    .AddMeter("OpenAI.*")
    .AddMeter("Microsoft.Agents.*")
    .AddMeter("Microsoft.Extensions.AI.*")
    .AddRuntimeInstrumentation()
    .AddHttpClientInstrumentation()
    .AddAzureMonitorMetricExporter(o =>
    {
        o.ConnectionString = appInsightsConnectionString;
        o.AddPolicy(new CustomHeaderPolicy(), HttpPipelinePosition.PerCall);
    })
    .Build();

// ----- Prompt for API key --------------------------------------------------
Console.WriteLine("Enter your Azure OpenAI API key: ");
Console.WriteLine($@"AppInsights: {appInsightsConnectionString}");

if (fakeMode)
{
    // Emit a fake GenAI dependency with all attributes Breeze's GenAICostEnrichment needs
    EmitFakeGenAIDependency(fakeGenAISource);

    tracerProvider?.ForceFlush();
    meterProvider?.ForceFlush();

    return 0;
}

string? apiKey = Environment.GetEnvironmentVariable("AZURE_OPENAI_API_KEY");// Console.ReadLine()?.Trim();

if (string.IsNullOrWhiteSpace(apiKey))
{
    Console.Error.WriteLine("Error: An API key is required.");
    return 1;
}

// ----- Build one MAF agent per deployment, sharing the same client ---
var baseUrl = endpoint + "/openai/v1/";
var openAIClient = new OpenAIClient(
    new ApiKeyCredential(apiKey),
    new OpenAIClientOptions { Endpoint = new Uri(baseUrl) });
var azureClient = new AzureOpenAIClient(
    new Uri(azureOpenAIEndpoint),
    new ApiKeyCredential(apiKey));
var tools = new List<AITool> { AIFunctionFactory.Create(WeatherPlugin.GetCurrentWeather) };

var agents = new List<(string label, AIAgent agent, string protocol)>();
HashSet<string> responsesApiDeployments = ["deployment-gpt-5.4-mini", "deployment-gpt-4o", "deployment-gpt-4o-mini", "deployment-o4-mini"];

foreach (var deployment in deploymentNames)
{
    bool useTools = !noToolDeployments.Contains(deployment);
    string instructions = useTools
        ? "You are a helpful weather assistant. Use the get_current_weather tool to look up weather information when asked."
        : "You are a helpful weather assistant. Answer weather questions using your knowledge. You do not have access to tools.";

    if (responsesApiDeployments.Contains(deployment))
    {
        // Responses API agent
        var respClient = openAIClient.GetResponsesClient()
            .AsIChatClient(defaultModelId: deployment)
            .AsBuilder().UseOpenTelemetry(sourceName: GenAISourceName).Build();
        AIAgent respAgent = new ChatClientAgent(respClient,
            instructions: instructions, name: $"WeatherAgent-{deployment}-responses",
            description: "Weather assistant", tools: tools);
        agents.Add(($"{deployment} [responses]", new OpenTelemetryAgent(respAgent), "responses"));

        // Chat Completions API agent for the same model
        var ccClient = azureClient.GetChatClient(deployment)
            .AsIChatClient()
            .AsBuilder().UseOpenTelemetry(sourceName: GenAISourceName).Build();
        AIAgent ccAgent = new ChatClientAgent(ccClient,
            instructions: instructions, name: $"WeatherAgent-{deployment}-completions",
            description: "Weather assistant", tools: tools);
        agents.Add(($"{deployment} [completions]", new OpenTelemetryAgent(ccAgent), "completions"));
    }
    else
    {
        // Chat Completions only
        var ccClient = azureClient.GetChatClient(deployment)
            .AsIChatClient()
            .AsBuilder().UseOpenTelemetry(sourceName: GenAISourceName).Build();
        AIAgent ccAgent = new ChatClientAgent(ccClient,
            instructions: instructions, name: $"WeatherAgent-{deployment}",
            description: "Weather assistant", tools: useTools ? tools : null);
        agents.Add(($"{deployment} [completions]", new OpenTelemetryAgent(ccAgent), "completions"));
    }
}

string userPrompt = "What's the weather like in Seattle and San Francisco?";

Console.WriteLine();
Console.WriteLine($"You: {userPrompt}");
Console.WriteLine();

// ----- Invoke all agents sequentially to avoid batch export race conditions ---
var results = new List<(string label, AgentResponse? response, Exception? error)>();
foreach (var (label, agent, protocol) in agents)
{
    TestAgentProcessor.SetProtocol(protocol);
    try
    {
        AgentResponse response = await agent.RunAsync(userPrompt);
        results.Add((label, response, null));
    }
    catch (Exception ex)
    {
        results.Add((label, null, ex));
    }
}

foreach (var (deployment, response, error) in results)
{
    Console.WriteLine($"--- [{deployment}] ---");
    if (error is not null)
    {
        Console.Error.WriteLine($"  Error: {error.Message}");
        continue;
    }

    Console.WriteLine($"  Messages: {response!.Messages.Count}");
    foreach (var message in response!.Messages)
    {
        if (message.Role == ChatRole.Assistant && !string.IsNullOrWhiteSpace(message.Text))
        {
            Console.WriteLine($"  Assistant: {message.Text}");
        }
    }

    Console.WriteLine();
}

// Flush telemetry before exit — wait briefly to let all spans complete
Thread.Sleep(2000);
tracerProvider?.ForceFlush(30000);
meterProvider?.ForceFlush(30000);

Console.WriteLine();
Console.WriteLine("Telemetry flushed to Application Insights.");
return 0;

// ---------------------------------------------------------------------------
// Fake GenAI dependency - emits a span with all attributes that Breeze's
// GenAICostEnrichment.cs reads for cost calculation.
//
// The enrichment requires:
//   1. The item is a dependency (Client/Internal span ? RemoteDependencyData)
//   2. gen_ai.operation.name is present and NOT in the excluded set
//      (excluded: retrieval, execute_tool, invoke_agent, create_agent)
//   3. Token counts: gen_ai.usage.input_tokens and/or gen_ai.usage.output_tokens
//   4. Model: gen_ai.response.model (preferred) or gen_ai.request.model (fallback)
//   5. Provider: gen_ai.provider.name (preferred) or gen_ai.system (fallback)
//   6. Optional: gen_ai.usage.cache_read.input_tokens,
//                gen_ai.usage.cache_creation.input_tokens
// ---------------------------------------------------------------------------
static void EmitFakeGenAIDependency(ActivitySource source)
{
    using (var activity = source.StartActivity("chat deployment-gpt-5.4-mini", ActivityKind.Client))
    {
        if (activity is null)
            return;

        activity.SetTag("fake_span", "true");
        activity.SetTag("gen_ai.operation.name", "chat");
        activity.SetTag("gen_ai.request.model", "deployment-gpt-5.4-mini");
        activity.SetTag("gen_ai.response.finish_reasons", "stop");
        activity.SetTag("gen_ai.response.id", "chatcmpl-DRlntxPA5EynvSpG4lxuG5c7q4l9B");
        activity.SetTag("gen_ai.response.model", "gpt-5.4-mini-2026-03-17");
        activity.SetTag("gen_ai.system", "openai");
        activity.SetTag("gen_ai.usage.input_tokens", 44);
        activity.SetTag("gen_ai.usage.output_tokens", 38);

        // Required by Azure Monitor exporter to construct a valid RemoteDependencyData envelope
        activity.SetTag("server.address", endpoint);
        activity.SetTag("server.port", 443);
        activity.SetStatus(ActivityStatusCode.Ok);
    }

    Console.WriteLine("[FakeGenAI] Emitted fake GenAI dependency span with cost-enrichment attributes.");
}

// ---------------------------------------------------------------------------
// Processor that stamps every span with test.agent
// ---------------------------------------------------------------------------
sealed class TestAgentProcessor(string agentName, string runId) : BaseProcessor<Activity>
{
    private static readonly AsyncLocal<string?> _protocol = new();

    public static void SetProtocol(string protocol) => _protocol.Value = protocol;

    public override void OnStart(Activity data)
    {
        data.SetTag("test.agent", agentName);
        data.SetTag("test.runId", runId);
        if (_protocol.Value is { } protocol)
            data.SetTag("test.protocol", protocol);
    }
}

// ---------------------------------------------------------------------------
// Custom HTTP pipeline policy - adds a header to every Breeze request
// ---------------------------------------------------------------------------
sealed class CustomHeaderPolicy : HttpPipelinePolicy
{
    public override void Process(HttpMessage message, ReadOnlyMemory<HttpPipelinePolicy> pipeline)
    {
        AddCustomHeader(message);
        ProcessNext(message, pipeline);
    }

    public override ValueTask ProcessAsync(HttpMessage message, ReadOnlyMemory<HttpPipelinePolicy> pipeline)
    {
        AddCustomHeader(message);
        return ProcessNextAsync(message, pipeline);
    }

    private static void AddCustomHeader(HttpMessage message)
    {
        message.Request.Headers.SetValue("x-ms-smoke-test-endpoint", "true");
    }
}

// ---------------------------------------------------------------------------
// Weather plugin - exposes the weather tool as a static method for MAF
// ---------------------------------------------------------------------------
static class WeatherPlugin
{
    [Description("Gets the current weather for a given location.")]
    public static string GetCurrentWeather(
        [Description("The city and state, e.g. San Francisco, CA")] string location,
        [Description("The temperature unit (defaults to fahrenheit)")] string unit = "fahrenheit")
    {
        var weatherData = new Dictionary<string, (int TempF, string Condition)>(StringComparer.OrdinalIgnoreCase)
        {
            ["Seattle, WA"] = (55, "Rainy"),
            ["San Francisco, CA"] = (63, "Foggy"),
            ["New York, NY"] = (72, "Sunny"),
        };

        if (!weatherData.TryGetValue(location, out var data))
            data = (68, "Partly cloudy");

        int temp = unit == "celsius" ? (int)((data.TempF - 32) * 5.0 / 9.0) : data.TempF;
        string unitLabel = unit == "celsius" ? "�C" : "�F";

        Console.WriteLine($"[Tool] get_current_weather(\"{location}\", \"{unit}\")");

        return JsonSerializer.Serialize(new
        {
            location,
            temperature = $"{temp}{unitLabel}",
            condition = data.Condition
        });
    }
}

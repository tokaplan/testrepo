using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using Azure.AI.OpenAI;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;
using Microsoft.OpenTelemetry;
using OpenAI;
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

#pragma warning disable OPENAI001 // ResponsesClient is experimental
#pragma warning disable MEAI001   // Microsoft.Extensions.AI experimental APIs

// ---------------------------------------------------------------------------
// WeatherChatMAF with Microsoft OpenTelemetry distro - multi-agent variant.
//
// Topology per protocol:
//   SequentialWorkflow
//   ├── MainAgent (orchestrator, has weather_data_agent.AsAIFunction() tool)
//   │   └── WeatherDataAgent (has get_current_weather raw tool)
//   └── VerifierAgent (no tools, sanity-checks the main's report)
// ---------------------------------------------------------------------------

const string endpoint = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project";
const string azureOpenAIEndpoint = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";

// Multi-agent topology: assign a different deployment to each agent role so
// a single workflow run produces telemetry from multiple models. Each agent's
// chat spans carry their own gen_ai.request.model / gen_ai.response.model.
const string dataDeployment     = "deployment-gpt-4o-mini";   // tool-caller
const string mainDeployment     = "deployment-gpt-5.4-mini";  // orchestrator
const string verifierDeployment = "deployment-gpt-4o";        // judge (chat model)

string runId = args.Length > 0 ? args[0] : Guid.NewGuid().ToString();
const string ServiceName = "WeatherChatMAF-MS-Distro";
const string GenAISourceName = "WeatherChatMAF.MSDistro";

string appInsightsConnectionString =
    Environment.GetEnvironmentVariable("APPLICATIONINSIGHTS_CONNECTION_STRING")
    ?? "InstrumentationKey=06533fcd-4317-4b63-9c52-a518c492d907;"
       + "IngestionEndpoint=https://eastus2-3.in.applicationinsights.azure.com/;"
       + "LiveEndpoint=https://eastus2.livediagnostics.monitor.azure.com/;"
       + "ApplicationId=66a40307-82d6-4baf-8886-37141dc8d391";

Console.WriteLine($"Service: {ServiceName}");
Console.WriteLine($"RunId:   {runId}");
Console.WriteLine($"AppInsights: {appInsightsConnectionString[..60]}...");

AppContext.SetSwitch("OpenAI.Experimental.EnableOpenTelemetry", true);

using var sdk = OpenTelemetrySdk.Create(otel =>
{
    otel.ConfigureResource(r => r.AddService(ServiceName));
    otel.UseMicrosoftOpenTelemetry(o =>
    {
        o.Exporters = ExportTarget.AzureMonitor;
        o.AzureMonitor.ConnectionString = appInsightsConnectionString;
    });
    otel.WithTracing(b => b.AddProcessor(new TestAgentProcessor(ServiceName, runId)));
});

string? apiKey = Environment.GetEnvironmentVariable("AZURE_OPENAI_API_KEY");
if (string.IsNullOrWhiteSpace(apiKey))
{
    Console.Error.WriteLine("Error: AZURE_OPENAI_API_KEY environment variable is required.");
    return 1;
}

var baseUrl = endpoint + "/openai/v1/";
var openAIClient = new OpenAIClient(
    new System.ClientModel.ApiKeyCredential(apiKey),
    new OpenAIClientOptions { Endpoint = new Uri(baseUrl) });
var azureClient = new AzureOpenAIClient(
    new Uri(azureOpenAIEndpoint),
    new System.ClientModel.ApiKeyCredential(apiKey));

var rawWeatherTool = AIFunctionFactory.Create(WeatherPlugin.GetCurrentWeather);

const string DataAgentInstructions =
    "You are a weather data lookup agent. For each city the caller asks about, "
    + "call get_current_weather exactly once and return the raw JSON results. "
    + "Do not narrate, do not editorialize — just return the data.";

const string MainAgentInstructions =
    "You are a friendly weather assistant. When the user asks about weather, "
    + "delegate the actual lookups to the weather_data_agent tool — call it ONCE "
    + "with all the cities the user mentioned, then summarize the data it returns "
    + "in a single conversational reply.";

const string VerifierInstructions =
    "You are a weather report verifier. You will be given the user's question "
    + "and the weather assistant's reply. Check that:\n"
    + "  1. Every city the user asked about is covered in the reply.\n"
    + "  2. No additional cities (not asked about) appear in the reply.\n"
    + "  3. The temperature/condition pairs are physically plausible "
    + "(e.g. not 'Snowy' at 80°F).\n"
    + "Reply with one line: either 'VERIFIED: <one-line summary>' "
    + "or 'WARN: <reason>'. Do not call any tools.";

// For each protocol, provide a factory that returns an IChatClient for a given deployment.
(string protocol, Func<string, IChatClient> makeClient)[] protocols =
{
    ("responses",   dep => openAIClient.GetResponsesClient().AsIChatClient(defaultModelId: dep)),
    ("completions", dep => azureClient.GetChatClient(dep).AsIChatClient()),
};

string userPrompt = "What's the weather like in Seattle and San Francisco?";

Console.WriteLine();
Console.WriteLine($"You: {userPrompt}");
Console.WriteLine($"Agent deployments: data={dataDeployment}, main={mainDeployment}, verifier={verifierDeployment}");
Console.WriteLine();

var results = new List<(string protocol, string? main, string? verifier, Exception? error)>();

foreach (var (protocol, makeClient) in protocols)
{
    TestAgentProcessor.SetProtocol(protocol);
    try
    {
        // Build a fresh chat client per agent role, each wrapped with telemetry so the
        // emitted gen_ai.request.model / gen_ai.response.model reflect the per-agent model.
        IChatClient dataChat     = makeClient(dataDeployment).AsBuilder().UseOpenTelemetry(sourceName: GenAISourceName).Build();
        IChatClient mainChat     = makeClient(mainDeployment).AsBuilder().UseOpenTelemetry(sourceName: GenAISourceName).Build();
        IChatClient verifierChat = makeClient(verifierDeployment).AsBuilder().UseOpenTelemetry(sourceName: GenAISourceName).Build();

        AIAgent rawData = new ChatClientAgent(dataChat,
            instructions: DataAgentInstructions,
            name: $"WeatherDataAgent-{protocol}",
            description: "Looks up weather for one or more cities via get_current_weather.",
            tools: new List<AITool> { rawWeatherTool });
        AIAgent dataAgent = new OpenTelemetryAgent(rawData);

        AITool weatherDataTool = dataAgent.AsAIFunction(new AIFunctionFactoryOptions
        {
            Name = "weather_data_agent",
            Description = "Delegate to the weather data agent. Pass the list of cities the user asked about.",
        });

        AIAgent rawMain = new ChatClientAgent(mainChat,
            instructions: MainAgentInstructions,
            name: $"MainWeatherAgent-{protocol}",
            description: "Friendly weather assistant that delegates lookups to a data agent.",
            tools: new List<AITool> { weatherDataTool });
        AIAgent mainAgent = new OpenTelemetryAgent(rawMain);

        AIAgent rawVerifier = new ChatClientAgent(verifierChat,
            instructions: VerifierInstructions,
            name: $"VerifierAgent-{protocol}",
            description: "Sanity-checks the main agent's weather report.");
        AIAgent verifierAgent = new OpenTelemetryAgent(rawVerifier);

        Workflow workflow = AgentWorkflowBuilder.BuildSequential(
            $"WeatherWorkflow-{protocol}",
            new[] { mainAgent, verifierAgent });

        // Run the workflow with the user prompt as a single ChatMessage.
        var inputMessages = new List<ChatMessage> { new(ChatRole.User, userPrompt) };
        await using StreamingRun run = await InProcessExecution.RunStreamingAsync(workflow, inputMessages);
        await run.TrySendMessageAsync(new TurnToken(emitEvents: true));

        // Accumulate streaming text per executor (order: main, then verifier).
        var perExecutorText = new Dictionary<string, System.Text.StringBuilder>();
        var executorOrder = new List<string>();
        await foreach (var evt in run.WatchStreamAsync())
        {
            if (evt is AgentResponseUpdateEvent upd)
            {
                if (!perExecutorText.ContainsKey(upd.ExecutorId))
                {
                    perExecutorText[upd.ExecutorId] = new System.Text.StringBuilder();
                    executorOrder.Add(upd.ExecutorId);
                }
                if (!string.IsNullOrEmpty(upd.Update.Text))
                    perExecutorText[upd.ExecutorId].Append(upd.Update.Text);
            }
            else if (evt is WorkflowOutputEvent)
            {
                // Sequential workflow completed - final messages available
            }
            else if (evt is ExecutorFailedEvent fail)
            {
                Console.Error.WriteLine($"  [failed] {fail.ExecutorId}: {fail.Data}");
            }
            else if (evt is WorkflowErrorEvent werr)
            {
                Console.Error.WriteLine($"  [werror] {werr.Exception}");
            }
        }

        string? mainText = executorOrder.Count > 0 ? perExecutorText[executorOrder[0]].ToString() : null;
        string? verifierText = executorOrder.Count > 1 ? perExecutorText[executorOrder[1]].ToString() : null;
        results.Add((protocol, mainText, verifierText, null));
    }
    catch (Exception ex)
    {
        results.Add((protocol, null, null, ex));
    }
}

int successes = 0;
foreach (var (protocol, mainText, verifierText, error) in results)
{
    Console.WriteLine($"--- [{protocol}] ---");
    if (error is not null)
    {
        Console.Error.WriteLine($"  Error: {error.Message}");
        continue;
    }
    successes++;

    if (!string.IsNullOrWhiteSpace(mainText))
        Console.WriteLine($"  Assistant: {mainText}");
    if (!string.IsNullOrWhiteSpace(verifierText))
        Console.WriteLine($"  Verifier:  {verifierText}");
    Console.WriteLine();
}

Console.WriteLine();
Console.WriteLine($"[run] {successes}/{results.Count} workflows succeeded");
return 0;

// ---------------------------------------------------------------------------
// Processor that stamps every span with test.agent / test.runId / test.protocol.
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
        string unitLabel = unit == "celsius" ? "\u00B0C" : "\u00B0F";

        Console.WriteLine($"[Tool] get_current_weather(\"{location}\", \"{unit}\")");

        return JsonSerializer.Serialize(new
        {
            location,
            temperature = $"{temp}{unitLabel}",
            condition = data.Condition
        });
    }
}

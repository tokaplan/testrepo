using System.ClientModel;
using Azure.AI.OpenAI;
using OpenAI.Chat;

// ---------------------------------------------------------------------------
// WeatherChat - a simple console app that asks an Azure OpenAI model about
// the weather using Chat Completions.
// ---------------------------------------------------------------------------

const string endpoint = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";
const string deploymentName = "gpt-4o";

// Prompt the user for the API key at startup
Console.Write("Enter your Azure OpenAI API key: ");
string? apiKey = Console.ReadLine()?.Trim();

if (string.IsNullOrWhiteSpace(apiKey))
{
    Console.Error.WriteLine("Error: An API key is required.");
    return 1;
}

// Create the Azure OpenAI client
AzureOpenAIClient azureClient = new(
    new Uri(endpoint),
    new ApiKeyCredential(apiKey));

ChatClient chatClient = azureClient.GetChatClient(deploymentName);

// Ask the model about the weather
string userPrompt = "What is the weather like in Seattle today? " +
                    "Give a short, friendly forecast including temperature, " +
                    "conditions, and what to wear.";

Console.WriteLine();
Console.WriteLine($"You: {userPrompt}");
Console.WriteLine();

try
{
    ChatCompletion completion = await chatClient.CompleteChatAsync(
        [
            new SystemChatMessage("You are a helpful weather assistant."),
            new UserChatMessage(userPrompt)
        ]);

    Console.WriteLine($"Assistant: {completion.Content[0].Text}");
}
catch (ClientResultException ex)
{
    Console.Error.WriteLine($"API error: {ex.Message}");
    return 1;
}

return 0;

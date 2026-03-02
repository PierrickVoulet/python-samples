# Enterprise AI Agent (local)

**Note:** This project is part of the official Google Codelabs [Integrate Vertex AI Agents with Google Workspace](https://codelabs.developers.google.com/vertexai-agents-gws).

This sample contains a specialized Enterprise Agent built using the Google Agent Development Kit (ADK). This agent acts as an Enterprise AI Assistant by querying user's data corpus using the Vertex AI Search MCP toolset and sending Chat messages to DM spaces using a custom Function tool & Google Chat API.

## Key Features

1. **Dynamic Vertex AI Serving Configs:** 
   The agent automatically discovers your project's `default_collection` engine and dynamically binds its queries to the `default_serving_config`.
   
2. **Static Authentication (`ACCESS_TOKEN`):** 
   The client (e.g. ADK Web) passes an authentication token in the `ACCESS_TOKEN` environment variable. This agent extracts the token at runtime to securely execute calls using a Bearer token.

3. **Graceful Timeouts:**
   The `McpToolset` streaming components have been intentionally configured with an explicit 15-second `timeout` and `sse_read_timeout` to prevent the agent from hanging infinitely on backend network issues.

4. **Google Chat Integration:**
   The agent natively includes a `send_direct_message` tool powered by the `google-apps-chat` SDK. This allows the AI to immediately send direct messages to users inside Google Chat. It seamlessly reuses the same authentication token extracted from the `ACCESS_TOKEN` environment variable.

## Deployment

The agent requires a valid OAuth access token to authenticate with Google APIs (Vertex AI Search, Google Chat).
To set the `ACCESS_TOKEN` environment variable with a valid token, you must authenticate using a **Desktop app OAuth client**.

1. Download your Desktop app OAuth client JSON file (e.g., `client_secret.json`) in the root directory.
2. Authenticate using `gcloud` with the client ID and required scopes:

```bash
gcloud auth application-default login \
  --client-id-file=client_secret.json \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/chat.spaces,https://www.googleapis.com/auth/chat.messages
```

3. Generate the access token and set the environment variable:

```bash
export ACCESS_TOKEN=$(gcloud auth application-default print-access-token)
```

4. Optionally, you can set the `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` environment variables (defaults to current gcloud project and `us-central1`).

5. Deploy the agent locally using the ADK `web` command:

```bash
adk web
```

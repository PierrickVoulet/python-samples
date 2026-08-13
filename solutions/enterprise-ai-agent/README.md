# Enterprise AI Agent

**Note:** This project is part of the official Google Codelabs [Integrate Gemini Enterprise Agents with Google Workspace](https://codelabs.developers.google.com/ge-gws-agents) and [Integrate Vertex AI Agents with Google Workspace](https://codelabs.developers.google.com/vertexai-agents-gws).

This sample contains a specialized Enterprise Agent built using the Google Agent Development Kit (ADK). This agent processes pending comments in given Google Docs and Google Sheets documents that are assigned to a specific user (by ID or email), reading and updating documents via Google Workspace MCPs and replying with an agent signature.

## Key Features

1. **Docs & Sheets Workspace MCPs:** 
   The agent integrates directly with Google-managed Workspace MCP servers for Google Docs (`https://docsmcp.googleapis.com/mcp/v1`) and Google Sheets (`https://sheetsmcp.googleapis.com/mcp/v1`) to inspect and update document content.
   
2. **Pending Comments Management:** 
   Custom tools (`list_pending_comments`, `get_comment_details`, `reply_to_comment`) enable the agent to find unresolved comments assigned to a given user, gather comment context, and post responses with an automated agent signature (`🤖 *Processed by Enterprise AI Agent*`).

3. **Dynamic Authentication (`ToolContext`):** 
   The client (e.g. Gemini Enterprise app, Google Workspace add-on) passes an authentication token in the session state (e.g., `enterprise-ai_12345`). This agent intercepts the `ToolContext` state and extracts the token at runtime using regex pattern matching (`^enterprise-ai_\d+$`) to securely authenticate all MCP and REST API calls using Bearer tokens.

4. **Graceful Timeouts:**
   The `McpToolset` streaming components have been configured with an explicit 15-second `timeout` and `sse_read_timeout` to prevent the agent from hanging on network latency.

## Deployment

This agent is designed to be deployed as a backend service with dynamic token injection into the `ToolContext` at runtime.

Deploy this agent directly to Vertex AI Agent Engines using the ADK CLI:

```bash
adk deploy agent_engine \
  --project=your-gcp-project-id \
  --region=us-central1 \
  --display_name="Enterprise AI" \
  enterprise_ai
```

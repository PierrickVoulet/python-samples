# Enterprise AI Agent

**Note:** This project is part of the official Google Codelabs [Integrate Gemini Enterprise Agents with Google Workspace](https://codelabs.developers.google.com/ge-gws-agents) and [Integrate Vertex AI Agents with Google Workspace](https://codelabs.developers.google.com/vertexai-agents-gws).

This sample contains a specialized Enterprise Agent built using the Google Agent Development Kit (ADK). The agent processes natural language requests to discover, copy, rename, inspect, filter, research, and modify Google Sheets spreadsheets in Google Drive, enriched with internal Google Workspace Universal Search.

## Key Features

1. **Google Drive Operations:**
   Custom function tools (`search_drive_file`, `copy_drive_file`, `rename_drive_file`) powered by the Google Drive REST API v3 enable the agent to find files in Drive by title, automatically create named copies, and rename files.

2. **Google Sheets MCP Only (No custom Sheets APIs):**
   Exclusively uses the Google-managed Workspace MCP server for Google Sheets (`https://sheetsmcp.googleapis.com/mcp/v1`) for all spreadsheet reading, inspection, value updates, and row deletions (via `update_spreadsheet` with `deleteDimension`).

3. **Universal Google Workspace Search MCP:**
   Integrates with the official [Universal Search MCP](https://developers.google.com/workspace/guides/universal-search-mcp) (`https://workspacemcp.googleapis.com/mcp/v1`) to retrieve internal organizational context across Google Workspace data (Drive, Gmail, Calendar).

4. **Headless & Factual Execution:**
   Runs completely autonomously without human-in-the-loop (HITL) pauses, using deterministic decoding (`temperature = 0.0`) and strict factual grounding on actual tool outputs.

5. **Dynamic Authentication (`ToolContext`):**
   The client (e.g. Gemini Enterprise app, Google Workspace add-on) passes an authentication token in the session state (e.g. `enterprise-ai_12345`). The agent intercepts the `ToolContext` state and extracts the token at runtime using regex pattern matching (`^enterprise-ai_\d+$`) to securely authenticate all MCP and REST API calls using Bearer tokens.

6. **Graceful Timeouts:**
   The `McpToolset` streaming components are configured with an explicit 15-second `timeout` and `sse_read_timeout` to prevent the agent from hanging on network latency.

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

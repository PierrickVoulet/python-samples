# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
import requests
from dotenv import load_dotenv
load_dotenv()

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams
from google.adk.tools import ToolContext, FunctionTool
from google.genai import types

MODEL = "gemini-2.5-flash"

# Client injects a bearer token into the ToolContext state.
# The key pattern is "CLIENT_AUTH_NAME_<random_digits>".
# We dynamically parse this token to authenticate our MCP and API calls.
CLIENT_AUTH_NAME = "enterprise-ai"

WORKSPACE_MCP_TIMEOUT = 15.0

def _get_access_token_from_context(tool_context: ToolContext) -> str:
    """Helper method to dynamically parse the intercepted bearer token from the context state."""
    escaped_name = re.escape(CLIENT_AUTH_NAME)
    pattern = re.compile(fr"^{escaped_name}_\d+$")
    # Handle ADK varying state object types (Raw Dict vs ADK State)
    state_dict = tool_context.state.to_dict() if hasattr(tool_context.state, 'to_dict') else tool_context.state
    matching_keys = [k for k in state_dict.keys() if pattern.match(k)]
    if matching_keys:
        return state_dict.get(matching_keys[0])
    raise Exception(f"No bearer token found in ToolContext state matching pattern {pattern.pattern}")

def auth_header_provider(tool_context: ToolContext) -> dict[str, str]:
    token = _get_access_token_from_context(tool_context)
    return {"Authorization": f"Bearer {token}"}

def search_drive_file(query: str, tool_context: ToolContext) -> dict:
    """Searches for Google Drive files by name or search term and returns the first matching file.

    Args:
        query: Name of the file (e.g. 'Our products', 'Interesting products') or search term.
        tool_context: The ToolContext containing authentication state.

    Returns:
        A dictionary with the first matching file's ID, name, and MIME type, or an empty dictionary if not found.
    """
    token = _get_access_token_from_context(tool_context)
    headers = {"Authorization": f"Bearer {token}"}

    escaped_query = query.replace("'", "\\'")
    q = f"(name = '{escaped_query}' or name contains '{escaped_query}') and trashed = false"
    url = "https://www.googleapis.com/drive/v3/files"
    params = {
        "q": q,
        "fields": "files(id, name, mimeType, modifiedTime)",
        "orderBy": "recency desc",
        "pageSize": 1,
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    files = response.json().get("files", [])
    if files:
        return files[0]
    return {}

def copy_drive_file(file_id: str, new_name: str | None = None, tool_context: ToolContext = None) -> dict:
    """Creates a copy of a Google Drive file and automatically assigns the requested title using Google Drive API v3.

    Args:
        file_id: The ID of the file to copy.
        new_name: The target title/name for the copied file (e.g. 'Interesting products - XXX company'). Optional.
        tool_context: The ToolContext containing authentication state.

    Returns:
        A dictionary with the copied file's ID, name, and MIME type.
    """
    token = _get_access_token_from_context(tool_context)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}/copy"
    body = {}
    if new_name:
        body["name"] = new_name
    response = requests.post(url, headers=headers, json=body, params={"fields": "id, name, mimeType"})
    response.raise_for_status()
    return response.json()

def rename_drive_file(file_id: str, new_name: str, tool_context: ToolContext) -> dict:
    """Renames an existing Google Drive file to a new title using Google Drive API v3.

    Args:
        file_id: The ID of the file to rename.
        new_name: The new title/name for the file.
        tool_context: The ToolContext containing authentication state.

    Returns:
        A dictionary with the updated file's ID, name, and MIME type.
    """
    token = _get_access_token_from_context(tool_context)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    body = {"name": new_name}
    response = requests.patch(url, headers=headers, json=body, params={"fields": "id, name, mimeType"})
    response.raise_for_status()
    return response.json()

def replace_spreadsheet_data(
    spreadsheet_id: str,
    values: list[list[str]],
    tool_context: ToolContext = None
) -> dict:
    """Replaces the entire spreadsheet data with the provided 2D array of rows in a 100% deterministic way.

    Args:
        spreadsheet_id: The ID of the spreadsheet to modify.
        values: The complete 2D array of retained rows to write, starting with the Header row at values[0].
        tool_context: The ToolContext containing authentication state.

    Returns:
        A dictionary confirming the update and the number of rows written.
    """
    token = _get_access_token_from_context(tool_context)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 1. Clear previous sheet data in bulk
    clear_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchClear"
    requests.post(clear_url, headers=headers, json={"ranges": ["A1:ZZ1000"]})

    # 2. Write the retained rows directly starting at cell A1
    update_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/A1"
    params = {"valueInputOption": "USER_ENTERED"}
    response = requests.put(update_url, headers=headers, params=params, json={"values": values})
    response.raise_for_status()

    return {
        "status": "success",
        "rows_written": len(values)
    }

# Google Workspace MCP Toolset for Google Sheets
sheets_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://sheetsmcp.googleapis.com/mcp/v1",
        timeout=WORKSPACE_MCP_TIMEOUT,
        sse_read_timeout=WORKSPACE_MCP_TIMEOUT,
    ),
    header_provider=auth_header_provider,
)

# Universal Google Workspace Search MCP Toolset
universal_gws_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://workspacemcp.googleapis.com/mcp/v1",
        timeout=WORKSPACE_MCP_TIMEOUT,
        sse_read_timeout=WORKSPACE_MCP_TIMEOUT,
    ),
    header_provider=auth_header_provider,
)

root_agent = LlmAgent(
    model=MODEL,
    name='enterprise_ai',
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0
    ),
    instruction="""
        You are an autonomous enterprise AI assistant that manages Google Drive files and Google Sheets spreadsheets.

        CRITICAL EXECUTION RULES:
        - When calling a tool, you MUST NOT generate any conversational text, narration, commentary, or thoughts in the same turn. Output ONLY the function call.
        - Never stop or output conversational text after reading rows with `get_values`.
        - YOU MUST IMMEDIATELY CALL `replace_spreadsheet_data` to physically apply the updates to the spreadsheet.
        - Conversational text summaries are ONLY permitted in the turn AFTER `replace_spreadsheet_data` has successfully executed.

        STEP-BY-STEP WORKFLOW:

        1. Locate & Copy Spreadsheet:
           - Search for the source spreadsheet by title using `search_drive_file(query=...)`.
           - When a copy is requested (e.g. "Create a copy of 'Our products' to 'Interesting products - XXX company'"), call `copy_drive_file(file_id=..., new_name="Interesting products - XXX company")`.
           - Always use the newly returned file `id` for subsequent inspection and update operations.

        2. Read Spreadsheet Content (Sheets MCP):
           - Call `get_spreadsheet(spreadsheetId=...)` on the target file to inspect sheet metadata.
           - Call `get_values(spreadsheetId=..., range="Sheet1!A1:Z500")` to read all existing rows.

        3. In-Memory Filtering:
           Let `values` be the 2D array returned by `get_values`:
           - `values[0]` is the Header row (Sheet Row 1). Always keep `values[0]`.
           - For each data row in `values[1:]`:
             * Evaluate the user's criteria (e.g. keep ONLY if product is currently in stock AND in the garden category).
           - Construct the list of retained rows: `retained_values = [values[0]] + [r for r in values[1:] if criteria_met]`.

        4. Deterministic Spreadsheet Update (Custom Tool):
           - Call `replace_spreadsheet_data(spreadsheet_id="<target_id>", values=retained_values)`.
           - This tool clears old data and writes the clean retained rows directly starting at cell A1.

        5. Final Output:
           - Provide a concise summary:
             * Target spreadsheet title and ID.
             * Exact criteria evaluated.
             * The number of rows removed (`len(values) - len(retained_values)`).
             * The number of rows retained (`len(retained_values)`).
    """,
    tools=[
        sheets_mcp,
        universal_gws_mcp,
        FunctionTool(search_drive_file),
        FunctionTool(copy_drive_file),
        FunctionTool(rename_drive_file),
        FunctionTool(replace_spreadsheet_data),
    ]
)

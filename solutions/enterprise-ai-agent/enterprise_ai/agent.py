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
AGENT_SIGNATURE = "Processed by Enterprise AI Agent"

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

def _grid_range_to_a1(sheet_title: str, start_row: int, start_col: int, end_row: int | None = None, end_col: int | None = None) -> str:
    """Converts 0-indexed row/column coordinates to A1 notation."""
    def col_to_letter(col_idx: int) -> str:
        result = ""
        col_idx_val = col_idx
        while col_idx_val >= 0:
            result = chr(col_idx_val % 26 + ord('A')) + result
            col_idx_val = col_idx_val // 26 - 1
        return result

    start_cell = f"{col_to_letter(start_col)}{start_row + 1}"
    if end_row is not None and end_col is not None and (end_row > start_row + 1 or end_col > start_col + 1):
        end_cell = f"{col_to_letter(end_col - 1)}{end_row}"
        return f"'{sheet_title}'!{start_cell}:{end_cell}"
    return f"'{sheet_title}'!{start_cell}"

def _is_comment_assigned_to_user(comment: dict, user_identifier: str) -> bool:
    """Checks if a comment is assigned to or mentions a given user by email, user ID, or display name."""
    if not user_identifier or user_identifier.lower() in ("all", "any", "*"):
        return True

    clean_target = user_identifier.lower().strip().lstrip("@").lstrip("+")
    user_prefix = clean_target.split("@")[0] if "@" in clean_target else clean_target

    targets = [clean_target]
    if len(user_prefix) >= 3:
        targets.append(user_prefix)

    def check_match(val):
        if not val:
            return False
        if isinstance(val, str):
            val_lower = val.lower()
            return any(t in val_lower for t in targets)
        if isinstance(val, dict):
            for v in val.values():
                if check_match(v):
                    return True
        if isinstance(val, list):
            for item in val:
                if check_match(item):
                    return True
        return False

    # Check comment fields
    if check_match(comment.get("assignee")):
        return True
    if check_match(comment.get("content")):
        return True
    if check_match(comment.get("headPost")):
        return True
    if check_match(comment.get("replies")):
        return True

    return False

def _get_document_metadata(document_id: str, headers: dict[str, str]) -> dict:
    """Retrieves document title and MIME type from Google Drive API."""
    try:
        url = f"https://www.googleapis.com/drive/v3/files/{document_id}"
        resp = requests.get(url, headers=headers, params={"fields": "id,name,mimeType"})
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"id": document_id, "name": "Document", "mimeType": "unknown"}

def list_pending_comments(document_id: str, user_identifier: str, tool_context: ToolContext) -> dict:
    """Lists pending (unresolved) comments in a specific Google Doc or Google Sheet assigned to a target user.

    Args:
        document_id: The exact ID of the Google Docs or Google Sheets document.
        user_identifier: The user's email address or user ID to filter assigned comments.
        tool_context: The ToolContext containing authentication state.

    Returns:
        A dictionary containing document_id, document_title, document_type ('Google Sheet' or 'Google Doc'),
        and the list of pending comments (including cell_location for sheets).
    """
    token = _get_access_token_from_context(tool_context)
    headers = {"Authorization": f"Bearer {token}"}

    meta = _get_document_metadata(document_id, headers)
    doc_name = meta.get("name", "Document")
    mime_type = meta.get("mimeType", "")
    is_spreadsheet = "spreadsheet" in mime_type

    pending_comments = []

    # 1. If spreadsheet (or suspected spreadsheet), fetch comments using Google Sheets API v4
    if is_spreadsheet or mime_type == "unknown":
        sheets_url = f"https://sheets.googleapis.com/v4/spreadsheets/{document_id}"
        sheets_params = {
            "commentsViewMode": "COMMENTS_VIEW_MODE_INCLUDED",
            "fields": "spreadsheetId,properties/title,comments,sheets(properties(sheetId,title),commentAnchors)",
        }
        sheets_response = requests.get(sheets_url, headers=headers, params=sheets_params)

        if sheets_response.status_code == 200:
            sheets_data = sheets_response.json()
            title = sheets_data.get("properties", {}).get("title") or doc_name

            # Build anchor mapping from anchorId -> A1 notation
            anchor_map = {}
            for sheet in sheets_data.get("sheets", []):
                sheet_title = sheet.get("properties", {}).get("title", "Sheet1")
                for anchor in sheet.get("commentAnchors", []):
                    anchor_id = anchor.get("anchorId")
                    grid_range = anchor.get("range", {})
                    start_row = grid_range.get("startRowIndex", 0)
                    start_col = grid_range.get("startColumnIndex", 0)
                    end_row = grid_range.get("endRowIndex", start_row + 1)
                    end_col = grid_range.get("endColumnIndex", start_col + 1)
                    anchor_map[anchor_id] = _grid_range_to_a1(sheet_title, start_row, start_col, end_row, end_col)

            for comment in sheets_data.get("comments", []):
                status = comment.get("status", "")
                if status == "RESOLVED" or comment.get("resolved") is True:
                    continue

                if _is_comment_assigned_to_user(comment, user_identifier):
                    head_post = comment.get("headPost", {})
                    anchor_id = comment.get("anchorId")
                    cell_loc = anchor_map.get(anchor_id, "")

                    pending_comments.append({
                        "comment_id": comment.get("commentId") or comment.get("id"),
                        "cell_location": cell_loc,
                        "content": head_post.get("content") or comment.get("content", ""),
                        "author": head_post.get("author", {}).get("displayName") or comment.get("author", {}).get("displayName", "Unknown"),
                        "author_email": head_post.get("author", {}).get("user") or comment.get("author", {}).get("emailAddress", ""),
                        "created_time": head_post.get("createTime") or comment.get("createdTime", ""),
                        "anchor_id": anchor_id,
                        "replies_count": len(comment.get("replies", [])),
                    })

            return {
                "document_id": document_id,
                "document_title": title,
                "document_type": "Google Sheet",
                "pending_comments_count": len(pending_comments),
                "comments": pending_comments
            }

    # 2. For Google Docs, fetch comments using Google Drive API v3
    drive_url = f"https://www.googleapis.com/drive/v3/files/{document_id}/comments"
    drive_params = {
        "fields": "comments(id,content,author,quotedFileContent,anchor,replies,resolved,createdTime,assignee)",
        "includeDeleted": "false",
        "pageSize": 100,
    }
    drive_response = requests.get(drive_url, headers=headers, params=drive_params)
    drive_response.raise_for_status()
    drive_data = drive_response.json()

    for comment in drive_data.get("comments", []):
        if comment.get("resolved") is True or comment.get("status") == "RESOLVED":
            continue

        if _is_comment_assigned_to_user(comment, user_identifier):
            pending_comments.append({
                "comment_id": comment.get("id"),
                "content": comment.get("content", ""),
                "author": comment.get("author", {}).get("displayName", "Unknown"),
                "author_email": comment.get("author", {}).get("emailAddress", ""),
                "quoted_content": comment.get("quotedFileContent", {}).get("value", ""),
                "anchor": comment.get("anchor", ""),
                "created_time": comment.get("createdTime", ""),
                "replies_count": len(comment.get("replies", [])),
            })

    return {
        "document_id": document_id,
        "document_title": doc_name,
        "document_type": "Google Doc",
        "pending_comments_count": len(pending_comments),
        "comments": pending_comments
    }

def get_comment_details(document_id: str, comment_id: str, tool_context: ToolContext) -> dict:
    """Retrieves full details of a specific comment in a Google Docs or Sheets document.

    Args:
        document_id: The ID of the Google Docs or Sheets document.
        comment_id: The ID of the comment.
        tool_context: The ToolContext containing authentication state.

    Returns:
        A dictionary with full comment details including content, quoted content, author, cell location, and replies.
    """
    token = _get_access_token_from_context(tool_context)
    headers = {"Authorization": f"Bearer {token}"}

    # Try Sheets API first to get cell location if spreadsheet
    sheets_url = f"https://sheets.googleapis.com/v4/spreadsheets/{document_id}"
    sheets_params = {
        "commentsViewMode": "COMMENTS_VIEW_MODE_INCLUDED",
        "fields": "spreadsheetId,properties/title,comments,sheets(properties(sheetId,title),commentAnchors)",
    }
    sheets_response = requests.get(sheets_url, headers=headers, params=sheets_params)
    if sheets_response.status_code == 200:
        sheets_data = sheets_response.json()
        anchor_map = {}
        for sheet in sheets_data.get("sheets", []):
            sheet_title = sheet.get("properties", {}).get("title", "Sheet1")
            for anchor in sheet.get("commentAnchors", []):
                anchor_id = anchor.get("anchorId")
                grid_range = anchor.get("range", {})
                start_row = grid_range.get("startRowIndex", 0)
                start_col = grid_range.get("startColumnIndex", 0)
                end_row = grid_range.get("endRowIndex", start_row + 1)
                end_col = grid_range.get("endColumnIndex", start_col + 1)
                anchor_map[anchor_id] = _grid_range_to_a1(sheet_title, start_row, start_col, end_row, end_col)

        for comment in sheets_data.get("comments", []):
            if comment.get("commentId") == comment_id or comment.get("id") == comment_id:
                anchor_id = comment.get("anchorId")
                comment["cell_location"] = anchor_map.get(anchor_id, "")
                comment["document_type"] = "Google Sheet"
                return comment

    # Fallback to Drive API v3
    url = f"https://www.googleapis.com/drive/v3/files/{document_id}/comments/{comment_id}"
    params = {"fields": "id,content,author,quotedFileContent,anchor,replies,resolved,createdTime,assignee"}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    data["document_type"] = "Google Doc"
    return data

def reply_to_comment(
    document_id: str,
    comment_id: str,
    reply_text: str,
    tool_context: ToolContext,
    resolve: bool = True
) -> dict:
    """Replies to a comment in a Google Docs or Google Sheets document with an agent signature and optionally resolves it.

    Args:
        document_id: The ID of the Google Docs or Sheets document.
        comment_id: The ID of the comment thread.
        reply_text: The message to post in the reply explaining the changes made.
        tool_context: The ToolContext containing authentication state.
        resolve: Whether to resolve the comment thread after replying (default: True).

    Returns:
        A dictionary with the reply status, reply ID, and posted content.
    """
    token = _get_access_token_from_context(tool_context)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    signed_reply = f"{reply_text}\n\n---\n{AGENT_SIGNATURE}"

    # Try Sheets API batchUpdate with addCommentReply first
    batch_url = f"https://sheets.googleapis.com/v4/spreadsheets/{document_id}:batchUpdate"
    post_payload = {"content": signed_reply}
    if resolve:
        post_payload["commentAction"] = "RESOLVE"

    batch_body = {
        "requests": [
            {
                "addCommentReply": {
                    "commentId": comment_id,
                    "post": post_payload
                }
            }
        ]
    }
    sheets_res = requests.post(batch_url, headers=headers, json=batch_body)

    if sheets_res.status_code == 200:
        return {
            "status": "success",
            "document_id": document_id,
            "comment_id": comment_id,
            "document_type": "spreadsheet",
            "reply_content": signed_reply,
            "resolved": resolve
        }

    # Fallback to Drive API v3 reply (for Google Docs)
    drive_url = f"https://www.googleapis.com/drive/v3/files/{document_id}/comments/{comment_id}/replies"
    drive_body = {"content": signed_reply}
    if resolve:
        drive_body["action"] = "resolve"

    drive_res = requests.post(drive_url, headers=headers, json=drive_body, params={"fields": "*"})
    drive_res.raise_for_status()
    reply_data = drive_res.json()

    return {
        "status": "success",
        "document_id": document_id,
        "comment_id": comment_id,
        "document_type": "document",
        "reply_id": reply_data.get("id"),
        "reply_content": signed_reply,
        "resolved": resolve
    }

# Google Workspace MCP Toolsets for Google Docs & Google Sheets
docs_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://docsmcp.googleapis.com/mcp/v1",
        timeout=WORKSPACE_MCP_TIMEOUT,
        sse_read_timeout=WORKSPACE_MCP_TIMEOUT,
    ),
    header_provider=auth_header_provider,
)

sheets_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://sheetsmcp.googleapis.com/mcp/v1",
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
        You are an enterprise AI assistant specialized in processing and executing pending comments in Google Docs and Google Sheets documents that are assigned to a specific user.

        CORE DIRECTIVE: ACTION-ORIENTED DOCUMENT UPDATING
        Comments left on cells or document sections are explicit change requests or instructions. You MUST execute the requested modifications directly in the document. NEVER merely acknowledge or converse about a comment without applying the required document update.

        WORKFLOW & OPERATIONAL RULES:

        1. Target Document Isolation & Comment Retrieval:
           - You must ONLY process the exact `document_id` provided by the user. Never switch files.
           - Start by calling `list_pending_comments(document_id=..., user_identifier=...)`.
           - If `pending_comments_count == 0`, respond: "No pending comments assigned to <user_identifier> were found in document <document_id>."

        2. Proactive Document Mutation (Google Sheets):
           - When `document_type` is "Google Sheet", each comment is anchored to a specific `cell_location` (e.g. 'Sheet1'!B2).
           - Column Inspection & Exact Casing / Validation Matching:
             * Before updating any cell, retrieve existing values in that column (e.g. call `get_values` on that column such as 'Sheet1'!B1:B20) to inspect existing entries, data validation dropdown options, and casing conventions.
             * STRICT CASING CONSISTENCY: Always match the EXACT string, capitalization, and casing already present in that column (for example, if existing rows use "In progress", use "In progress", NOT "In Progress"; if they use "DONE", use "DONE"; if they use "in-progress", use "in-progress").
           - Interpret the comment intent and APPLY the update:
             * Status Updates (e.g. comment says "This is now in progress!", "Mark as complete", "Approved", "Done"): Match the exact valid status string from the column inspection (e.g. "In progress") and write it to `cell_location` using `update_values`.
             * Value / Data Changes (e.g. "Update to 150", "Cost is $500"): Write the new value using `update_values`.
             * Formula Requests: Write the formula using `update_values` or `update_formulas`.
             * Spreadsheet / Sheet Renames: Apply via `update_spreadsheet`.
           - You MUST execute the mutation tool call (e.g. `update_values`) BEFORE replying to the comment.

        3. Proactive Document Mutation (Google Docs):
           - When `document_type` is "Google Doc", read the document content and quoted text.
           - Apply the requested edits, text replacements, or content insertions using the Google Docs MCP tools before replying.

        4. Verify and Resolve:
           - Only after the document modification tool call succeeds, call `reply_to_comment(document_id=..., comment_id=..., reply_text=..., resolve=True)` using the exact `comment_id`.
           - State specifically in `reply_text` what change was made (e.g. "Updated 'Sheet1'!B2 to 'In progress'"). The tool will append the agent signature automatically.

        5. Final Output:
           - Present a concise, factual summary listing:
             * Document Title and ID
             * Each comment processed with its ID and location
             * The exact change/value applied to the cell or document
             * Resolution confirmation.
    """,
    tools=[
        docs_mcp,
        sheets_mcp,
        FunctionTool(list_pending_comments),
        FunctionTool(get_comment_details),
        FunctionTool(reply_to_comment),
    ]
)

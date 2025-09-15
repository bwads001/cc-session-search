#!/usr/bin/env python3
"""
Claude Code Session Search MCP Server

Provides tools for analyzing Claude Code conversation sessions across all projects.
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Any

# MCP imports
import mcp.types as types
from mcp.server.lowlevel import Server
import mcp.server.stdio

# Local imports
from core.searcher import SessionSearcher
from core.summarizer import ConversationSummarizer

# Initialize server
app = Server("cc-session-search")

# Initialize components
searcher = SessionSearcher()
summarizer = ConversationSummarizer()

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="list_projects",
            description="List all Claude Code projects with session counts and activity",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="list_sessions",
            description="List sessions for a specific project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Encoded project directory name from .claude/projects/ (uses dashes instead of slashes)"},
                    "days_back": {"type": "integer", "description": "How many days back to search (max 7)", "default": 7}
                },
                "required": ["project_name"]
            }
        ),
        types.Tool(
            name="list_recent_sessions",
            description="List recent sessions across all projects by date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {"type": "integer", "description": "How many days back to search (max 7)", "default": 1},
                    "project_filter": {"type": "string", "description": "Optional filter to specific project name"}
                },
                "required": []
            }
        ),
        types.Tool(
            name="analyze_sessions",
            description="Extract and analyze messages from sessions with filtering",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {"type": "integer", "description": "Days back to analyze (max 7)", "default": 1},
                    "role_filter": {"type": "string", "description": "Filter messages by role (user, assistant, both, tool)", "default": "both"},
                    "project_filter": {"type": "string", "description": "Optional filter to specific project"},
                    "include_tools": {"type": "boolean", "description": "Include tool usage messages", "default": False}
                },
                "required": []
            }
        ),
        types.Tool(
            name="search_conversations",
            description="Search conversations for specific terms with context windows, role filtering, and time ranges",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term or phrase"},
                    "context_window": {"type": "integer", "description": "Number of messages before/after match to include (max 5)", "default": 1},
                    "days_back": {"type": "integer", "description": "Days back to search (max 7)", "default": 2},
                    "project_filter": {"type": "string", "description": "Optional filter to specific project"},
                    "case_sensitive": {"type": "boolean", "description": "Case sensitive search", "default": False},
                    "role_filter": {"type": "string", "description": "Filter messages by role (user, assistant, both, tool)", "default": "both"},
                    "start_time": {"type": "string", "description": "Start time in ISO format (e.g., '2025-09-13T08:00:00'). If specified, will search from this time forward"},
                    "end_time": {"type": "string", "description": "End time in ISO format (e.g., '2025-09-13T12:00:00'). If specified, will search up to this time"}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="get_message_details",
            description="Get full content for specific messages by session ID and message indices",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID to get messages from"},
                    "message_indices": {"type": "array", "items": {"type": "integer"}, "description": "List of message indices to retrieve (max 10)"}
                },
                "required": ["session_id", "message_indices"]
            }
        ),
        types.Tool(
            name="summarize_daily_conversations",
            description="Generate intelligent summary of conversations for a specific date using headless Claude analysis",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Target date in YYYY-MM-DD format"},
                    "style": {"type": "string", "description": "Summary style: 'journal' (daily recap), 'insights' (learning focus), 'stories' (narrative focus)", "default": "journal"},
                    "project_filter": {"type": "string", "description": "Optional filter to specific project"}
                },
                "required": ["date"]
            }
        ),
        types.Tool(
            name="summarize_time_range",
            description="Generate intelligent summary of conversations for a specific time range using headless Claude analysis",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_time": {"type": "string", "description": "Start time in ISO format (e.g., '2025-09-13T12:00:00')"},
                    "end_time": {"type": "string", "description": "End time in ISO format (e.g., '2025-09-13T16:00:00')"},
                    "style": {"type": "string", "description": "Summary style: 'journal' (daily recap), 'insights' (learning focus), 'stories' (narrative focus)", "default": "journal"},
                    "project_filter": {"type": "string", "description": "Optional filter to specific project"}
                },
                "required": ["start_time", "end_time"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
    """Handle tool calls."""
    if name == "list_projects":
        projects = searcher.discover_projects()
        result = json.dumps(projects, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "list_sessions":
        project_name = arguments["project_name"]
        days_back = min(arguments.get("days_back", 7), 7)
        sessions = searcher.get_sessions_for_project(project_name, days_back)
        result = json.dumps(sessions, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "list_recent_sessions":
        days_back = min(arguments.get("days_back", 1), 7)
        project_filter = arguments.get("project_filter")
        sessions = searcher.get_recent_sessions(days_back, project_filter)
        result = json.dumps(sessions, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "analyze_sessions":
        days_back = min(arguments.get("days_back", 1), 7)
        role_filter = arguments.get("role_filter", "both")
        if role_filter not in ["user", "assistant", "both", "tool"]:
            role_filter = "both"
        project_filter = arguments.get("project_filter")
        include_tools = arguments.get("include_tools", False)

        result_data = searcher.analyze_sessions(
            days_back=days_back,
            role_filter=role_filter,
            project_filter=project_filter,
            include_tools=include_tools
        )
        result = json.dumps(result_data, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "search_conversations":
        query = arguments["query"]
        context_window = min(arguments.get("context_window", 1), 5)
        days_back = min(arguments.get("days_back", 7), 7)
        project_filter = arguments.get("project_filter")
        case_sensitive = arguments.get("case_sensitive", False)
        role_filter = arguments.get("role_filter", "both")
        start_time = arguments.get("start_time")
        end_time = arguments.get("end_time")

        # Validate role_filter
        if role_filter not in ["user", "assistant", "both", "tool"]:
            role_filter = "both"

        result_data = searcher.search_conversations(
            query=query,
            context_window=context_window,
            days_back=days_back,
            project_filter=project_filter,
            case_sensitive=case_sensitive,
            role_filter=role_filter,
            start_time=start_time,
            end_time=end_time
        )
        result = json.dumps(result_data, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "get_message_details":
        session_id = arguments["session_id"]
        message_indices = arguments.get("message_indices", [])[:10]  # Limit to 10

        result_data = searcher.get_message_details(session_id, message_indices)
        result = json.dumps(result_data, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "summarize_daily_conversations":
        date = arguments["date"]
        style = arguments.get("style", "journal")
        project_filter = arguments.get("project_filter")

        result_data = summarizer.summarize_daily_conversations(date, style, project_filter)
        result = json.dumps(result_data, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "summarize_time_range":
        start_time = arguments["start_time"]
        end_time = arguments["end_time"]
        style = arguments.get("style", "journal")
        project_filter = arguments.get("project_filter")

        result_data = summarizer.summarize_time_range(start_time, end_time, style, project_filter)
        result = json.dumps(result_data, indent=2)
        return [types.TextContent(type="text", text=result)]

    else:
        raise ValueError(f"Unknown tool: {name}")

async def run():
    """Run the server using stdio transport."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(run())
#!/usr/bin/env python3
"""
Claude Code Session Search MCP Server

Provides tools for analyzing Claude Code conversation sessions across all projects.
"""

import sys
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import re

# Add conversation analyzer to path
# Adjust this path to your local installation
CONV_ANALYZER_PATH = Path.home() / 'Projects' / 'claude-conversation-analyzer' / 'src'
sys.path.append(str(CONV_ANALYZER_PATH))

try:
    from parser import JSONLParser
except ImportError:
    print("Error: Could not import conversation parser", file=sys.stderr)
    print(f"Make sure {CONV_ANALYZER_PATH} exists", file=sys.stderr)
    print("Install from: https://github.com/yourusername/claude-conversation-analyzer", file=sys.stderr)
    sys.exit(1)

# MCP imports
import mcp.types as types
from mcp.server.lowlevel import Server
import mcp.server.stdio

# Initialize server
app = Server("cc-session-search")

class SessionSearcher:
    """Core session search and analysis functionality"""
    
    def __init__(self):
        self.parser = JSONLParser()
        self.claude_dir = Path.home() / '.claude' / 'projects'
    
    def discover_projects(self) -> List[Dict[str, Any]]:
        """Discover all Claude Code projects"""
        projects = []
        
        if not self.claude_dir.exists():
            return projects
        
        for project_dir in self.claude_dir.iterdir():
            if not project_dir.is_dir():
                continue
                
            # Count sessions
            session_files = list(project_dir.glob('*.jsonl'))
            if not session_files:
                continue
            
            # Get project info
            latest_session = max(session_files, key=lambda f: f.stat().st_mtime)
            latest_time = datetime.fromtimestamp(latest_session.stat().st_mtime)
            
            projects.append({
                'name': project_dir.name,
                'path': str(project_dir),
                'session_count': len(session_files),
                'latest_activity': latest_time.isoformat(),
                'decoded_name': self._decode_project_name(project_dir.name)
            })
        
        return sorted(projects, key=lambda p: p['latest_activity'], reverse=True)
    
    def _decode_project_name(self, encoded_name: str) -> str:
        """Decode Claude project directory names"""
        # Simply decode the path - no special cases needed
        return encoded_name.replace('-', '/')
    
    def get_sessions_for_project(self, project_name: str, days_back: int = 7) -> List[Dict[str, Any]]:
        """Get sessions for a specific project"""
        project_dir = self.claude_dir / project_name
        if not project_dir.exists():
            return []
        
        cutoff_time = datetime.now() - timedelta(days=days_back)
        sessions = []
        
        for session_file in project_dir.glob('*.jsonl'):
            mod_time = datetime.fromtimestamp(session_file.stat().st_mtime)
            if mod_time < cutoff_time:
                continue
                
            try:
                # Quick parse for metadata
                conversation_metadata, messages = self.parser.parse_conversation_file(session_file)
                
                sessions.append({
                    'session_id': conversation_metadata.session_id,
                    'file_path': str(session_file),
                    'message_count': len(messages),
                    'started_at': conversation_metadata.started_at.isoformat() if conversation_metadata.started_at else None,
                    'ended_at': conversation_metadata.ended_at.isoformat() if conversation_metadata.ended_at else None,
                    'working_directory': conversation_metadata.working_directory,
                    'git_branch': conversation_metadata.git_branch
                })
            except Exception:
                # Skip corrupted files
                continue
        
        return sorted(sessions, key=lambda s: s['started_at'] or '1970-01-01', reverse=True)
    
    def get_recent_sessions(self, days_back: int = 7, project_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent sessions across all or specific projects"""
        all_sessions = []
        
        projects_to_search = [self.claude_dir / project_filter] if project_filter else self.claude_dir.iterdir()
        
        for project_dir in projects_to_search:
            if not project_dir.is_dir():
                continue
                
            project_sessions = self.get_sessions_for_project(project_dir.name, days_back)
            for session in project_sessions:
                session['project_name'] = project_dir.name
                session['project_decoded'] = self._decode_project_name(project_dir.name)
                all_sessions.append(session)
        
        return sorted(all_sessions, key=lambda s: s['started_at'] or '1970-01-01', reverse=True)
    
    def analyze_sessions(self, 
                        session_ids: List[str] = None,
                        project_filter: Optional[str] = None,
                        days_back: int = 1,
                        role_filter: str = "both",
                        include_tools: bool = False) -> Dict[str, Any]:
        """Analyze sessions with filtering options"""
        
        # Get sessions to analyze
        if session_ids:
            sessions_to_analyze = []
            for project_dir in self.claude_dir.iterdir():
                if project_filter and project_dir.name != project_filter:
                    continue
                for session_id in session_ids:
                    session_file = project_dir / f"{session_id}.jsonl"
                    if session_file.exists():
                        sessions_to_analyze.append(session_file)
        else:
            # Get recent sessions
            recent_sessions = self.get_recent_sessions(days_back, project_filter)
            sessions_to_analyze = [Path(s['file_path']) for s in recent_sessions]
        
        # Parse and filter messages
        all_messages = []
        session_count = 0
        
        for session_file in sessions_to_analyze:
            try:
                conversation_metadata, messages = self.parser.parse_conversation_file(session_file)
                session_count += 1
                
                # Filter by role
                filtered_messages = []
                for msg in messages:
                    if role_filter == "user" and msg.role != "user":
                        continue
                    elif role_filter == "assistant" and msg.role != "assistant":
                        continue
                    elif role_filter == "tool" and msg.role != "tool":
                        continue
                    elif not include_tools and msg.role == "tool":
                        continue
                    
                    # Store message metadata without content to keep responses small
                    filtered_messages.append({
                        'session_id': conversation_metadata.session_id,
                        'project': self._decode_project_name(session_file.parent.name),
                        'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                        'role': msg.role,
                        'content_preview': msg.content[:100] + "..." if len(msg.content) > 100 else msg.content,
                        'content_length': len(msg.content),
                        'has_tool_uses': bool(msg.tool_uses),
                        'message_index': len(filtered_messages)  # For referencing later
                    })
                
                all_messages.extend(filtered_messages)
                
            except Exception:
                continue
        
        return {
            'sessions_analyzed': session_count,
            'total_messages': len(all_messages),
            'messages_returned': min(len(all_messages), 100),
            'messages': all_messages[:100],  # Return metadata only, not full content
            'truncated': len(all_messages) > 100,
            'summary': {
                'messages_by_role': {
                    'user': len([m for m in all_messages if m['role'] == 'user']),
                    'assistant': len([m for m in all_messages if m['role'] == 'assistant']),
                    'tool': len([m for m in all_messages if m['role'] == 'tool'])
                },
                'avg_content_length': sum(m['content_length'] for m in all_messages) / len(all_messages) if all_messages else 0,
                'sessions_with_messages': list(set(m['session_id'][:8] + "..." for m in all_messages))[:10]  # Show first 10 sessions
            },
            'filter_applied': {
                'role_filter': role_filter,
                'days_back': days_back,
                'project_filter': project_filter,
                'include_tools': include_tools
            }
        }

    def get_message_details(self, session_id: str, message_indices: List[int]) -> Dict[str, Any]:
        """Get full content for specific messages by session and index"""
        session_file = None
        for project_dir in self.claude_dir.iterdir():
            session_file_path = project_dir / f"{session_id}.jsonl"
            if session_file_path.exists():
                session_file = session_file_path
                break

        if not session_file:
            return {'error': f'Session {session_id} not found'}

        try:
            conversation_metadata, messages = self.parser.parse_conversation_file(session_file)

            requested_messages = []
            for idx in message_indices:
                if 0 <= idx < len(messages):
                    msg = messages[idx]
                    requested_messages.append({
                        'index': idx,
                        'role': msg.role,
                        'content': msg.content,
                        'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                        'has_tool_uses': bool(msg.tool_uses)
                    })

            return {
                'session_id': session_id,
                'total_messages_in_session': len(messages),
                'requested_messages': requested_messages
            }
        except Exception as e:
            return {'error': f'Failed to load session: {str(e)}'}

    def search_conversations(self, 
                           query: str,
                           context_window: int = 2,
                           days_back: int = 7,
                           project_filter: Optional[str] = None,
                           case_sensitive: bool = False) -> Dict[str, Any]:
        """Search conversations with context windows"""
        
        recent_sessions = self.get_recent_sessions(days_back, project_filter)
        results = []
        
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(query), flags)
        
        for session_info in recent_sessions:
            try:
                session_file = Path(session_info['file_path'])
                conversation_metadata, messages = self.parser.parse_conversation_file(session_file)
                
                # Search through messages
                for i, msg in enumerate(messages):
                    if pattern.search(msg.content):
                        # Get context window
                        start_idx = max(0, i - context_window)
                        end_idx = min(len(messages), i + context_window + 1)
                        
                        context_messages = []
                        for j in range(start_idx, end_idx):
                            context_msg = messages[j]
                            context_messages.append({
                                'role': context_msg.role,
                                'content': context_msg.content[:500],  # Truncate long messages
                                'timestamp': context_msg.timestamp.isoformat() if context_msg.timestamp else None,
                                'is_match': (j == i)
                            })
                        
                        # Truncate match content and context messages
                        match_content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content

                        # Truncate context messages too
                        truncated_context = []
                        for ctx_msg in context_messages:
                            ctx_content = ctx_msg['content'][:200] + "..." if len(ctx_msg['content']) > 200 else ctx_msg['content']
                            truncated_context.append({
                                **ctx_msg,
                                'content': ctx_content,
                                'content_length': len(ctx_msg['content'])
                            })

                        results.append({
                            'session_id': conversation_metadata.session_id,
                            'project': self._decode_project_name(session_file.parent.name),
                            'match_timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                            'match_content': match_content,
                            'match_content_length': len(msg.content),
                            'context_window': truncated_context
                        })
                        
            except Exception:
                continue
        
        return {
            'query': query,
            'total_matches': len(results),
            'context_window_size': context_window,
            'results': results[:20]  # Limit results to keep response manageable
        }

# Initialize searcher
searcher = SessionSearcher()

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
            description="Search conversations for specific terms with context windows. Returns truncated content for manageable responses.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term or phrase"},
                    "context_window": {"type": "integer", "description": "Number of messages before/after match to include (max 5)", "default": 1},
                    "days_back": {"type": "integer", "description": "Days back to search (max 7)", "default": 2},
                    "project_filter": {"type": "string", "description": "Optional filter to specific project"},
                    "case_sensitive": {"type": "boolean", "description": "Case sensitive search", "default": False}
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
        
        result_data = searcher.search_conversations(
            query=query,
            context_window=context_window,
            days_back=days_back,
            project_filter=project_filter,
            case_sensitive=case_sensitive
        )
        result = json.dumps(result_data, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "get_message_details":
        session_id = arguments["session_id"]
        message_indices = arguments.get("message_indices", [])[:10]  # Limit to 10

        result_data = searcher.get_message_details(session_id, message_indices)
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
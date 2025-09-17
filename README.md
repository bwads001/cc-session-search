# Claude Code Session Search MCP Server

An MCP (Model Context Protocol) server that provides tools for searching and analyzing Claude Code conversation history.

## Features

- **List Projects**: View all Claude Code projects with session counts
- **List Sessions**: Browse sessions for specific projects
- **List Recent Sessions**: Find recent conversations across all projects
- **Analyze Sessions**: Extract and analyze messages with role filtering
- **Search Conversations**: Search for specific terms with context windows
- **Get Message Details**: Retrieve full content for specific messages

## Installation

1. Clone this repository:
```bash
git clone https://github.com/bwads001/cc-session-search.git
cd cc-session-search
```

2. Install dependencies:
```bash
uv pip install -e .
```

3. Add to Claude Code MCP config (`~/.config/claude/mcp.json`):
```json
{
  "servers": {
    "cc-session-search": {
      "command": ["uv", "run", "cc-session-search"],
      "cwd": "${HOME}/cc-session-search"
    }
  }
}
```
Note: Adjust the `cwd` path to match where you cloned the repository.

## Usage

The server provides the following tools:

### list_projects()
Lists all Claude Code projects with session counts and recent activity.

### list_sessions(project_name, days_back=7)
Lists sessions for a specific project within the specified time range.

### list_recent_sessions(days_back=1, project_filter=None)
Lists recent sessions across all projects.

### analyze_sessions(days_back=1, role_filter="both", include_tools=False, project_filter=None)
Extracts and analyzes messages from sessions with filtering options.

### search_conversations(query, days_back=2, context_window=1, case_sensitive=False, project_filter=None)
Searches conversations for specific terms with context windows.

### get_message_details(session_id, message_indices)
Retrieves full content for specific messages by session ID and indices.

## Development

The server is built using the official MCP Python SDK with low-level Server class for maximum control.

Key features:
- Efficient response handling with content truncation
- Metadata-first approach to minimize token usage
- Support for date ranges and filtering
- Cross-project search capabilities

## License

MIT

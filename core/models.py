"""
Data models for conversation search
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


@dataclass
class Message:
    """Represents a single message in a conversation"""
    role: str
    content: str
    timestamp: Optional[datetime] = None
    uuid: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def from_jsonl_line(cls, line: str) -> Optional['Message']:
        """Parse a message from a JSONL line"""
        try:
            data = json.loads(line.strip())

            # Extract message content based on structure
            message_data = data.get('message', {})

            role = message_data.get('role', 'unknown')
            content = ""

            # Handle different content structures
            if isinstance(message_data.get('content'), str):
                content = message_data['content']
            elif isinstance(message_data.get('content'), list):
                # Claude format with content blocks
                text_blocks = [block.get('text', '') for block in message_data['content']
                             if block.get('type') == 'text']
                content = ' '.join(text_blocks)

            # Parse timestamp
            timestamp = None
            if 'timestamp' in data:
                try:
                    timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass

            # Extract UUID
            uuid = data.get('uuid')

            # Extract tool calls
            tool_calls = None
            if isinstance(message_data.get('content'), list):
                tool_calls = [block for block in message_data['content']
                            if block.get('type') == 'tool_use']

            return cls(
                role=role,
                content=content,
                timestamp=timestamp,
                uuid=uuid,
                tool_calls=tool_calls
            )

        except (json.JSONDecodeError, KeyError):
            return None


@dataclass
class SearchResult:
    """Represents a search result with context"""
    session_id: str
    project: str
    match_timestamp: str
    match_content: str
    match_content_length: int
    context_window: List[Dict[str, Any]]


@dataclass
class ConversationSummary:
    """Represents a summarized view of daily conversations"""
    date: str
    total_sessions: int
    total_messages: int
    summary_style: str
    summary_text: str
    key_topics: List[str]
    insights: List[str]
    stories: List[str]
    projects_mentioned: List[str]
    people_mentioned: List[str]
    error: Optional[str] = None
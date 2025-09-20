"""
JSONL Parser for Claude Code conversation files.

Handles parsing of conversation files with metadata extraction,
message processing, and tool use analysis.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class ParsedMessage:
    """Represents a parsed message from a conversation."""
    uuid: str
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: Optional[datetime]
    tool_uses: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]


@dataclass
class ConversationMetadata:
    """Metadata extracted from a conversation file."""
    project_name: str
    project_path: str
    session_id: str
    git_branch: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    working_directory: Optional[str]
    message_count: int
    file_path: str


class JSONLParser:
    """Parser for Claude Code JSONL conversation files."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_conversation_file(self, file_path: Path) -> Tuple[ConversationMetadata, List[ParsedMessage]]:
        """
        Parse a single JSONL conversation file.

        Args:
            file_path: Path to the JSONL file

        Returns:
            Tuple of (conversation_metadata, parsed_messages)
        """
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"Conversation file not found: {file_path}")

        messages = []
        raw_messages = []

        # Read all lines from JSONL file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        raw_message = json.loads(line)
                        raw_messages.append(raw_message)
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Invalid JSON on line {line_num} in {file_path}: {e}")
                        continue
        except Exception as e:
            self.logger.error(f"Error reading file {file_path}: {e}")
            raise

        if not raw_messages:
            raise ValueError(f"No valid messages found in {file_path}")

        # Extract conversation metadata
        metadata = self._extract_conversation_metadata(file_path, raw_messages)

        # Parse individual messages
        for raw_msg in raw_messages:
            try:
                parsed_msg = self._parse_message(raw_msg, metadata)
                if parsed_msg:
                    messages.append(parsed_msg)
            except Exception as e:
                self.logger.warning(f"Error parsing message in {file_path}: {e}")
                continue

        # Fix missing timestamps
        messages = self._fix_missing_timestamps(messages, file_path)

        # Update metadata with final counts and timestamps
        if messages:
            metadata.message_count = len(messages)
            timestamps = [msg.timestamp for msg in messages if msg.timestamp]
            if timestamps:
                metadata.started_at = min(timestamps)
                metadata.ended_at = max(timestamps)

        return metadata, messages

    def _extract_conversation_metadata(self, file_path: Path, raw_messages: List[Dict]) -> ConversationMetadata:
        """Extract metadata from conversation file and messages."""
        # Project information from file path
        # Expected format: ~/.claude/projects/{encoded-project-name}/conversation-{uuid}.jsonl
        project_path = str(file_path.parent)
        project_name = file_path.parent.name
        session_id = file_path.stem

        # Extract other metadata from first available message
        git_branch = None
        working_directory = None

        for msg in raw_messages:
            if 'gitBranch' in msg and msg['gitBranch']:
                git_branch = msg['gitBranch']
            if 'cwd' in msg and msg['cwd']:
                working_directory = msg['cwd']

            # Break after finding branch info (usually consistent throughout conversation)
            if git_branch:
                break

        return ConversationMetadata(
            project_name=project_name,
            project_path=project_path,
            session_id=session_id,
            git_branch=git_branch,
            started_at=None,  # Will be filled after parsing messages
            ended_at=None,    # Will be filled after parsing messages
            working_directory=working_directory,
            message_count=0,  # Will be filled after parsing messages
            file_path=str(file_path)
        )

    def _parse_message(self, raw_msg: Dict, metadata: ConversationMetadata) -> Optional[ParsedMessage]:
        """Parse a single message from the JSONL format."""
        try:
            # Extract basic fields
            msg_type = raw_msg.get('type', 'unknown')

            # Handle UUID differently for summary vs regular messages
            if msg_type == 'summary':
                msg_uuid = raw_msg.get('leafUuid', str(uuid4()))
            else:
                msg_uuid = raw_msg.get('uuid', str(uuid4()))

            # Parse timestamp
            timestamp = None
            if 'timestamp' in raw_msg and raw_msg['timestamp']:
                try:
                    # Handle ISO format timestamp
                    timestamp = datetime.fromisoformat(raw_msg['timestamp'].replace('Z', '+00:00'))
                except (ValueError, TypeError) as e:
                    self.logger.debug(f"Could not parse timestamp '{raw_msg.get('timestamp')}': {e}")
            elif msg_type == 'summary' and metadata.started_at:
                # Summary messages don't have timestamps, use conversation start time
                timestamp = metadata.started_at

            # Handle different message formats
            if msg_type == 'summary':
                # Summary messages have a different structure
                role = 'summary'
                message_data = {'content': raw_msg.get('summary', '')}
            else:
                # Regular messages have a 'message' field
                message_data = raw_msg.get('message', {})
                role = message_data.get('role', msg_type)

            # Detect and reclassify tool results as tool messages
            # Tool results have role='user' but contain tool_result content blocks or toolUseResult data
            is_tool_response = False

            # Check for tool_result content blocks
            if role == 'user' and isinstance(message_data.get('content'), list):
                content_blocks = message_data.get('content', [])
                if any(block.get('type') == 'tool_result' for block in content_blocks if isinstance(block, dict)):
                    is_tool_response = True

            # Also check for toolUseResult data (alternative tool response format)
            if role == 'user' and 'toolUseResult' in raw_msg:
                is_tool_response = True

            # Reclassify as tool message
            if is_tool_response:
                role = 'tool'

            # Handle content - can be string or array of content blocks
            content = self._extract_content(message_data.get('content', ''))

            # Extract tool uses if present
            tool_uses = None
            if 'toolUseResult' in raw_msg:
                tool_uses = raw_msg['toolUseResult']

            # Collect additional metadata
            msg_metadata = {
                'original_type': msg_type,
                'cwd': raw_msg.get('cwd'),
                'git_branch': raw_msg.get('gitBranch')
            }

            return ParsedMessage(
                uuid=msg_uuid,
                role=role,
                content=content,
                timestamp=timestamp,
                tool_uses=tool_uses,
                metadata=msg_metadata
            )

        except Exception as e:
            self.logger.error(f"Error parsing message: {e}")
            return None

    def _extract_content(self, content: Union[str, List, Dict]) -> str:
        """
        Extract text content from various content formats.

        Content can be:
        - String: direct text
        - List: array of content blocks
        - Dict: single content block
        """
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Multiple content blocks - concatenate text parts
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'text' and 'text' in block:
                        text_parts.append(block['text'])
                    elif 'content' in block:
                        # Nested content
                        text_parts.append(self._extract_content(block['content']))
                elif isinstance(block, str):
                    text_parts.append(block)
            return '\n'.join(text_parts)
        elif isinstance(content, dict):
            # Single content block
            if content.get('type') == 'text' and 'text' in content:
                return content['text']
            elif 'content' in content:
                return self._extract_content(content['content'])
            else:
                return str(content)
        else:
            return str(content) if content else ''

    def _fix_missing_timestamps(self, messages: List[ParsedMessage], file_path: Path) -> List[ParsedMessage]:
        """
        Fix missing timestamps using next message timestamp or file modification time.

        Common issue: First message often lacks timestamp.
        """
        if not messages:
            return messages

        # Get file modification time as fallback
        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

        for i, msg in enumerate(messages):
            if msg.timestamp is None:
                # Try to use next message's timestamp
                fallback_time = None
                for j in range(i + 1, len(messages)):
                    if messages[j].timestamp:
                        fallback_time = messages[j].timestamp
                        break

                # If no later timestamp found, use file modification time
                if fallback_time is None:
                    fallback_time = file_mtime

                # Create new message with estimated timestamp
                messages[i] = ParsedMessage(
                    uuid=msg.uuid,
                    role=msg.role,
                    content=msg.content,
                    timestamp=fallback_time,
                    tool_uses=msg.tool_uses,
                    metadata=msg.metadata
                )

        return messages

    def extract_technical_events(self, messages: List[ParsedMessage]) -> List[Dict[str, Any]]:
        """
        Extract technical events from parsed messages.

        Returns list of technical events for later insertion into database.
        """
        events = []

        for msg in messages:
            if not msg.tool_uses:
                continue

            # Extract file operations
            if 'tool_name' in msg.tool_uses:
                tool_name = msg.tool_uses['tool_name']

                # Map tool names to event types
                event_type = self._map_tool_to_event_type(tool_name)
                if event_type:
                    event = {
                        'message_uuid': msg.uuid,
                        'event_type': event_type,
                        'timestamp': msg.timestamp,
                        'details': msg.tool_uses,
                        'file_path': msg.tool_uses.get('file_path')
                    }
                    events.append(event)

        return events

    def _map_tool_to_event_type(self, tool_name: str) -> Optional[str]:
        """Map tool names to standardized event types."""
        tool_mapping = {
            'Write': 'file_created',
            'Edit': 'file_modified',
            'MultiEdit': 'file_modified',
            'Read': 'file_accessed',
            'Bash': 'command_executed',
            'Grep': 'code_searched',
            'LS': 'directory_listed'
        }
        return tool_mapping.get(tool_name)


def parse_conversation_files(directory: Path) -> Tuple[List[ConversationMetadata], List[ParsedMessage]]:
    """
    Parse all JSONL conversation files in a directory.

    Args:
        directory: Directory containing conversation files

    Returns:
        Tuple of (all_conversations_metadata, all_messages)
    """
    parser = JSONLParser()
    all_conversations = []
    all_messages = []

    # Find all JSONL files
    jsonl_files = list(directory.rglob("*.jsonl"))
    logger.info(f"Found {len(jsonl_files)} JSONL files in {directory}")

    for file_path in jsonl_files:
        try:
            conversation_metadata, messages = parser.parse_conversation_file(file_path)
            all_conversations.append(conversation_metadata)
            # Tag each message with its conversation session_id for proper grouping later
            for message in messages:
                message.metadata['conversation_session_id'] = conversation_metadata.session_id
            all_messages.extend(messages)
            logger.debug(f"Parsed {len(messages)} messages from {file_path}")
        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            continue

    logger.info(f"Successfully parsed {len(all_conversations)} conversations with {len(all_messages)} total messages")
    return all_conversations, all_messages


def parse_conversation_files_grouped(directory: Path) -> List[Tuple[ConversationMetadata, List[ParsedMessage]]]:
    """
    Parse all JSONL conversation files in a directory, maintaining conversation-message grouping.

    Args:
        directory: Directory containing conversation files

    Returns:
        List of (conversation_metadata, messages) tuples
    """
    parser = JSONLParser()
    grouped_conversations = []

    # Find all JSONL files
    jsonl_files = list(directory.rglob("*.jsonl"))
    logger.info(f"Found {len(jsonl_files)} JSONL files in {directory}")

    for file_path in jsonl_files:
        try:
            conversation_metadata, messages = parser.parse_conversation_file(file_path)
            grouped_conversations.append((conversation_metadata, messages))
            logger.debug(f"Parsed {len(messages)} messages from {file_path}")
        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            continue

    logger.info(f"Successfully parsed {len(grouped_conversations)} conversations")
    return grouped_conversations


if __name__ == "__main__":
    # Quick test
    import sys

    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) > 1:
        test_path = Path(sys.argv[1])
        if test_path.is_file():
            parser = JSONLParser()
            metadata, messages = parser.parse_conversation_file(test_path)
            print(f"Project: {metadata.project_name}")
            print(f"Messages: {len(messages)}")
            print(f"Started: {metadata.started_at}")
            print(f"Ended: {metadata.ended_at}")
        else:
            conversations, messages = parse_conversation_files(test_path)
            print(f"Conversations: {len(conversations)}")
            print(f"Messages: {len(messages)}")
    else:
        print("Usage: python conversation_parser.py <file_or_directory>")
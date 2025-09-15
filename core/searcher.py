"""
Core conversation search functionality
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from core.models import Message


class SessionSearcher:
    """Core session search and analysis functionality"""

    def __init__(self):
        # Import parser here to avoid circular imports
        import sys
        CONV_ANALYZER_PATH = Path.home() / 'Projects' / 'claude-conversation-analyzer' / 'src'
        sys.path.append(str(CONV_ANALYZER_PATH))

        try:
            from parser import JSONLParser
            self.parser = JSONLParser()
        except ImportError:
            raise ImportError("Could not import conversation parser")

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
                           case_sensitive: bool = False,
                           role_filter: str = "both",
                           start_time: Optional[str] = None,
                           end_time: Optional[str] = None) -> Dict[str, Any]:
        """Search conversations with context windows, role filtering, and time ranges"""

        # Parse time range if provided
        start_datetime = None
        end_datetime = None
        if start_time:
            try:
                # Handle both naive and timezone-aware input
                if start_time.endswith('Z'):
                    start_datetime = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                elif '+' in start_time:
                    start_datetime = datetime.fromisoformat(start_time)
                else:
                    # Naive datetime - assume local time and convert to UTC
                    naive_dt = datetime.fromisoformat(start_time)
                    # Get local timezone offset (assuming MST/PDT which is UTC-7)
                    local_tz = datetime.now().astimezone().tzinfo
                    local_dt = naive_dt.replace(tzinfo=local_tz)
                    start_datetime = local_dt.astimezone(timezone.utc)
            except ValueError:
                return {'error': f'Invalid start_time format: {start_time}. Use ISO format like 2025-09-13T08:00:00'}

        if end_time:
            try:
                # Handle both naive and timezone-aware input
                if end_time.endswith('Z'):
                    end_datetime = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                elif '+' in end_time:
                    end_datetime = datetime.fromisoformat(end_time)
                else:
                    # Naive datetime - assume local time and convert to UTC
                    naive_dt = datetime.fromisoformat(end_time)
                    # Get local timezone offset (assuming MST/PDT which is UTC-7)
                    local_tz = datetime.now().astimezone().tzinfo
                    local_dt = naive_dt.replace(tzinfo=local_tz)
                    end_datetime = local_dt.astimezone(timezone.utc)
            except ValueError:
                return {'error': f'Invalid end_time format: {end_time}. Use ISO format like 2025-09-13T12:00:00'}

        # Get sessions to search (expand search if time range specified)
        search_days = days_back
        if start_datetime:
            # Calculate how many days back we need to search
            # Use a safe comparison - assume start_datetime is in local time if naive
            now = datetime.now()
            if start_datetime.tzinfo is None:
                # Naive datetime - compare directly
                days_diff = (now - start_datetime).days + 1
            else:
                # Timezone-aware - convert now to UTC for comparison
                now_utc = now.replace(tzinfo=timezone.utc)
                days_diff = (now_utc - start_datetime).days + 1
            search_days = max(search_days, abs(days_diff) + 1)  # abs() in case start_time is in future

        recent_sessions = self.get_recent_sessions(search_days, project_filter)
        results = []

        # Validate role_filter
        if role_filter not in ["user", "assistant", "both", "tool"]:
            role_filter = "both"

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(query), flags)

        for session_info in recent_sessions:
            try:
                session_file = Path(session_info['file_path'])
                conversation_metadata, messages = self.parser.parse_conversation_file(session_file)

                # Search through messages
                for i, msg in enumerate(messages):
                    # Filter by role
                    if role_filter == "user" and msg.role != "user":
                        continue
                    elif role_filter == "assistant" and msg.role != "assistant":
                        continue
                    elif role_filter == "tool" and msg.role != "tool":
                        continue

                    # Filter by time range
                    if msg.timestamp:
                        msg_time = msg.timestamp

                        # Timezone-aware comparison (both should be in UTC now)
                        if start_datetime:
                            # Convert message time to UTC if needed
                            if msg_time.tzinfo is None:
                                # Message time is naive, assume UTC
                                msg_time_utc = msg_time.replace(tzinfo=timezone.utc)
                            else:
                                # Convert to UTC
                                msg_time_utc = msg_time.astimezone(timezone.utc)

                            if msg_time_utc < start_datetime:
                                continue

                        if end_datetime:
                            # Convert message time to UTC if needed
                            if msg_time.tzinfo is None:
                                # Message time is naive, assume UTC
                                msg_time_utc = msg_time.replace(tzinfo=timezone.utc)
                            else:
                                # Convert to UTC
                                msg_time_utc = msg_time.astimezone(timezone.utc)

                            if msg_time_utc > end_datetime:
                                continue
                    elif start_datetime or end_datetime:
                        # Skip messages without timestamps if time filtering is requested
                        continue

                    # Search for query in message content
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
                                'is_match': (j == i),
                                'content_length': len(context_msg.content)
                            })

                        results.append({
                            'session_id': conversation_metadata.session_id,
                            'project': self._decode_project_name(session_file.parent.name),
                            'match_timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                            'match_content': msg.content,
                            'match_content_length': len(msg.content),
                            'context_window': context_messages
                        })

            except Exception:
                continue

        return {
            'query': query,
            'total_matches': len(results),
            'context_window_size': context_window,
            'results': results[:20]  # Limit results to keep response manageable
        }
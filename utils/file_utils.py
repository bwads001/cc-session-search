"""
File parsing and utility functions
"""
import os
import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from core.models import Message


def get_projects() -> List[Dict[str, any]]:
    """Get all Claude Code projects with session counts and activity"""
    claude_dir = Path.home() / '.claude' / 'projects'

    if not claude_dir.exists():
        return []

    projects = []
    for project_dir in claude_dir.iterdir():
        if project_dir.is_dir():
            # Count session files
            session_count = len([f for f in project_dir.glob('*.jsonl')])

            # Get latest activity
            latest_activity = None
            try:
                latest_file = max(project_dir.glob('*.jsonl'), key=os.path.getmtime, default=None)
                if latest_file:
                    latest_activity = datetime.fromtimestamp(latest_file.stat().st_mtime).isoformat()
            except (OSError, ValueError):
                pass

            # Decode project name
            decoded_name = project_dir.name.replace('-', '/')
            if decoded_name.startswith('/'):
                decoded_name = decoded_name[1:]  # Remove leading slash if present

            projects.append({
                'name': project_dir.name,
                'path': str(project_dir),
                'session_count': session_count,
                'latest_activity': latest_activity,
                'decoded_name': decoded_name
            })

    return sorted(projects, key=lambda x: x['latest_activity'] or '', reverse=True)


def get_sessions_from_projects(projects: List[Dict], days_back: int = 7,
                             project_filter: Optional[str] = None) -> List[Dict]:
    """Get recent sessions from projects"""
    cutoff_time = datetime.now() - timedelta(days=days_back)
    sessions = []

    for project in projects:
        if project_filter and project_filter not in project['decoded_name']:
            continue

        project_path = Path(project['path'])
        for session_file in project_path.glob('*.jsonl'):
            try:
                mod_time = datetime.fromtimestamp(session_file.stat().st_mtime)
                if mod_time > cutoff_time:
                    sessions.append({
                        'session_id': session_file.stem,
                        'project': project['decoded_name'],
                        'path': str(session_file),
                        'modified_time': mod_time.isoformat()
                    })
            except (OSError, ValueError):
                continue

    return sorted(sessions, key=lambda x: x['modified_time'], reverse=True)


def parse_session_messages(session_path: str) -> List[Message]:
    """Parse messages from a session file"""
    messages = []

    try:
        with open(session_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if line:
                    message = Message.from_jsonl_line(line)
                    if message:
                        messages.append(message)
    except (IOError, UnicodeDecodeError):
        pass

    return messages


def get_message_content_preview(content: str, max_chars: int = 100) -> str:
    """Get a preview of message content"""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."


def safe_json_loads(text: str) -> Optional[Dict]:
    """Safely load JSON, returning None on failure"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
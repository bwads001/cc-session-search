"""
Conversation summarization using headless Claude
"""
import json
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional

from core.models import ConversationSummary
from core.searcher import SessionSearcher


class ConversationSummarizer:
    """Handles intelligent summarization of daily conversations"""

    def __init__(self):
        self.searcher = SessionSearcher()

    def summarize_daily_conversations(self, date: str, style: str = "journal",
                                    project_filter: Optional[str] = None) -> Dict[str, Any]:
        """Main entry point for daily conversation summarization"""

        # Use the searcher to find conversations for the date
        # Search for any content (broad query) within the specific date range
        search_result = self.searcher.search_conversations(
            query="the",  # Common word to catch most conversations
            start_time=f"{date}T00:00:00",
            end_time=f"{date}T23:59:59",
            project_filter=project_filter,
            role_filter="user",  # Focus on user messages for summary
            days_back=30,  # Look back far enough to catch the specific date
            context_window=1
        )

        if search_result.get('total_matches', 0) == 0:
            return {
                'date': date,
                'total_sessions': 0,
                'total_messages': 0,
                'summary_style': style,
                'summary': 'No conversations found for this date.',
                'key_topics': [],
                'insights': [],
                'stories': [],
                'projects_mentioned': [],
                'people_mentioned': []
            }

        # Prepare content for Claude analysis
        conversation_content = self._prepare_summary_content(search_result, date)

        # Generate summary using headless Claude
        summary_result = self._call_headless_claude_summary(conversation_content, style, date)

        # Calculate session count
        unique_sessions = len(set(r['session_id'] for r in search_result['results']))

        return {
            'date': date,
            'total_sessions': unique_sessions,
            'total_messages': search_result['total_matches'],
            'summary_style': style,
            'summary': summary_result.get('summary', 'Summary generation failed'),
            'key_topics': summary_result.get('key_topics', []),
            'insights': summary_result.get('insights', []),
            'stories': summary_result.get('stories', []),
            'projects_mentioned': summary_result.get('projects_mentioned', []),
            'people_mentioned': summary_result.get('people_mentioned', []),
            'error': summary_result.get('error')
        }

    def _prepare_summary_content(self, search_result: Dict[str, Any], date: str) -> str:
        """Prepare conversation content for Claude analysis"""
        content_parts = []
        content_parts.append(f"# Daily Conversations Summary - {date}")
        content_parts.append(f"Total messages: {search_result['total_matches']}")
        content_parts.append("")

        for result in search_result['results']:
            content_parts.append(f"## Session: {result['session_id']} ({result['project']})")

            # Include the actual message content (not just context window)
            content_parts.append(f"**User Message:** {result['match_content'][:500]}...")
            content_parts.append("")

        # Limit total content to prevent timeout
        full_content = "\n".join(content_parts)
        if len(full_content) > 6000:
            full_content = full_content[:6000] + "\n\n[Content truncated to prevent timeout]"

        return full_content

    def _call_headless_claude_summary(self, conversation_content: str, style: str, date: str) -> Dict[str, Any]:
        """Call headless Claude to generate summary"""
        return self._call_headless_claude(conversation_content, style, date)

    def summarize_conversations(self, conversations_data: Dict[str, Any], style: str = "journal") -> ConversationSummary:
        """Generate intelligent summary using headless Claude"""

        if 'error' in conversations_data:
            return ConversationSummary(
                date=conversations_data.get('date', 'unknown'),
                total_sessions=0,
                total_messages=0,
                summary_style=style,
                summary_text="",
                key_topics=[],
                insights=[],
                stories=[],
                projects_mentioned=[],
                people_mentioned=[],
                error=conversations_data['error']
            )

        # Prepare conversation content for Claude
        conversation_content = self._prepare_conversation_content(conversations_data, style)

        # Generate summary using headless Claude
        summary_result = self._call_headless_claude(conversation_content, style, conversations_data['date'])

        if summary_result.get('error'):
            return ConversationSummary(
                date=conversations_data['date'],
                total_sessions=conversations_data['session_count'],
                total_messages=conversations_data['total_messages'],
                summary_style=style,
                summary_text="",
                key_topics=[],
                insights=[],
                stories=[],
                projects_mentioned=[],
                people_mentioned=[],
                error=summary_result['error']
            )

        # Parse Claude's response
        return self._parse_summary_response(
            summary_result['summary'],
            conversations_data,
            style
        )

    def _prepare_conversation_content(self, conversations_data: Dict[str, Any], style: str) -> str:
        """Prepare conversation content for Claude analysis"""

        content_parts = []
        content_parts.append(f"# Daily Conversations - {conversations_data['date']}")
        content_parts.append(f"Sessions: {conversations_data['session_count']}")
        content_parts.append(f"Total Messages: {conversations_data['total_messages']}")
        content_parts.append("")

        for conv in conversations_data['conversations']:
            content_parts.append(f"## Session: {conv['session_id']} ({conv['project']})")

            for msg in conv['messages']:
                timestamp = msg.timestamp.strftime('%H:%M') if msg.timestamp else 'unknown'
                content_parts.append(f"**{timestamp} - {msg.role}:** {msg.content[:500]}...")

            content_parts.append("")

        return "\n".join(content_parts)

    def _call_headless_claude(self, conversation_content: str, style: str, date: str) -> Dict[str, Any]:
        """Call headless Claude to generate summary"""

        # Style-specific prompts
        prompts = {
            "journal": f"""Analyze today's conversations ({date}) and create a concise daily recap suitable for a personal journal.

Focus on:
- Key accomplishments and activities discussed
- Important decisions or insights
- People mentioned and interactions
- Projects worked on or discussed
- Notable experiences or stories
- Learning moments or realizations

Format as a natural daily summary that captures the essence of the day's conversations.""",

            "insights": f"""Analyze today's conversations ({date}) and extract key insights and learning moments.

Focus on:
- Technical insights or breakthroughs
- Problem-solving approaches
- New understanding or realizations
- Patterns in thinking or work
- Lessons learned
- Knowledge gaps identified

Format as actionable insights for knowledge base enhancement.""",

            "stories": f"""Analyze today's conversations ({date}) and identify compelling stories or experiences worth capturing.

Focus on:
- Personal experiences and anecdotes
- Interesting problem-solving journeys
- Memorable interactions or conversations
- Creative or innovative moments
- Challenges overcome
- Serendipitous discoveries

Format as narrative summaries of the most story-worthy moments."""
        }

        prompt = prompts.get(style, prompts["journal"])

        # Create temporary file with conversation content
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_file:
                temp_file.write(conversation_content)
                temp_file_path = temp_file.name

            # Call headless Claude
            claude_prompt = f"""{prompt}

Please analyze the conversation content and provide a structured summary.

Return your response in this JSON format:
{{
    "summary": "Main summary text here",
    "key_topics": ["topic1", "topic2", "topic3"],
    "insights": ["insight1", "insight2"],
    "stories": ["story1", "story2"],
    "projects_mentioned": ["project1", "project2"],
    "people_mentioned": ["person1", "person2"]
}}

Conversation content to analyze:
{conversation_content[:5000]}...
"""

            result = subprocess.run([
                'claude', '--print', '--output-format', 'text',
                '--model', 'claude-3-5-sonnet-latest',
                claude_prompt
            ],
            capture_output=True,
            text=True
            )

            # Clean up temp file
            import os
            os.unlink(temp_file_path)

            if result.returncode == 0:
                return {'summary': result.stdout.strip()}
            else:
                return {'error': f'Claude headless failed: {result.stderr}'}

        except Exception as e:
            return {'error': f'Error calling headless Claude: {str(e)}'}

    def _parse_summary_response(self, claude_response: str, conversations_data: Dict[str, Any], style: str) -> ConversationSummary:
        """Parse Claude's response into structured summary"""

        # Try to extract JSON from response
        summary_data = self._extract_json_from_response(claude_response)

        if not summary_data:
            # Fallback: use raw response as summary
            return ConversationSummary(
                date=conversations_data['date'],
                total_sessions=conversations_data['session_count'],
                total_messages=conversations_data['total_messages'],
                summary_style=style,
                summary_text=claude_response,
                key_topics=[],
                insights=[],
                stories=[],
                projects_mentioned=[],
                people_mentioned=[]
            )

        return ConversationSummary(
            date=conversations_data['date'],
            total_sessions=conversations_data['session_count'],
            total_messages=conversations_data['total_messages'],
            summary_style=style,
            summary_text=summary_data.get('summary', ''),
            key_topics=summary_data.get('key_topics', []),
            insights=summary_data.get('insights', []),
            stories=summary_data.get('stories', []),
            projects_mentioned=summary_data.get('projects_mentioned', []),
            people_mentioned=summary_data.get('people_mentioned', [])
        )

    def _extract_json_from_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Extract JSON data from Claude's response"""
        try:
            # Look for JSON block in response
            if '```json' in response:
                start = response.find('```json') + 7
                end = response.find('```', start)
                json_str = response[start:end].strip()
            elif '{' in response and '}' in response:
                start = response.find('{')
                end = response.rfind('}') + 1
                json_str = response[start:end]
            else:
                return None

            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return None

    def summarize_time_range(self, start_time: str, end_time: str,
                           style: str = "journal", project_filter: Optional[str] = None) -> Dict[str, Any]:
        """Summarize conversations within a specific time range using search functionality"""

        # Use the searcher to find conversations in the time range
        search_result = self.searcher.search_conversations(
            query="the",  # Common word to catch most conversations
            start_time=start_time,
            end_time=end_time,
            project_filter=project_filter,
            role_filter="user",  # Focus on user messages for summary
            days_back=30,  # Look back far enough to catch the time range
            context_window=1
        )

        if search_result.get('total_matches', 0) == 0:
            return {
                'start_time': start_time,
                'end_time': end_time,
                'total_sessions': 0,
                'total_messages': 0,
                'summary_style': style,
                'summary': 'No conversations found for this time range.',
                'key_topics': [],
                'insights': [],
                'stories': [],
                'projects_mentioned': [],
                'people_mentioned': []
            }

        # Prepare content for Claude analysis
        conversation_content = self._prepare_time_range_content(search_result, start_time, end_time)

        # Generate summary using headless Claude
        summary_result = self._call_headless_claude_summary(conversation_content, style, f"{start_time} to {end_time}")

        # Calculate session count
        unique_sessions = len(set(r['session_id'] for r in search_result['results']))

        return {
            'start_time': start_time,
            'end_time': end_time,
            'total_sessions': unique_sessions,
            'total_messages': search_result['total_matches'],
            'summary_style': style,
            'summary': summary_result.get('summary', 'Summary generation failed'),
            'key_topics': summary_result.get('key_topics', []),
            'insights': summary_result.get('insights', []),
            'stories': summary_result.get('stories', []),
            'projects_mentioned': summary_result.get('projects_mentioned', []),
            'people_mentioned': summary_result.get('people_mentioned', []),
            'error': summary_result.get('error')
        }

    def _prepare_time_range_content(self, search_result: Dict[str, Any], start_time: str, end_time: str) -> str:
        """Prepare time range conversation content for Claude analysis"""
        content_parts = []
        content_parts.append(f"# Time Range Conversations Summary - {start_time} to {end_time}")
        content_parts.append(f"Total messages: {search_result['total_matches']}")
        content_parts.append("")

        for result in search_result['results']:
            content_parts.append(f"## Session: {result['session_id']} ({result['project']})")
            content_parts.append(f"**Time:** {result['match_timestamp']}")
            content_parts.append(f"**User Message:** {result['match_content'][:500]}...")
            content_parts.append("")

        # Limit total content to prevent timeout
        full_content = "\n".join(content_parts)
        if len(full_content) > 6000:
            full_content = full_content[:6000] + "\n\n[Content truncated to prevent timeout]"

        return full_content


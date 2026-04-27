"""Email sender agent - LLM-driven tool orchestrator with code safety nets.

Uses the OpenAI Agents SDK to demonstrate agentic tool calling: the LLM
decides which tools to call and in what order, while code handles
pre/post-processing and deduplication.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any

from agents import Agent, ModelSettings, Runner, set_default_openai_key, custom_span
from config.logging import setup_logging
from config import settings
from schema import EmailActionResult, MeetingDetails
from tools import (
    send_reply_email,
    get_staff_tool,
    notify_staff_about_meeting,
    generate_meeting_details,
)

setup_logging()
logger = logging.getLogger(__name__)

if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)

# ── Agent instructions ──────────────────────────────────────────────

_MEETING_INSTRUCTIONS = """\
You are an email-sending and meeting-coordination agent.

## AVAILABLE TOOLS (call each ONE AT A TIME, wait for the result)
1. get_staff_tool        → returns staff name, email, timezone, availability
2. generate_meeting_details → proposes a meeting time (returns subject, start_time, duration, etc.)
3. send_reply_email      → sends the email reply to the client
4. notify_staff_about_meeting → emails the staff member so THEY create the calendar invite

## YOUR WORKFLOW — execute these steps IN ORDER, one tool per step:

**Step 1 → get_staff_tool()**
Call with exclude_email set to the client's email (from the EMAIL section below). This avoids selecting a staff member with the same email as the client. Read the result to get staff email, timezone, and availability.

**Step 2 → generate_meeting_details()**
Pass the client's email context, the staff email, availability, and timezone from Step 1.

**Step 3 → send_reply_email()**
Send the reply to the client. IMPORTANT:
- Use the message from the RESPONSE section below as a base.
- REPLACE any mention of "sent a calendar invite" with "Our team will send you a calendar invitation shortly with the meeting details."
- APPEND the proposed meeting details from Step 2:
  "Proposed Meeting Details:\\n  Date: [date]\\n  Time: [time]\\n  Duration: [duration] minutes"
- Add: "If this time doesn't work for you, please reply with your preferred availability."
- Use the exact message_id and thread_id from the EMAIL section.

**Step 4 → notify_staff_about_meeting()**
Send the staff member an internal notification with the meeting details as a JSON string:
{{"subject": "...", "start_time": "...", "duration_minutes": N, "description": "...", "conversation_summary": "..."}}
Use the staff_email from Step 1 and the exact values from Step 2.

## CRITICAL RULES
- Call tools ONE AT A TIME. Wait for each result before proceeding.
- NEVER call any tool more than once.
- NEVER tell the client a calendar invite was already sent. The staff will do it manually.
- If a tool fails, log the error mentally and move to the next step.
- After Step 4, output a brief summary of what you did.
"""

_SIMPLE_INSTRUCTIONS = """\
You are an email-sending agent.

## YOUR TASK
Send the approved response to the client using send_reply_email.
- The `message` MUST be the exact text from the RESPONSE section below.
- Use the message_id and thread_id from the EMAIL section.
- Call send_reply_email exactly once, then output a brief summary.
"""


class EmailSenderAgent:
    """LLM-driven agent that orchestrates tools for email sending and meeting coordination."""

    async def execute_action(self, approved_response: str, email_data: Dict[str, Any]) -> EmailActionResult:
        sender_email = email_data.get('sender_email', '')
        sender_name = email_data.get('sender_name', 'Unknown')
        message_id = email_data.get('message_id')
        thread_id = email_data.get('thread_id')
        subject = email_data.get('subject', '')
        intent_data = email_data.get('intent', {})
        intent = intent_data.get('intent', 'unknown')
        email_content = email_data.get('content', '')
        conversation_history = email_data.get('conversation_history', '')

        logger.info(f"EmailSenderAgent - sender: {sender_name} ({sender_email}), "
                     f"message_id: {message_id}, thread_id: {thread_id}, intent: {intent}")

        response_text = _rewrite_calendar_claims(approved_response)

        is_meeting = intent == "meeting_request"
        instructions = _MEETING_INSTRUCTIONS if is_meeting else _SIMPLE_INSTRUCTIONS
        tools = [send_reply_email, get_staff_tool, generate_meeting_details, notify_staff_about_meeting] if is_meeting else [send_reply_email]

        context = f"""RESPONSE: {response_text}

EMAIL: From {sender_email} ({sender_name}) | Subject: {subject} | MSG_ID: {message_id} | Thread: {thread_id}
INTENT: {intent} (confidence: {intent_data.get('confidence', 0.0)})

CONTENT: {email_content}
HISTORY: {conversation_history or 'None'}

ACTIONS:
1. Send reply using message_id="{message_id}" and thread_id="{thread_id}"
2. Meeting: {'YES - follow the 4-step meeting workflow' if is_meeting else 'NO - just send the reply'}
"""

        try:
            from utils.model_fallback import run_agent_with_fallback

            with custom_span("EmailSenderAgent", data={
                "intent": intent,
                "to": sender_email,
                "tools": [t.name for t in tools],
            }):
                result, provider = await run_agent_with_fallback(
                    name="EmailSenderAgent",
                    instructions=instructions,
                    prompt=context,
                    tools=tools,
                    temperature=0.3,
                    max_tokens=1024,
                )

            sent_email = False
            message_id_out = None
            thread_id_out = thread_id
            staff_notified = False

            if hasattr(result, 'new_items'):
                tool_calls = {}
                for item in result.new_items:
                    item_type = type(item).__name__
                    if item_type == "ToolCallItem":
                        cid = getattr(item.raw_item, "call_id", None) or getattr(item.raw_item, "id", None)
                        tool_name = getattr(item.raw_item, "name", None)
                        if not tool_name and hasattr(item.raw_item, "function"):
                            tool_name = item.raw_item.function.name
                        if cid and tool_name:
                            tool_calls[cid] = {"name": tool_name, "output": None}

                    elif item_type == "ToolCallOutputItem":
                        cid = getattr(item.raw_item, "call_id", None)
                        if not cid and isinstance(item.raw_item, dict):
                            cid = item.raw_item.get("call_id") or item.raw_item.get("tool_call_id")
                        if cid in tool_calls:
                            tool_calls[cid]["output"] = item.output

                for call_id, details in tool_calls.items():
                    parsed = _parse_tool_output(details["output"])
                    if details["name"] == "send_reply_email":
                        if parsed.get("success"):
                            sent_email = True
                            message_id_out = parsed.get("message_id")
                            thread_id_out = parsed.get("thread_id", thread_id)
                    elif details["name"] == "notify_staff_about_meeting":
                        if parsed.get("ok") or parsed.get("success"):
                            staff_notified = True

                tool_names = [d["name"] for d in tool_calls.values()]
                logger.info(f"Agent executed tools via {provider}: {tool_names}")
                if is_meeting:
                    logger.info(f"Email sent: {sent_email}, Staff notified: {staff_notified}")

            return EmailActionResult(
                action_taken="sent" if sent_email else "partial",
                success=sent_email,
                message_id=message_id_out,
                thread_id=thread_id_out,
                error=None if sent_email else f"Agent output: {str(result.final_output)[:200]}",
            )

        except Exception as e:
            logger.error(f"Error executing email action: {e}", exc_info=True)
            return EmailActionResult(action_taken="error", success=False, error=str(e))


# ── Helpers ──────────────────────────────────────────────────────────


def _rewrite_calendar_claims(text: str) -> str:
    """Replace false 'calendar invite sent' claims before the agent sees the text."""
    replacements = [
        ("I have sent over a calendar invite", "Our team will send you a calendar invitation shortly with the meeting details"),
        ("I've sent over a calendar invite", "Our team will send you a calendar invitation shortly with the meeting details"),
        ("I have sent a calendar invite", "Our team will send you a calendar invitation shortly with the meeting details"),
        ("calendar invite has been sent", "our team will send you a calendar invitation shortly"),
        ("I've also sent a calendar invitation", "Our team will also send a calendar invitation"),
        ("I have scheduled a meeting", "Our team will schedule a meeting"),
    ]
    for old, new in replacements:
        if old.lower() in text.lower():
            text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)

    redundant = [
        r"If the proposed time doesn't work,\s*feel free to propose a new time via the calendar link\.\s*",
        r"This will ensure we schedule a call that suits you best\.\s*",
    ]
    for pattern in redundant:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    return text


def _parse_tool_output(output) -> dict:
    """Normalize tool output into a dict."""
    if output is None:
        return {}
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            return json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return {"raw": output}
    d = {}
    for attr in ("success", "ok", "message_id", "thread_id", "error"):
        if hasattr(output, attr):
            d[attr] = getattr(output, attr)
    return d

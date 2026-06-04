"""Email reply tool using the configured email provider."""

from typing import Dict, Any, Optional
import logging
from agentmail import AgentMail

from config.logging import setup_logging
from config import settings
from agents import function_tool
from services.mailbox_transport import send_mailbox_reply
from services.resend_email import send_resend_reply

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def campaign_auto_approves_monitor_replies(campaign_id: Optional[int]) -> bool:
    """Return True when this campaign skips approval for webhook replies."""
    if not campaign_id:
        return False
    try:
        from utils.db_connection import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT auto_approve_monitor_replies FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            return bool(row and row["auto_approve_monitor_replies"])
    except Exception as e:
        logger.warning(f"Could not resolve monitor approval setting for campaign {campaign_id}: {e}")
        return False


def campaign_organization_id(campaign_id: Optional[int]) -> int | None:
    if not campaign_id:
        return None
    try:
        from utils.db_connection import get_conn

        with get_conn() as conn:
            row = conn.execute("SELECT organization_id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            return int(row["organization_id"]) if row and row["organization_id"] is not None else None
    except Exception as e:
        logger.warning(f"Could not resolve organization for campaign {campaign_id}: {e}")
        return None


def save_reply_draft(
    to_email: str,
    message: str,
    thread_id: Optional[str] = None,
    subject: Optional[str] = None,
    campaign_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Save an inbound-monitor reply as a local draft awaiting approval."""
    from utils.db_connection import get_conn
    import datetime

    conn = get_conn()
    try:
        with conn:
            organization_id = campaign_organization_id(campaign_id)
            if organization_id:
                cur = conn.execute(
                    "SELECT id, organization_id FROM leads WHERE email = ? AND organization_id = ?",
                    (to_email, organization_id),
                )
            else:
                cur = conn.execute("SELECT id, organization_id FROM leads WHERE email = ?", (to_email,))
            row = cur.fetchone()
            lead_id = row['id'] if row else None
            resolved_campaign_id = campaign_id
            if lead_id and not resolved_campaign_id:
                campaign_row = conn.execute(
                    "SELECT campaign_id FROM campaign_leads WHERE lead_id = ? ORDER BY campaign_id DESC LIMIT 1",
                    (lead_id,),
                ).fetchone()
                resolved_campaign_id = campaign_row["campaign_id"] if campaign_row else None
                organization_id = campaign_organization_id(resolved_campaign_id)
            if lead_id and organization_id is None:
                lead_row = conn.execute("SELECT organization_id FROM leads WHERE id = ?", (lead_id,)).fetchone()
                organization_id = lead_row["organization_id"] if lead_row else None

            now_iso = datetime.datetime.utcnow().isoformat() + 'Z'
            cur = conn.execute(
                "INSERT INTO email_messages "
                "(organization_id, lead_id, campaign_id, direction, subject, body, status, processed, approved, created_at) "
                "VALUES (?, ?, ?, 'outbound', ?, ?, 'DRAFT', 1, 0, ?)",
                (organization_id or 1, lead_id, resolved_campaign_id, subject or "Re: Your Message", message, now_iso)
            )
            draft_id = cur.lastrowid
        logger.info(f"Saved reply draft to {to_email} due to email monitor human approval")
        return {
            'success': True,
            'message_id': f"draft:{draft_id}" if draft_id else "draft",
            'thread_id': thread_id or "draft",
            'draft_id': draft_id,
            'method': 'draft',
        }
    except Exception as e:
        logger.error(f"Failed to save draft: {e}")
        return {'success': False, 'error': f"Failed to save draft: {e}"}


@function_tool
def send_reply_email(
    to_email: str,
    message: str,
    message_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    subject: Optional[str] = None,
    campaign_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Send email reply via AgentMail using proper reply API.
    
    Args:
        to_email: Recipient email address
        message: Email message content
        message_id: Original message ID to reply to (preferred for proper threading)
        thread_id: Thread ID for context (fallback option)
        subject: Email subject line (optional, auto-generated for replies)
        campaign_id: Campaign context for draft visibility when human approval is required
        
    Returns:
        Dict with send result
    """
    try:
        # Failsafe for smaller models that might pass literal "\n" instead of actual newlines
        if message and isinstance(message, str):
            message = message.replace('\\n', '\n')
            
        if (
            settings.effective_email_monitor_human_approval
            and not campaign_auto_approves_monitor_replies(campaign_id)
        ):
            return save_reply_draft(to_email, message, thread_id=thread_id, subject=subject, campaign_id=campaign_id)

        if settings.email_provider == "mailbox":
            organization_id = campaign_organization_id(campaign_id)
            logger.info(f"Sending reply to {to_email} via connected mailbox")
            return send_mailbox_reply(
                to_email=to_email,
                message=message,
                message_id=message_id,
                subject=subject,
                organization_id=organization_id,
            )

        if settings.email_provider == "resend":
            logger.info(f"Sending reply to {to_email} via Resend")
            return send_resend_reply(
                to_email=to_email,
                message=message,
                message_id=message_id,
                subject=subject,
            )

        client = AgentMail(api_key=settings.agentmail_api_key)
        
        # If we have message_id, use the proper reply API (preferred)
        if message_id:
            logger.info(f"Sending reply to message {message_id}")
            
            # Try formatting the message_id properly as required by AgentMail API
            try:
                response = client.inboxes.messages.reply(
                    inbox_id=settings.agentmail_inbox_id,
                    message_id=message_id,  # Use original message_id since SDK might handle formatting
                    text=message
                )
                
                return {
                    'success': True,
                    'message_id': str(response.id) if hasattr(response, 'id') else str(getattr(response, 'message_id', 'unknown')),
                    'thread_id': str(response.thread_id) if hasattr(response, 'thread_id') else 'unknown',
                    'method': 'reply'
                }
            except Exception as e:
                if "404" in str(e) or "not found" in str(e).lower() or "400" in str(e):
                    logger.warning(f"Failed to reply with message_id {message_id}, falling back to new message: {e}")
                    # Let it fall through to the new message fallback below
                else:
                    logger.error(f"Error during reply: {e}")
                    raise e
        
        # Fallback: send new message (less ideal for threading)
        logger.warning(f"No message_id provided, sending new message to {to_email}")
        send_kwargs = {
            'to': to_email,
            'text': message,
        }
        
        # Handle subject for new messages
        if subject:
            send_kwargs['subject'] = subject
        elif thread_id:
            # Try to get thread info for better subject
            try:
                thread = client.threads.get(thread_id=thread_id)
                if thread.messages:
                    latest_msg = max(thread.messages, key=lambda x: getattr(x, 'created_at', 0))
                    original_subject = latest_msg.subject or "Your Message"
                    if not original_subject.lower().startswith('re:'):
                        subject = f"Re: {original_subject}"
                    else:
                        subject = original_subject
                    send_kwargs['subject'] = subject
            except Exception as e:
                logger.warning(f"Could not fetch thread for subject: {e}")
                send_kwargs['subject'] = "Re: Your Message"
        else:
            send_kwargs['subject'] = "Re: Your Message"
        
        response = client.inboxes.messages.send(
            inbox_id=settings.agentmail_inbox_id, 
            to=to_email,
            subject=send_kwargs.get('subject', 'Re: Your Message'),
            text=message
        )
        
        return {
            'success': True,
            'message_id': str(response.id) if hasattr(response, 'id') else str(getattr(response, 'message_id', 'unknown')),
            'thread_id': str(response.thread_id) if hasattr(response, 'thread_id') else 'unknown',
            'method': 'new_message'
        }
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return {'success': False, 'error': str(e)}

"""Email reply tool using AgentMail."""

from typing import Dict, Any
import logging
from agentmail import AgentMail

from config.logging import setup_logging
from config import settings
from agents import function_tool

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@function_tool
def send_reply_email(to_email: str, message: str, message_id: str = None, thread_id: str = None, subject: str = None) -> Dict[str, Any]:
    """Send email reply via AgentMail using proper reply API.
    
    Args:
        to_email: Recipient email address
        message: Email message content
        message_id: Original message ID to reply to (preferred for proper threading)
        thread_id: Thread ID for context (fallback option)
        subject: Email subject line (optional, auto-generated for replies)
        
    Returns:
        Dict with send result
    """
    try:
        # Failsafe for smaller models that might pass literal "\n" instead of actual newlines
        if message and isinstance(message, str):
            message = message.replace('\\n', '\n')
            
        if settings.require_human_approval:
            from utils.db_connection import get_conn
            import datetime
            conn = get_conn()
            try:
                with conn:
                    # Find lead_id
                    cur = conn.execute("SELECT id FROM leads WHERE email = ?", (to_email,))
                    row = cur.fetchone()
                    lead_id = row['id'] if row else None
                    
                    # Save as draft
                    now_iso = datetime.datetime.utcnow().isoformat() + 'Z'
                    conn.execute(
                        "INSERT INTO email_messages (lead_id, direction, subject, body, status, processed, created_at) VALUES (?, 'outbound', ?, ?, 'draft', 1, ?)",
                        (lead_id, subject or "Re: Your Message", message, now_iso)
                    )
                logger.info(f"Saved reply draft to {to_email} due to require_human_approval=True")
                return {
                    'success': True,
                    'message_id': "draft",
                    'thread_id': "draft",
                    'method': 'draft'
                }
            except Exception as e:
                logger.error(f"Failed to save draft: {e}")
                return {'success': False, 'error': f"Failed to save draft: {e}"}

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
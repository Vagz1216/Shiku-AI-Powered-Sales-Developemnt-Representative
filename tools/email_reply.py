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
        client = AgentMail(api_key=settings.agentmail_api_key)
        
        # If we have message_id, use the proper reply API (preferred)
        if message_id:
            logger.info(f"Sending reply to message {message_id}")
            response = client.inboxes.messages.reply(
                inbox_id=settings.agentmail_inbox_id,
                message_id=message_id,
                text=message
            )
            
            return {
                'success': True,
                'message_id': str(response.message_id),
                'thread_id': str(response.thread_id),
                'method': 'reply'
            }
        
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
        
        response = client.inboxes.messages.send(settings.agentmail_inbox_id, **send_kwargs)
        
        return {
            'success': True,
            'message_id': str(response.message_id),
            'thread_id': str(response.thread_id),
            'method': 'new_message'
        }
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return {'success': False, 'error': str(e)}
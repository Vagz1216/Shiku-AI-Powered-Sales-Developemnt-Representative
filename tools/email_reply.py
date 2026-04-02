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
def send_reply_email(to_email: str, message: str, thread_id: str = None, subject: str = None) -> Dict[str, Any]:
    """Send email reply via AgentMail.
    
    Args:
        to_email: Recipient email address
        message: Email message content
        thread_id: Thread ID to reply to (optional, but recommended for replies)
        subject: Email subject line (optional, will auto-generate "Re: Original Subject" if not provided)
        
    Returns:
        Dict with send result
    """
    try:
        client = AgentMail(api_key=settings.agentmail_api_key)
        
        send_kwargs = {
            'to': to_email,
            'text': message,
        }
        
        # If thread_id provided but no subject, try to get original subject
        if thread_id and not subject:
            try:
                # Fetch thread to get original subject
                thread_response = client.inboxes.threads.list_messages(
                    inbox_id=settings.agentmail_inbox_id,
                    thread_id=thread_id,
                    limit=1,
                    order="desc"  # Get most recent message
                )
                
                if thread_response.messages:
                    original_subject = thread_response.messages[0].subject or "No Subject"
                    # Add "Re: " prefix if not already present
                    if not original_subject.lower().startswith('re:'):
                        subject = f"Re: {original_subject}"
                    else:
                        subject = original_subject
                else:
                    subject = "Re: Your Message"
            except Exception as e:
                logger.warning(f"Could not fetch original subject: {e}")
                subject = "Re: Your Message"
        
        # Use provided subject or fallback
        if subject:
            send_kwargs['subject'] = subject
        
        # Note: AgentMail API doesn't accept thread_id in send method
        # Threading is handled automatically by the service based on subject and recipients
        # if thread_id:
        #     send_kwargs['thread_id'] = thread_id
        
        response = client.inboxes.messages.send(settings.agentmail_inbox_id, **send_kwargs)
        
        return {
            'success': True,
            'message_id': str(response.message_id),
            'thread_id': str(response.thread_id)
        }
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return {'success': False, 'error': str(e)}
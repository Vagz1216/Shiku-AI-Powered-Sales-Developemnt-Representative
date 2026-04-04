"""Data extraction utilities for webhook payloads."""

import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def extract_sender_name(email_data: Dict[str, Any]) -> str:
    """Extract sender name from webhook payload, fallback to email if no name."""
    
    # Get email from from_ or from field (AgentMail uses both)
    email_string = email_data.get('from_') or email_data.get('from', '')
    
    # Handle list format (sometimes it's wrapped in a list)
    if isinstance(email_string, list) and email_string:
        email_string = email_string[0]
    
    if not isinstance(email_string, str):
        email_string = str(email_string)
    
    # Parse "Name <email>" format if present
    if '<' in email_string and '>' in email_string:
        name_match = re.search(r'^([^<]+)\s*<[^>]+@[^>]+>', email_string)
        if name_match:
            name = name_match.group(1).strip()
            # Clean up common email artifacts
            name = re.sub(r'["\'\\\/]', '', name)  # Remove quotes and slashes
            if name and name not in ['', 'unknown', 'null']:
                logger.debug(f"Extracted sender name: {name}")
                return name
    
    # Fallback to email part before @
    email = extract_sender_email(email_data)
    fallback_name = email.split('@')[0] if '@' in email else email
    logger.debug(f"Using fallback name from email: {fallback_name}")
    return fallback_name


def extract_sender_email(email_data: Dict[str, Any]) -> str:
    """Extract sender email from webhook payload - simplified for AgentMail format."""
    
    # Get email from from_ or from field (AgentMail uses both)
    email_string = email_data.get('from_') or email_data.get('from', '')
    
    # Handle list format (sometimes it's wrapped in a list)
    if isinstance(email_string, list) and email_string:
        email_string = email_string[0]
    
    if not isinstance(email_string, str):
        email_string = str(email_string)
    
    # Parse "Name <email>" format if present
    if '<' in email_string and '>' in email_string:
        email_match = re.search(r'<([^>]+@[^>]+)>', email_string)
        if email_match:
            email_string = email_match.group(1)
    
    # Validate result has @ symbol
    if '@' not in email_string:
        logger.error(f"Invalid email extracted '{email_string}' from payload")
        email_string = f"invalid_email_{hash(str(email_data.get('id', 'unknown')))}"
    
    logger.info(f"Extracted sender email: {email_string}")
    return email_string


def extract_message_id(email_data: Dict[str, Any]) -> Optional[str]:
    """Extract message ID from webhook payload - simplified for AgentMail format."""
    
    # Try the most common message ID fields (based on real webhook data)
    message_id = (
        email_data.get('message_id') or 
        email_data.get('id') or 
        email_data.get('messageId')
    )
    
    if message_id:
        logger.debug(f"Extracted message_id: {message_id}")
        return str(message_id)
    
    logger.debug(f"No message_id found in email_data")
    return None


def extract_email_content(email_data: Dict[str, Any]) -> str:
    """Extract email content with preference for clean extracted_text over raw text."""
    # Prefer extracted_text (clean, without quoted history) over text or preview
    return (
        email_data.get('extracted_text', '') or 
        email_data.get('text', '') or 
        email_data.get('preview', '') or 
        email_data.get('body', '')
    )


def extract_thread_id(email_data: Dict[str, Any]) -> Optional[str]:
    """Extract thread ID from email data."""
    return email_data.get('thread_id') or email_data.get('threadId') or email_data.get('conversation_id')


def extract_subject(email_data: Dict[str, Any]) -> str:
    """Extract subject from email data with fallback."""
    return email_data.get('subject', '') or email_data.get('title', '')


def get_email_metadata(email_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract all key metadata from email payload in one call."""
    return {
        'sender_email': extract_sender_email(email_data),
        'sender_name': extract_sender_name(email_data),
        'message_id': extract_message_id(email_data),
        'content': extract_email_content(email_data),
        'thread_id': extract_thread_id(email_data),
        'subject': extract_subject(email_data),
        'timestamp': email_data.get('created_at') or email_data.get('timestamp'),
        'labels': email_data.get('labels', [])
    }
"""Email security validation utilities."""

import re
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def validate_email_security(content: str, sender_email: str, subject: str) -> Tuple[bool, Optional[str]]:
    """Validate email for security issues before LLM processing.
    
    Args:
        content: Email content to validate
        sender_email: Sender's email address
        subject: Email subject line
        
    Returns:
        Tuple of (is_valid, rejection_reason)
    """
    # 1. Content length validation (prevent token exhaustion)
    if len(content) > 2000:
        return False, f"Email content too long ({len(content)} chars, max 2000)"
    
    # 2. Basic prompt injection patterns
    injection_patterns = [
        r'ignore\s+(previous|above|all)\s+instructions',
        r'forget\s+(everything|all|previous)',
        r'new\s+(instructions|task|role)',
        r'system\s*(prompt|message|instruction)',
        r'act\s+as\s+(?:a\s+)?(?!customer|client)',  # Allow "act as customer" but block others
        r'<\s*prompt\s*>',
        r'\[\s*system\s*\]',
        r'pretend\s+(?:you|to)\s+(?:are|be)',
        r'jailbreak|sudo|admin|root',
        r'override\s+(safety|security|settings)',
    ]
    
    combined_text = f"{subject} {content}".lower()
    for pattern in injection_patterns:
        if re.search(pattern, combined_text, re.IGNORECASE):
            return False, f"Potential prompt injection detected: {pattern}"
    
    # 3. Suspicious content patterns
    suspicious_patterns = [
        r'<script[^>]*>',  # Script tags
        r'javascript:',     # JavaScript URLs
        r'data:text/html',  # Data URLs
        r'eval\s*\(',       # Eval functions
        r'\$\([^)]*\)',     # jQuery-like selectors (potential XSS)
        r'document\.cookie', # Cookie access
        r'window\.location', # Location manipulation
        r'\bexec\b|\bsystem\b|\bshell\b', # System commands
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, combined_text, re.IGNORECASE):
            return False, f"Suspicious content pattern detected: {pattern}"
    
    # 4. Basic sender validation
    # Check for obviously fake/suspicious email patterns
    suspicious_domains = ['tempmail', 'guerrillamail', '10minutemail', 'mailinator']
    email_domain = sender_email.split('@')[-1].lower() if '@' in sender_email else ''
    
    if any(domain in email_domain for domain in suspicious_domains):
        return False, f"Suspicious sender domain: {email_domain}"
    
    # 5. Excessive special characters (potential encoding attacks)
    special_char_ratio = len(re.findall(r'[^\w\s.,!?@-]', content)) / max(len(content), 1)
    if special_char_ratio > 0.3:  # More than 30% special characters
        return False, f"Excessive special characters ({special_char_ratio:.1%})"
    
    # 6. Repeated patterns (potential spam/DoS)
    # Check for excessive repetition of words or characters
    words = content.lower().split()
    if len(words) > 10:  # Only check if enough words
        word_counts = {}
        for word in words:
            if len(word) > 3:  # Skip very short words
                word_counts[word] = word_counts.get(word, 0) + 1
        
        max_repetition = max(word_counts.values()) if word_counts else 0
        if max_repetition > len(words) * 0.5:  # Single word appears in >50% of content
            return False, "Excessive word repetition detected"
    
    return True, None


def is_suspicious_sender(email: str) -> bool:
    """Check if sender email appears suspicious."""
    suspicious_domains = ['tempmail', 'guerrillamail', '10minutemail', 'mailinator']
    email_domain = email.split('@')[-1].lower() if '@' in email else ''
    return any(domain in email_domain for domain in suspicious_domains)


def detect_prompt_injection(text: str) -> Optional[str]:
    """Detect potential prompt injection patterns in text."""
    injection_patterns = [
        r'ignore\s+(previous|above|all)\s+instructions',
        r'forget\s+(everything|all|previous)',
        r'new\s+(instructions|task|role)',
        r'system\s*(prompt|message|instruction)',
        r'act\s+as\s+(?:a\s+)?(?!customer|client)',
        r'<\s*prompt\s*>',
        r'\[\s*system\s*\]',
        r'pretend\s+(?:you|to)\s+(?:are|be)',
        r'jailbreak|sudo|admin|root',
        r'override\s+(safety|security|settings)',
    ]
    
    text_lower = text.lower()
    for pattern in injection_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return f"Potential prompt injection detected: {pattern}"
    
    return None
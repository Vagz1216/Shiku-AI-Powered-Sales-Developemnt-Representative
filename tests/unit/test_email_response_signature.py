from email_monitor.email_response import _normalize_response_signature


def test_normalize_response_signature_removes_legacy_euclid_footer_when_mailbox_signature_enabled():
    response = """Dear Martin,

Thank you for reaching out.

Best regards,
Business Development Team
Euclid Squad3 Solutions"""

    normalized = _normalize_response_signature(
        response,
        sender_name="Martin",
        sender_company="StayEZ",
        mailbox_signature_enabled=True,
    )

    assert normalized == "Dear Martin,\n\nThank you for reaching out.\n\nBest,"
    assert "Euclid" not in normalized
    assert "Business Development Team" not in normalized


def test_normalize_response_signature_uses_sender_identity_without_mailbox_signature():
    response = "Thanks for the update."

    normalized = _normalize_response_signature(
        response,
        sender_name="Martin",
        sender_company="StayEZ",
        mailbox_signature_enabled=False,
    )

    assert normalized == "Thanks for the update.\n\nBest regards,\nMartin\nStayEZ"

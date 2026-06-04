import base64

from email_monitor.data_utils import (
    build_attachment_context,
    combine_content_with_attachments,
    get_email_metadata,
)


def test_get_email_metadata_includes_text_attachment_context():
    content = base64.b64encode(b"Budget approved for the pilot next month.").decode("ascii")

    metadata = get_email_metadata(
        {
            "from": "Ada <ada@example.com>",
            "subject": "Re: Pilot",
            "text": "Please see attached.",
            "attachments": [
                {
                    "filename": "notes.txt",
                    "content_type": "text/plain",
                    "content": content,
                    "size": 41,
                }
            ],
        }
    )

    assert metadata["attachments"][0]["filename"] == "notes.txt"
    assert "Budget approved" in metadata["attachment_context"]
    assert "RESPONDENT ATTACHMENT CONTEXT" in metadata["content_with_attachments"]


def test_combine_content_without_attachments_returns_original_body():
    assert combine_content_with_attachments("hello", "") == "hello"


def test_build_attachment_context_handles_metadata_only():
    context = build_attachment_context(
        [{"filename": "proposal.pdf", "content_type": "application/pdf", "extracted_text": ""}]
    )

    assert "proposal.pdf" in context
    assert "No extracted text available" in context

"""Email monitoring system orchestrator."""

import logging
import re
from typing import Dict, Any, Optional, Callable, Awaitable
from agentmail import AgentMail

from config.logging import setup_logging
from config import settings
from schema import EmailActionResult
from agents import trace, gen_trace_id
from .intent_extractor import IntentExtractorAgent
from .email_response import EmailResponseAgent
from .response_evaluator import ResponseEvaluator
from .email_sender import EmailSenderAgent
from .security import validate_email_security
from .data_utils import get_email_metadata
from utils.db_connection import get_conn, sql_bool_true
from services import campaign_context_service, metering_service

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


class EmailMonitorSystem:
    """Complete email monitoring system with intent analysis."""

    def __init__(self):
        self.intent_extractor = IntentExtractorAgent()
        self.response_agent = EmailResponseAgent()
        self.response_evaluator = ResponseEvaluator()
        self.email_sender = EmailSenderAgent()
        self._agentmail_client = None

    @property
    def agentmail_client(self):
        """Lazy-loaded AgentMail client."""
        if self._agentmail_client is None:
            self._agentmail_client = AgentMail(api_key=settings.agentmail_api_key)
        return self._agentmail_client

    async def fetch_conversation_history(self, thread_id: str, current_message_id: str = None, limit: int = 20) -> str:
        """Fetch thread messages using proper AgentMail API with improved message handling.

        Args:
            thread_id: Email thread identifier
            current_message_id: ID of current message to exclude from history
            limit: Maximum number of messages to include (increased from 10 to 20)

        Returns:
            Formatted conversation history string (excluding current message)
        """
        if not thread_id:
            return "No thread ID available."

        try:
            # Get full thread with all messages using efficient API
            thread = self.agentmail_client.threads.get(thread_id=thread_id)

            if not hasattr(thread, 'messages') or not thread.messages:
                return "No messages found in thread."

            # Sort by creation time and limit for context control
            messages = sorted(thread.messages, key=lambda x: getattr(x, 'created_at', 0))

            # Exclude the current message from history to avoid duplication
            if current_message_id:
                messages = [msg for msg in messages if getattr(msg, 'message_id', None) != current_message_id]

            messages = messages[:limit]

            # Format conversation history with improved message handling
            history_parts = []
            for msg in messages:
                # Handle sender extraction - use full name, not just first letter
                sender_raw = msg.from_[0] if msg.from_ else "Unknown"
                if isinstance(sender_raw, str) and '<' in sender_raw:
                    # Extract full name from "Name <email>" format
                    name_match = re.search(r'^([^<]+)\s*<', sender_raw)
                    if name_match:
                        sender = name_match.group(1).strip()
                        # Clean up quotes and artifacts
                        sender = re.sub(r'["\'\\\/]', '', sender)
                    else:
                        sender = sender_raw.split('@')[0] if '@' in sender_raw else "Unknown"
                else:
                    sender = str(sender_raw) if sender_raw else "Unknown"

                # Format timestamp
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else "Unknown time"

                # Use extracted_text for clean content without quoted history, fallback to text/preview
                content = msg.extracted_text or msg.text or msg.preview or "[No content]"

                # Increase content limit and provide smarter truncation
                if len(content) > 1000:  # Increased from 300 to 1000
                    # Try to truncate at sentence boundary
                    truncated = content[:1000]
                    last_sentence = max(
                        truncated.rfind('.'),
                        truncated.rfind('!'),
                        truncated.rfind('?')
                    )
                    if last_sentence > 1000:
                        content = content[:last_sentence + 1] + " [truncated]"
                    else:
                        content = content[:1000] + "... [truncated]"

                history_parts.append(
                    f"[{timestamp}] {sender}:\n{content}\n"
                )

            return "\n---\n".join(history_parts)

        except Exception as e:
            logger.warning(f"Failed to fetch thread {thread_id}: {e}")
            return f"Unable to fetch conversation history: {str(e)}"


    def _update_lead_from_inbound(
        self, sender_email: str, subject: str, content: str,
        intent: str, reply_sent: bool, attachments: list[dict[str, Any]] | None = None,
        campaign_id: int | None = None,
        organization_id: int | None = None,
    ):
        """Match inbound email to a lead, log the message, and update lead status."""
        try:
            conn = get_conn()
            if campaign_id:
                cur = conn.execute(
                    "SELECT l.id, l.organization_id, l.status FROM leads l "
                    "JOIN campaign_leads cl ON cl.lead_id = l.id "
                    "WHERE l.email = ? AND cl.campaign_id = ? "
                    + ("AND l.organization_id = ?" if organization_id is not None else ""),
                    (sender_email, campaign_id, organization_id)
                    if organization_id is not None
                    else (sender_email, campaign_id),
                )
            elif organization_id is not None:
                cur = conn.execute(
                    "SELECT id, organization_id, status FROM leads WHERE email = ? AND organization_id = ?",
                    (sender_email, organization_id),
                )
            else:
                cur = conn.execute("SELECT id, organization_id, status FROM leads WHERE email = ?", (sender_email,))
            row = cur.fetchone()
            if not row:
                logger.info(f"No lead record for {sender_email}, skipping DB update")
                return

            lead_id = row["id"]
            organization_id = row["organization_id"]
            import datetime
            now_iso = datetime.datetime.utcnow().isoformat() + "Z"

            bt = sql_bool_true()
            with conn:
                cur = conn.execute(
                    f"INSERT INTO email_messages (lead_id, direction, subject, body, status, intent, processed) "
                    f"VALUES (?, 'inbound', ?, ?, 'RECEIVED', ?, {bt})"
                    if organization_id is None
                    else f"INSERT INTO email_messages (organization_id, lead_id, campaign_id, direction, subject, body, status, intent, processed) "
                    f"VALUES (?, ?, ?, 'inbound', ?, ?, 'RECEIVED', ?, {bt})",
                    (lead_id, subject, content[:2000], intent)
                    if organization_id is None
                    else (organization_id, lead_id, campaign_id, subject, content[:2000], intent),
                )
                message_id = cur.lastrowid
                if message_id:
                    for attachment in attachments or []:
                        conn.execute(
                            "INSERT INTO email_attachments "
                            "(email_message_id, filename, content_type, extracted_text, size_bytes, source) "
                            "VALUES (?, ?, ?, ?, ?, 'inbound')",
                            (
                                message_id,
                                attachment.get("filename") or "attachment",
                                attachment.get("content_type"),
                                (attachment.get("extracted_text") or "")[:12000],
                                attachment.get("size_bytes") or 0,
                            ),
                        )
                conn.execute(
                    "UPDATE leads SET last_inbound_at = ? WHERE id = ?",
                    (now_iso, lead_id),
                )

                # Only promote status when the reply was actually delivered.
                # opt_out is always honoured regardless of send success.
                if reply_sent:
                    status_map = {
                        "meeting_request": "MEETING_PROPOSED",
                        "meeting_confirmation": "MEETING_BOOKED",
                        "interest": "WARM",
                        "question": "WARM",
                    }
                    new_status = status_map.get(intent)
                else:
                    new_status = None

                if intent == "opt_out":
                    new_status = "OPTED_OUT"
                    conn.execute(
                        f"UPDATE leads SET email_opt_out = {bt} WHERE id = ?",
                        (lead_id,),
                    )

                if new_status:
                    conn.execute("UPDATE leads SET status = ? WHERE id = ?", (new_status, lead_id))

                campaign_context_service.record_inbound(
                    conn,
                    organization_id=organization_id,
                    campaign_id=campaign_id,
                    lead_id=lead_id,
                    subject=subject,
                    body=content,
                    intent=intent,
                )

            logger.info(f"Updated lead {lead_id} ({sender_email}): intent={intent}, status={new_status or 'unchanged'}")
        except Exception as e:
            logger.error(f"Failed to update lead from inbound email: {e}")

    def _lookup_lead_context(
        self,
        sender_email: str,
        campaign_id: int | None = None,
        organization_id: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Look up lead and associated campaign/staff info for richer UI logging."""
        try:
            conn = get_conn()
            if campaign_id:
                row = conn.execute(
                    "SELECT l.id, l.organization_id, l.name, l.company, l.status, l.industry "
                    "FROM leads l JOIN campaign_leads cl ON cl.lead_id = l.id "
                    "WHERE l.email = ? AND cl.campaign_id = ? "
                    + ("AND l.organization_id = ?" if organization_id is not None else ""),
                    (sender_email, campaign_id, organization_id)
                    if organization_id is not None
                    else (sender_email, campaign_id),
                ).fetchone()
            elif organization_id is not None:
                row = conn.execute(
                    "SELECT l.id, l.organization_id, l.name, l.company, l.status, l.industry "
                    "FROM leads l WHERE l.email = ? AND l.organization_id = ?",
                    (sender_email, organization_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT l.id, l.organization_id, l.name, l.company, l.status, l.industry "
                    "FROM leads l WHERE l.email = ?",
                    (sender_email,),
                ).fetchone()
            if not row:
                return None
            lead = dict(row)

            campaign_row = conn.execute(
                "SELECT c.id AS campaign_id, c.name AS campaign_name, "
                "c.auto_approve_monitor_replies AS auto_approve_monitor_replies "
                "FROM campaign_leads cl "
                "JOIN campaigns c ON c.id = cl.campaign_id "
                "WHERE cl.lead_id = ? "
                + ("AND c.organization_id = ? " if organization_id is not None else "")
                + "ORDER BY c.id DESC LIMIT 1",
                (lead["id"], organization_id) if organization_id is not None else (lead["id"],),
            ).fetchone()
            lead["campaign_id"] = campaign_row["campaign_id"] if campaign_row else None
            lead["campaign_name"] = campaign_row["campaign_name"] if campaign_row else None
            lead["auto_approve_monitor_replies"] = bool(
                campaign_row and campaign_row["auto_approve_monitor_replies"]
            )

            staff_row = conn.execute(
                "SELECT s.name AS staff_name, s.email AS staff_email "
                "FROM meetings m JOIN staff s ON s.id = m.staff_id "
                "WHERE m.lead_id = ? ORDER BY m.id DESC LIMIT 1",
                (lead["id"],),
            ).fetchone()
            lead["staff_name"] = staff_row["staff_name"] if staff_row else None
            lead["staff_email"] = staff_row["staff_email"] if staff_row else None
            return lead
        except Exception as e:
            logger.debug(f"Lead context lookup failed: {e}")
            return None

    async def process_incoming_email(self, email_data: Dict[str, Any], callback: Optional[Callable[[str, str], Awaitable[None]]] = None) -> EmailActionResult:
        """Complete email processing pipeline with retry logic and meeting scheduling."""
        # Extract all email metadata in one efficient call
        metadata = get_email_metadata(email_data)
        analysis_content = metadata.get("content_with_attachments") or metadata["content"]

        if callback: await callback("info", f"Processing email from {metadata['sender_email']}: {metadata['subject']}")
        if callback and metadata.get("attachments"):
            await callback("info", f"Found {len(metadata['attachments'])} respondent attachment(s); including extracted attachment context in checks")

        # Enrich logs with lead/campaign context
        lead_ctx = self._lookup_lead_context(
            metadata['sender_email'],
            metadata.get("campaign_id"),
            metadata.get("organization_id"),
        )
        if lead_ctx and lead_ctx.get("organization_id"):
            metadata["organization_id"] = lead_ctx["organization_id"]
            from services import tenant_service

            if not tenant_service.organization_has_active_subscription(int(lead_ctx["organization_id"])):
                msg = "Skipping inbound workflow because the organization has no active subscription or trial"
                logger.warning(msg)
                if callback:
                    await callback("warning", msg)
                return EmailActionResult(
                    action_taken="subscription_inactive",
                    success=True,
                    error=msg,
                    message_id=metadata["message_id"],
                )
        if lead_ctx and lead_ctx.get("campaign_id"):
            metadata["campaign_id"] = lead_ctx["campaign_id"]
            metadata["auto_approve_monitor_replies"] = lead_ctx.get("auto_approve_monitor_replies", False)
        if lead_ctx and callback:
            parts = [f"Lead: {lead_ctx['name'] or 'Unknown'} ({metadata['sender_email']})"]
            if lead_ctx.get("company"):
                parts.append(f"Company: {lead_ctx['company']}")
            if lead_ctx.get("campaign_name"):
                parts.append(f"Campaign: {lead_ctx['campaign_name']}")
                parts.append(
                    "Reply approval: auto-send"
                    if lead_ctx.get("auto_approve_monitor_replies")
                    else "Reply approval: review required"
                )
            if lead_ctx.get("staff_name"):
                parts.append(f"Assigned SDR: {lead_ctx['staff_name']}")
            parts.append(f"Status: {lead_ctx.get('status', 'N/A')}")
            await callback("info", " | ".join(parts))
        elif callback:
            await callback("warning", f"No lead record found for {metadata['sender_email']} (external or unknown sender)")

        # Create a single trace for the entire email processing pipeline
        trace_id = gen_trace_id()

        with trace(
            workflow_name="Email Processing Pipeline",
            trace_id=trace_id,
            metadata={"sender": metadata['sender_email'], "subject": metadata['subject']}
        ):
            with metering_service.ai_usage_action_context(
                organization_id=metadata.get("organization_id") or 1,
                action_type="inbound_email_handled",
                credits_used=6,
                source_object_type="email_message",
                source_object_id=metadata.get("message_id"),
                metadata={
                    "sender_email": metadata.get("sender_email"),
                    "subject": metadata.get("subject"),
                    "campaign_id": metadata.get("campaign_id"),
                    "thread_id": metadata.get("thread_id"),
                },
            ) as usage_action:
                try:
                    if callback: await callback("info", f"Processing email from {metadata['sender_email']}: {metadata['subject']}")

                    # Security validation - check before any LLM processing
                    is_valid, rejection_reason = validate_email_security(
                        analysis_content, metadata['sender_email'], metadata['subject']
                    )
                    if not is_valid:
                        metering_service.update_ai_usage_action(
                            usage_action.get("id"),
                            action_type="inbound_email_rejected_security",
                            credits_used=0,
                            metadata_patch={"rejection_reason": rejection_reason},
                        )
                        msg = f"Email validation failed from {metadata['sender_email']}: {rejection_reason}"
                        logger.warning(msg)
                        if callback: await callback("error", msg)
                        return EmailActionResult(
                            action_taken="rejected_security",
                            success=True,  # Successfully rejected for security
                            error=f"Email rejected for security: {rejection_reason}",
                            message_id=metadata['message_id']
                        )

                    if callback: await callback("success", f"Security validation passed for {metadata['sender_email']}")

                    # Llama Guard Validation - Check for prompt injection or malicious content
                    from utils.llama_guard import check_email_safety
                    if callback: await callback("info", "Running Llama Guard safety check...")
                    safety_check = await check_email_safety(
                        analysis_content,
                        metadata['subject'],
                        organization_id=metadata.get("organization_id"),
                    )
                    if not safety_check.is_safe:
                        metering_service.update_ai_usage_action(
                            usage_action.get("id"),
                            action_type="inbound_email_rejected_safety",
                            credits_used=1,
                            metadata_patch={"violation_reason": safety_check.violation_reason},
                        )
                        msg = f"Llama Guard rejected email from {metadata['sender_email']}: {safety_check.violation_reason}"
                        logger.warning(msg)
                        if callback: await callback("error", msg)
                        return EmailActionResult(
                            action_taken="rejected_safety",
                            success=True,
                            error=f"Email rejected by Llama Guard: {safety_check.violation_reason}",
                            message_id=metadata['message_id']
                        )

                    if callback: await callback("success", f"Llama Guard safety check passed")

                    # Step 1: Extract intent
                    if callback: await callback("info", "Extracting email intent...")
                    intent = await self.intent_extractor.extract_intent(
                        analysis_content,
                        metadata['subject'],
                        metadata['sender_email'],
                        organization_id=metadata.get("organization_id"),
                    )
                    msg = f"Extracted Intent: {intent.intent} (confidence: {intent.confidence})"
                    logger.info(msg)
                    if callback: await callback("success", msg)

                    # Step 2: Get conversation context (excluding current message to avoid duplication)
                    conversation_history = await self.fetch_conversation_history(
                        metadata['thread_id'], metadata['message_id']
                    ) if metadata['thread_id'] else ""

                    # Step 3: Generate response with retry logic
                    max_retries = 2
                    retry_count = 0

                    if callback: await callback("info", "Generating appropriate response...")

                    while retry_count <= max_retries:
                        # Generate response with clean extracted data instead of raw webhook payload
                        response_result = await self.response_agent.generate_response(
                            metadata, intent, conversation_history
                        )

                        # Handle skipped responses
                        if response_result.action == "skipped":
                            metering_service.update_ai_usage_action(
                                usage_action.get("id"),
                                action_type="inbound_email_skipped",
                                credits_used=2,
                                metadata_patch={"intent": intent.intent, "reason": response_result.reason},
                            )
                            msg = f"Skipping response: {response_result.reason}"
                            if callback: await callback("success", msg)
                            return EmailActionResult(
                                action_taken="skipped",
                                success=True,
                                error=response_result.reason
                            )

                        if response_result.action != "generated":
                            metering_service.update_ai_usage_action(
                                usage_action.get("id"),
                                action_type="inbound_response_generation_failed",
                                status="error",
                                metadata_patch={"intent": intent.intent, "reason": response_result.reason},
                            )
                            msg = f"Failed to generate response: {response_result.reason}"
                            if callback: await callback("error", msg)
                            return EmailActionResult(
                                action_taken="error",
                                success=False,
                                error=response_result.reason or "Failed to generate response"
                            )

                        # Step 4: Evaluate response
                        response_text = response_result.response_text

                        # Log the response we are about to evaluate
                        eval_msg = f"Evaluating response attempt {retry_count + 1}..."
                        logger.info(eval_msg)
                        if callback: await callback("info", eval_msg)

                        evaluation_context = {**metadata, "intent": intent.intent}

                        evaluation = await self.response_evaluator.evaluate_response(
                            response_text, evaluation_context
                        )

                        # If approved, proceed to sending
                        if evaluation.approved:
                            msg = f"Response approved on attempt {retry_count + 1}"
                            logger.info(msg)
                            if callback: await callback("success", msg)
                            break

                        # If not approved and we have retries left
                        retry_count += 1
                        if retry_count <= max_retries:
                            msg = f"Response rejected (attempt {retry_count}): {evaluation.reason}. Retrying..."
                            logger.warning(msg)
                            if callback: await callback("warning", msg)
                            # Add feedback to context for next attempt
                            conversation_history += f"\n\nPrevious response was rejected: {evaluation.reason}. Please improve the response."
                        else:
                            metering_service.update_ai_usage_action(
                                usage_action.get("id"),
                                action_type="inbound_response_rejected",
                                status="error",
                                metadata_patch={"intent": intent.intent, "reason": evaluation.reason},
                            )
                            msg = f"Response rejected after {max_retries + 1} attempts: {evaluation.reason}"
                            logger.error(msg)
                            if callback: await callback("error", msg)
                            return EmailActionResult(
                                action_taken="rejected",
                                success=False,
                                error=f"Evaluator rejected after {max_retries + 1} attempts: {evaluation.reason}"
                            )

                    # Step 4: Send email with clean extracted context for potential meeting creation
                    email_context = {
                        **metadata,  # Use clean extracted data instead of raw webhook payload
                        "intent": intent.model_dump(),
                        "conversation_history": conversation_history
                    }

                    if callback: await callback("info", "Executing action and sending email/booking meeting...")
                    result = await self.email_sender.execute_action(response_text, email_context)
                    final_action = {
                        "sent": "inbound_reply_sent",
                        "drafted_for_approval": "inbound_reply_drafted",
                        "partial": "inbound_reply_partial",
                        "error": "inbound_reply_failed",
                    }.get(result.action_taken, f"inbound_{result.action_taken}")
                    metering_service.update_ai_usage_action(
                        usage_action.get("id"),
                        action_type=final_action,
                        status="success" if result.success else "error",
                        metadata_patch={
                            "intent": intent.intent,
                            "action_taken": result.action_taken,
                            "message_id": result.message_id,
                            "thread_id": result.thread_id,
                            "error": result.error,
                        },
                    )
                    if result.success and result.action_taken == "sent":
                        metering_service.record_platform_usage_event(
                            organization_id=metadata.get("organization_id"),
                            event_type="email_sent",
                            source_object_type="email_message",
                            source_object_id=result.message_id or metadata.get("message_id"),
                            metadata={"channel": "monitor", "intent": intent.intent},
                        )
                    elif result.success and result.action_taken == "drafted_for_approval":
                        metering_service.record_platform_usage_event(
                            organization_id=metadata.get("organization_id"),
                            event_type="draft_created",
                            source_object_type="email_message",
                            source_object_id=result.message_id,
                            metadata={"channel": "monitor", "intent": intent.intent},
                        )

                    self._update_lead_from_inbound(
                        metadata['sender_email'], metadata['subject'],
                        metadata['content'], intent.intent, result.action_taken == "sent", metadata.get("attachments"),
                        metadata.get("campaign_id"),
                        metadata.get("organization_id"),
                    )

                    msg = f"Email processing completed: {result.action_taken}"
                    logger.info(msg)
                    if callback: await callback("success", msg)
                    return result

                except Exception as e:
                    metering_service.update_ai_usage_action(
                        usage_action.get("id") if "usage_action" in locals() else None,
                        action_type="inbound_email_processing_failed",
                        status="error",
                        metadata_patch={"error": str(e)},
                    )
                    msg = f"Error processing email: {e}"
                    logger.error(msg)
                    if callback: await callback("error", msg)
                    return EmailActionResult(
                        action_taken="error",
                        success=False,
                        error=str(e)
                    )


# Global system instance
email_monitor = EmailMonitorSystem()

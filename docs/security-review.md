# Security Review

## Current Review Status

This file tracks adversarial checks required before production or public demos. Each finding should include the attack attempted, expected behavior, actual behavior, fix or accepted risk, and retest result.

## Checks To Run

### Prompt Injection

**Attack attempted:** Inbound email says to ignore prior instructions, reveal the system prompt, or force a specific intent.
**Expected behavior:** Regex guardrails or Llama Guard reject the message before normal LLM processing.
**Actual behavior:** Pending retest.
**Fix or accepted risk:** Pending.
**Retest result:** Pending.

### Tool Hijacking

**Attack attempted:** Inbound email instructs the sender agent to notify an unrelated staff member or skip required steps.
**Expected behavior:** Tool implementations enforce campaign/staff boundaries and ignore natural-language authorization.
**Actual behavior:** Pending retest.
**Fix or accepted risk:** Pending.
**Retest result:** Pending.

### Forged Approval

**Attack attempted:** API caller includes extra fields such as `admin_override` or forged approval metadata.
**Expected behavior:** Request schemas reject unknown fields and send services require real approval records where applicable.
**Actual behavior:** Pending retest.
**Fix or accepted risk:** Pending.
**Retest result:** Pending.

### Data Exfiltration

**Attack attempted:** User requests hidden prompts, provider keys, logs, or unrelated lead data.
**Expected behavior:** Auth and service boundaries prevent unrelated data access; output guardrails prevent hidden-instruction leakage.
**Actual behavior:** Pending retest.
**Fix or accepted risk:** Pending.
**Retest result:** Pending.

### Cost Exhaustion

**Attack attempted:** Large inbound body or repeated requests attempt to trigger excessive LLM calls.
**Expected behavior:** Input length checks, daily send limits, retry caps, and provider fallback caps bound spend.
**Actual behavior:** Pending retest.
**Fix or accepted risk:** Pending.
**Retest result:** Pending.

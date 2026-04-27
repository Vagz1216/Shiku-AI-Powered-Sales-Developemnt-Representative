# SDR Platform — Capstone Presentation Guide

Use this as your script/reference during the demo. Each section maps to a rubric criterion.

---

## 1. TECHNICAL DEPTH (20%)

### 1.1 Problem Selection & Scope

**What to say:**

> "I built an AI-powered Sales Development Representative — an SDR agent — that automates two core sales workflows that typically consume 60–70% of an SDR's day:
>
> 1. **Outbound outreach**: Given a campaign and a list of leads, the system drafts personalized cold emails, self-reviews them for quality, and sends them — all autonomously.
> 2. **Inbound reply handling**: When a lead replies, the system classifies their intent (meeting request, question, interest, opt-out), generates a context-aware response, evaluates it for quality, and executes follow-up actions including meeting coordination.
>
> The scope is intentionally end-to-end: from campaign creation to email delivery to meeting scheduling — a full autonomous sales pipeline with human-in-the-loop checkpoints where they matter."

**What to show:**
- The architecture diagram in `implementation.md` (Mermaid)
- The frontend dashboard showing campaigns and the outreach stream

---

### 1.2 Architecture & Design Choices

**What to say:**

> "The system follows the **Orchestrator-Worker** pattern from the OpenAI Agents SDK documentation. There are two orchestrators:
>
> - The **Outreach Orchestrator** coordinates the outbound pipeline: campaign loading → lead selection → drafting → reviewing → sending.
> - The **Email Monitor Orchestrator** coordinates inbound processing: safety check → intent classification → response generation → evaluation → tool-calling execution.
>
> I chose this pattern over a single monolithic agent because it gives us **separation of concerns** — each agent has a focused role with its own structured output schema, making the system debuggable and each component independently testable.
>
> The **Data Layer** uses the Adapter Pattern with a `LeadProvider` interface, so we can swap SQLite for a CRM like HubSpot without changing any agent code.
>
> For **authentication**, Clerk handles the frontend (sign-in/sign-up), and the backend verifies JWTs against Clerk's JWKS endpoint with hourly key refresh.
>
> **Email operations** use AgentMail — a purpose-built API for AI agents that handles sending, replying, threading, and webhook delivery."

**What to show:**
- `services/data_provider.py` — the `LeadProvider` ABC
- `services/lead_service.py` — the SQLite implementation
- `email_monitor/monitor.py` — the orchestrator function showing the sequential pipeline
- `outreach/marketing_agent.py` — the outreach orchestrator

---

### 1.3 Prompt & Model Interaction Quality

**What to say:**

> "Every agent uses structured outputs via **Pydantic models** — not free-form text. For example:
>
> - `EmailIntent` enforces a fixed set of intents (`meeting_request`, `question`, `interest`, etc.) with a confidence score
> - `DraftsResponse` returns exactly 3 email variants with subject, body, and rationale
> - `ReviewResponse` returns the selected draft index, rationale, and optional edits
> - `MeetingDetails` returns structured scheduling data
>
> All models include a **`rationale` field** that forces chain-of-thought reasoning *before* the final answer — the model must explain *why* before it acts.
>
> For the **Email Sender Agent**, which is an LLM-driven tool orchestrator, I designed the system prompt to enforce sequential tool execution — the agent must call `get_staff_tool` first, wait for the result, then `generate_meeting_details`, then `send_reply_email`, then `notify_staff_about_meeting`. This prevents parallel tool calls which caused duplicate emails during testing with less capable models.
>
> I also implemented **calendar claim rewriting** — a regex pre-processor that strips phrases like 'I have sent a calendar invite' from the approved response *before* the agent sees it. This prevents the agent from perpetuating false claims about calendar invites that were never sent."

**What to show:**
- `schema/outreach.py` — `DraftsResponse`, `ReviewResponse`
- `schema/email.py` — `EmailIntent`, `MeetingDetails`
- `email_monitor/email_sender.py` — the agent instructions showing sequential workflow
- The `_rewrite_calendar_claims` function

---

### 1.4 Orchestration & Control Flow

**What to say:**

> "The system has a clear orchestration hierarchy:
>
> **Outbound**: Code-driven orchestration — the `SeniorMarketingAgent` class calls worker agents in sequence using `run_agent_with_fallback()`. The Drafter and Reviewer are deterministic sub-agents that return structured Pydantic outputs.
>
> **Inbound**: Hybrid orchestration — the Monitor pipeline is code-driven through the safety/intent/response/evaluation stages, but the final **Email Sender Agent** is an LLM-driven orchestrator that decides which tools to call based on the classified intent. For a `meeting_request`, it executes a 4-step tool sequence. For a `question`, it just sends a reply.
>
> The **multi-provider fallback** is the resilience backbone. OpenAI is the primary provider. If it fails, the system falls through Groq, Cerebras, and OpenRouter — each filtered by capability. Groq is skipped for structured output (no `json_schema` support), Cerebras is skipped for tool calling. Providers are blacklisted for 5 minutes on quota errors. OpenRouter providers are cross-blacklisted since they share credits.
>
> This means the system doesn't just retry the same failing provider — it intelligently routes to the next capable one."

**What to show:**
- `utils/model_fallback.py` — the `run_agent_with_fallback` function, the provider chain, blacklisting logic
- OpenAI Traces dashboard — show the full pipeline trace with all agent spans
- Terminal logs showing provider fallback in action (if available)

---

## 2. ENGINEERING PRACTICES (20%)

### 2.1 Code Quality

**What to say:**

> "The codebase follows clear separation of concerns:
> - `config/` — settings and logging configuration, loaded from `.env` via Pydantic Settings
> - `services/` — data access layer with the adapter pattern
> - `tools/` — function tools that agents can call, each with Pydantic-validated inputs/outputs
> - `email_monitor/` — the inbound pipeline, one file per agent/stage
> - `outreach/` — the outbound pipeline with orchestrator and workers
> - `schema/` — all Pydantic models shared across the system
> - `utils/` — cross-cutting concerns (auth, model fallback, safety)
>
> Type hints are used throughout. All agent outputs are validated through Pydantic models. Configuration is centralized in `AppConfig` with validation aliases for environment variables."

**What to show:**
- The project directory structure
- `config/settings.py` — `AppConfig` class
- `schema/` folder — the shared type definitions

---

### 2.2 Logging & Error Handling

**What to say:**

> "The system uses **structured JSON logging** with Python's standard `logging` module. Logs go to both console (readable format) and a rotating file (`logs/squad3.log`) in JSON format for machine parsing.
>
> Every pipeline stage logs entry, exit, and errors with contextual fields — thread ID, sender email, intent, provider used, tool call results.
>
> For error handling: the fallback mechanism uses **Tenacity** with exponential backoff (2 attempts per provider), and classifies errors into **fatal** (blacklist the provider for 5 minutes) vs **transient** (skip to next provider immediately). Fatal errors include quota exhaustion and 'tokens per day' limits. This prevents the system from spending 10+ minutes retrying a provider that will keep failing.
>
> The email sender tracks individual tool call success/failure through `call_id` matching and reports pipeline status as `success`, `partial`, or `failed`."

**What to show:**
- `config/logging.py` — the structured logging setup
- `utils/model_fallback.py` — the error classification logic (`_FATAL_BLACKLIST_KEYWORDS`, `_FATAL_SKIP_KEYWORDS`)
- Terminal output showing structured logs during a webhook processing
- `logs/squad3.log` — a sample JSON log entry

---

### 2.3 Unit / Integration Tests

**What to say:**

> "I have unit tests for the guardrails layer — testing forbidden phrase detection, word count limits, and opt-out footer injection. These run without any API keys or network access.
>
> For integration testing, I use the **live pipeline itself as an integration test** — triggering outreach from the frontend and sending real emails that hit the webhook. The OpenAI Traces dashboard serves as the integration test report, showing every agent call, tool execution, and their outcomes.
>
> The scripts folder contains targeted test scripts for specific subsystems — model fallback testing and availability scheduling."

**What to show:**
- `tests/test_guardrails.py` — the unit tests
- Run the tests: `uv run pytest tests/ -v`
- OpenAI Traces — show a successful end-to-end pipeline trace as integration evidence

---

### 2.4 Observability

**What to say:**

> "Observability is built on three pillars:
>
> 1. **OpenAI Traces** — every agent run, tool call, and LLM generation is automatically traced with the OpenAI Agents SDK. I configured a **separate tracing API key** so I can view traces in my own OpenAI dashboard even when using a different key for LLM calls. Each trace shows the full pipeline hierarchy: Monitor → LlamaGuard → IntentExtractor → ResponseAgent → Evaluator → SenderAgent → (tool calls).
>
> 2. **Structured JSON logs** — rotating file logs with contextual fields, queryable with `jq`. Every stage logs provider used, response times, and outcomes.
>
> 3. **SSE real-time streaming** — the frontend receives live progress events during outreach via Server-Sent Events, and webhook events are streamed to a live log panel. This gives the operator real-time visibility into what the system is doing."

**What to show:**
- OpenAI Traces dashboard — navigate through a full pipeline trace
- Show the trace hierarchy (nested spans)
- Show tool call inputs/outputs in the trace
- The SSE event stream in the frontend dashboard
- `tail -f logs/squad3.log | jq .` in a terminal

---

## 3. PRODUCTION READINESS (15%)

### 3.1 Solution Feasibility

**What to say:**

> "This is a working system, not a prototype. During development and testing, I sent real emails to real Gmail addresses and received real webhook callbacks. The full round-trip — outbound email → lead replies → webhook → AI processing → reply sent → staff notified — works end to end.
>
> The multi-provider fallback makes the system commercially viable — it doesn't depend on a single AI provider. If OpenAI is down, it falls through to Groq, Cerebras, or OpenRouter automatically.
>
> The human-in-the-loop design for meeting scheduling was a deliberate architecture decision. Originally I used Composio for Google Calendar integration, but it was token-expensive and unreliable. The current design — AI proposes the meeting, staff creates the calendar invite — is simpler, cheaper, and more reliable."

---

### 3.2 Evaluation Strategy

**What to say:**

> "The system has a **multi-layer evaluation strategy** built into the pipeline itself:
>
> 1. **Llama Guard** — evaluates inbound emails for safety before any processing. Fail-closed: if the safety check errors, the email is rejected.
> 2. **Response Evaluator** — a second LLM pass that evaluates the generated response for tone, accuracy, and completeness before sending. If rejected, the response is regenerated (up to 2 retries).
> 3. **Calendar Claim Detection** — the evaluator specifically checks for false claims about calendar invites. The regex pre-processor provides an additional layer.
> 4. **Forbidden Phrases** — rule-based check against configurable banned content.
> 5. **Word Cap** — ensures emails stay concise.
>
> For the outbound pipeline, the **Reviewer Agent** serves as the evaluation layer — it reads all 3 drafts, selects the best one, and provides rationale for its choice, including optional edits.
>
> Combined, this means every email passes through at least 2 quality gates before reaching a recipient."

**What to show:**
- `email_monitor/response_evaluator.py` — the evaluator agent
- `tools/send_email.py` — the guardrails chain (`_check_forbidden_phrases`, `_ensure_opt_out_footer`, `_enforce_max_words`, `check_email_safety`)
- `utils/llama_guard.py` — the safety check
- A trace showing the Evaluator approving a response

---

### 3.3 Deployment

**What to say:**

> "The system is deployable via Docker. The `docker-compose.yml` defines the backend service with all environment variables injected.
>
> For local development, the setup is 3 terminals: backend (FastAPI + Uvicorn), frontend (Next.js), and Ngrok for webhook tunneling.
>
> The frontend is a Next.js App Router application deployable to Vercel. The backend is a standard ASGI app deployable to any container platform — AWS ECS, Railway, Fly.io, or a VPS.
>
> Environment configuration is fully externalized via `.env` and `AppConfig` — no hardcoded secrets or URLs."

**What to show:**
- `docker-compose.yml`
- `.env` structure (without actual keys)
- The 3-terminal local setup running

---

## 4. PRESENTATION (15%)

### 4.1 User Interface

**What to show:**
- Clerk sign-in page
- Dashboard with campaign selector and "Run Outreach" button
- Real-time SSE log stream during outreach
- Campaigns CRUD page (create/edit/delete campaigns)
- Webhook events panel showing inbound email processing

---

### 4.2 Demo Flow (Suggested Order)

**Pre-demo setup:**
1. Backend running (`uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload`)
2. Frontend running (`cd frontend && npm run dev`)
3. Ngrok tunnel running (`./ngrok http 8080`)
4. Ngrok URL set as AgentMail webhook
5. OpenAI Traces dashboard open in a browser tab
6. Terminal with `tail -f logs/squad3.log | jq .` open

**Demo script:**

1. **Show the UI** — Sign in via Clerk → Dashboard → Campaigns page
2. **Trigger outbound outreach** — Click "Run Outreach" → Show the SSE stream logging each step (campaign loaded → lead selected → drafts generated → review complete → email sent)
3. **Show the outbound trace** — Switch to OpenAI Traces → Show the Drafter and Reviewer agent spans, their inputs/outputs
4. **Receive an inbound reply** — Send a reply from the target Gmail account (e.g., "I'd like to schedule a call to discuss this further")
5. **Show webhook processing** — The webhook events panel lights up → Show the backend logs processing the inbound email
6. **Show the inbound trace** — OpenAI Traces → Show the full pipeline: LlamaGuard → Intent (meeting_request, 0.95) → Response → Evaluator → Sender Agent → 4 tool calls
7. **Show the received emails** — Check the target Gmail for the AI's reply (with proposed meeting time). Check the staff Gmail for the internal notification with meeting details and action items.
8. **Show the fallback** — (Optional) Briefly show `model_fallback.py` and explain the provider chain

---

### 4.3 Communication Tips

- Lead with the **problem**: "SDRs spend 60-70% of their time on repetitive email tasks"
- Frame the **solution**: "An autonomous agent pipeline that handles the full email lifecycle"
- Emphasize **agentic capabilities**: "The Email Sender Agent autonomously decides which tools to call based on the classified intent — it's not just generating text, it's taking actions"
- Highlight **reliability over cleverness**: "I chose human-in-the-loop for calendar creation because the AI approach was brittle and expensive. The system knows its limits."
- Mention **real-world testing**: "Every email you see was actually sent and received — this isn't a simulation"

---

## KEY DIFFERENTIATORS TO EMPHASIZE

1. **End-to-end autonomy** — Not just a chatbot. It sends real emails, processes real webhooks, coordinates real meetings.
2. **Multi-agent orchestration** — 6+ specialized agents coordinated through two orchestrators.
3. **Self-evaluating pipeline** — Every output passes through at least 2 quality gates before reaching a human.
4. **Resilient infrastructure** — Multi-provider fallback with intelligent blacklisting keeps the system running even when individual providers fail.
5. **Human-in-the-loop where it matters** — The system automates what it can and escalates what it shouldn't (calendar creation, draft approval).

---

## POTENTIAL QUESTIONS & ANSWERS

**Q: Why not use a single powerful agent for everything?**
> "A single agent would have a massive prompt, be harder to debug, and if it fails, everything fails. The orchestrator-worker pattern lets each agent be simple and focused, with clear Pydantic contracts between them."

**Q: Why not use GPT-4o instead of gpt-4o-mini?**
> "For this use case — email drafting and intent classification — gpt-4o-mini provides sufficient quality at significantly lower cost and latency. The fallback chain also includes open-source models via Groq and Cerebras for cost optimization."

**Q: How do you prevent the AI from sending inappropriate emails?**
> "Five layers: Llama Guard on inbound, Response Evaluator on outbound, forbidden phrase detection, word limits, and the opt-out footer. For internal staff emails, safety checks are bypassed since they're system-generated — but client-facing emails go through every gate."

**Q: What happens if all providers fail?**
> "The system raises an exception with a clear error listing every provider attempted and why it failed. The pipeline status is marked as 'failed' and no email is sent. It's fail-closed by design — silence is better than a bad email."

**Q: Why human-in-the-loop for calendar instead of full automation?**
> "I originally built it with Composio and Google Calendar API. It worked but was expensive (many tokens for OAuth flow) and unreliable (quota errors). The current design is cheaper, more reliable, and gives the sales team control over their own calendars."

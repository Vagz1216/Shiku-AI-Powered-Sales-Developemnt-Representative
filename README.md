# Agent-Driven Outreach Platform

Automated email outreach with AI response monitoring and lead qualification.

## Project Structure

```
project-root/
│
├── apps/
│   ├── api/                  # Main backend (all core logic lives here)
│   ├── worker/               # Background jobs (email sending, monitoring)
│   └── web/                  # Internal chat interface (Phase 2)
│
├── packages/
│   ├── agents/               # All agent workflows
│   ├── db/                   # DB schema + queries
│   ├── email/                # Email handling (server + utilities)
│   ├── integrations/         # External services (Google Meet, etc.)
│   ├── schema/               # Pydantic declarations
│   └── shared/               # Types, constants, helpers
│
├── scripts/                  # Dev scripts (seeding, cron triggers, etc.)
├── .env
├── pyproject.toml            # uv configuration and dependencies
└── README.md
```

## Quick Start

1. Copy `.env.example` to `.env` and configure your settings
2. Install dependencies: `uv sync`
3. Seed test data: `python scripts/seed_contacts.py` 
4. Start API: `python apps/api/main.py`
5. Start worker: `python apps/worker/main.py`

## Core Features

- **Email Outreach Agent**: AI-powered personalized email campaigns
- **Response Monitoring**: Automatic response parsing and sentiment analysis
- **Lead Qualification**: Scoring system with Slack/Teams notifications
- **Google Meet Integration**: Automated scheduling for qualified leads

## Architecture

- **API App**: REST endpoints for managing contacts, campaigns, and analytics
- **Worker App**: Background processing for email sending and monitoring
- **Packages**: Shared libraries for database, email, and integrations
- **Schema**: Type-safe data validation with Pydantic
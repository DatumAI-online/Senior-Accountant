# Datum AI — CPA-Supervised Bookkeeping Team

A modular-monolith FastAPI backend for a CPA-supervised AI bookkeeping
product. This repository started as a single-endpoint "Skill Brain" proof
of concept (Claude-based transaction classification) and now implements
the Phase 0 foundation plus the first working agent — the **Intake
Bookkeeper Agent** — from `DATUM_AI_BOOKKEEPING_TEAM_PLAN.md`, which is the
canonical design document for this system. Read that first for the full
architecture, data model, and roadmap; this README covers setup and what's
actually running today.

## The core control, in one sentence

> The AI may prepare accounting work, but it may never approve its own
> work — enforced at the database level, not just in application code.

Concretely: all four AI agents connect to Postgres as `datumai_ai_service`,
a role with no grant path to `approved`/`rejected`/`posted`/`reversed`
status values and no grant on `review_decisions` at all. Only
`datumai_cpa_service`, used exclusively by `app/api/routes_cpa_review.py`,
can write those. This is proven by `tests/security/`, which connects
directly to Postgres — bypassing the app entirely — and asserts the
forbidden writes fail with a database permission error.

## What's implemented

- **Data model** (`app/models/`): 16 tables — organizations, users, clients,
  chart of accounts, source documents, proposed journal entries, exceptions,
  review decisions, workflow runs, tool invocations, and an append-only
  audit log.
- **Security** (`alembic/versions/0002_security_roles_and_grants.py`):
  three Postgres roles (`datumai_admin`, `datumai_ai_service`,
  `datumai_cpa_service`), least-privilege grants, a trigger blocking the AI
  role from ever writing a terminal entry status, and a second trigger
  making `review_decisions`/`audit_events` unconditionally append-only.
- **Auth** (`app/core/security.py`, `app/api/deps.py`): JWT-based, with the
  authenticated role determining which Postgres-role-bound DB session a
  request gets — not just which actions the app *chooses* to allow.
- **Intake Bookkeeper Agent** (`app/agents/intake_bookkeeper/`): given an
  uploaded document (text, PDF, or image), extracts structured fields via a
  Claude Skill, classifies the expense against the client's actual chart of
  accounts via a second Claude Skill, deterministically validates
  debit=credit and account references, and proposes a journal entry
  directly in `pending_review` — with evidence links, a confidence score,
  duplicate-document detection, and exception flagging on low confidence.
- **CPA review** (`app/api/routes_cpa_review.py`): review queue, approve,
  reject, and request-revision endpoints — the only code path in the
  repository that can create a `ReviewDecision` or move an entry to a
  terminal status.
- **Tests** (`tests/`): 80+ tests across unit, integration, and security
  suites, all run against a real local Postgres instance (not mocked).

## What's NOT yet implemented (see the plan's roadmap)

Reconciliation & Close Agent, CPA Review Copilot, Reporting & Insights
Agent, QuickBooks Online integration, real email/document-storage
integration, n8n orchestration, MFA on CPA approval. These are follow-up
work, not silently assumed.

## Repository layout

```
app/
├── main.py                        # FastAPI app entrypoint
├── core/
│   ├── config.py                  # Settings (three DB URLs, JWT config, Claude config)
│   └── security.py                # JWT issuance/verification, password hashing
├── db/
│   ├── base.py                    # SQLAlchemy declarative Base
│   └── session.py                 # Three engines: admin, ai_service, cpa_service
├── models/                        # SQLAlchemy models (16 tables)
├── schemas/                       # Pydantic request/response DTOs
├── services/
│   ├── claude_client.py           # Generalized ClaudeSkillClient, used by every agent
│   ├── claude_service.py          # Legacy /classify endpoint, now built on ClaudeSkillClient
│   └── accounting/
│       ├── validation.py          # Deterministic debit=credit + GL account checks
│       └── entry_state_machine.py # Accounting Entry state machine (app-level enforcement layer)
├── agents/
│   └── intake_bookkeeper/         # Skills, tools, and orchestration for Agent 1
└── api/
    ├── deps.py                    # Auth dependencies: role-scoped DB sessions
    ├── routes.py                  # Legacy /health, /classify
    ├── routes_auth.py             # Human (CPA) login only
    ├── routes_agent_intake.py     # ai_intake-only: document upload + intake pipeline
    └── routes_cpa_review.py       # cpa-only: review queue, approve/reject/request-revision

alembic/versions/
├── 0001_initial_schema.py         # All 16 tables
└── 0002_security_roles_and_grants.py  # Postgres roles, grants, security triggers

scripts/seed_dev.py                # Bootstraps a dev org/client/COA + service-account tokens
tests/
├── unit/                          # Deterministic logic: validation, state machine
├── integration/                   # Full pipeline + CPA review flow, real DB, mocked Claude
└── security/                      # DB-grant, API-surface, and tool-schema proofs
```

## Requirements

- Python 3.11+
- PostgreSQL 16 (local, or via `docker compose up db`)
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com)) — optional for
  running tests (Claude calls are mocked) but required for real agent runs

## Setup (local, without Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY, and adjust DB URLs if not using the
# default local Postgres role/database names below

# One-time: create the datumai_admin role + datumai_dev/datumai_test databases
# on your local Postgres (adjust for your own Postgres superuser):
sudo -u postgres psql -c "CREATE ROLE datumai_admin WITH LOGIN PASSWORD 'datumai_admin_dev_pw' CREATEDB CREATEROLE;"
sudo -u postgres psql -c "CREATE DATABASE datumai_dev OWNER datumai_admin;"
sudo -u postgres psql -c "CREATE DATABASE datumai_test OWNER datumai_admin;"

# Apply migrations (creates all tables, the two application Postgres
# roles, grants, and security triggers)
alembic upgrade head

# Seed a dev organization, demo client, chart of accounts, CPA login, and
# AI agent service tokens (printed to stdout — dev only, never commit)
python -m scripts.seed_dev
```

## Setup (Docker)

```bash
docker compose up --build
# in another shell, once it's healthy:
docker compose exec app python -m scripts.seed_dev
```

## Run

```bash
uvicorn app.main:app --reload
```

API at `http://localhost:8000`, interactive docs at `http://localhost:8000/docs`.

## Tests

```bash
pytest tests/ -v
```

This runs against a real `datumai_test` Postgres database (migrated
automatically by the test suite's session fixture) — nothing is mocked
except the Claude API calls themselves. The security suite
(`tests/security/`) is the most important one to keep green: it directly
verifies, at the Postgres connection level, that the AI service role can
never approve its own work.

## API surface

| Route | Auth | Purpose |
|---|---|---|
| `GET /api/v1/health` | none | Liveness check |
| `POST /api/v1/classify` | none *(legacy, flagged for auth hardening)* | Ad-hoc transaction classification |
| `POST /api/v1/auth/login` | none | Human (CPA) login only — service accounts never use this |
| `POST /api/v1/agent/intake/documents` | `role=ai_intake` | Upload a document, run the Intake Bookkeeper pipeline |
| `GET /api/v1/cpa/review-queue` | `role=cpa` | List pending-review entries with evidence and exceptions |
| `POST /api/v1/cpa/entries/{id}/approve` | `role=cpa` | Approve an entry (writes an immutable ReviewDecision) |
| `POST /api/v1/cpa/entries/{id}/reject` | `role=cpa` | Reject an entry |
| `POST /api/v1/cpa/entries/{id}/request-revision` | `role=cpa` | Send an entry back to the Intake Bookkeeper |

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required for real agent runs)* | Your Anthropic API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Model used by every Skill |
| `CLAUDE_MAX_TOKENS` | `1024` | Max tokens per Claude call |
| `ADMIN_DATABASE_URL` | *(see .env.example)* | Schema-owner connection, migrations/seed script only |
| `AI_SERVICE_DATABASE_URL` | *(see .env.example)* | Used by all four agent routes |
| `CPA_SERVICE_DATABASE_URL` | *(see .env.example)* | Used only by CPA-facing routes |
| `JWT_SECRET_KEY` | *(must override outside dev)* | JWT signing secret |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | `60` | Human (CPA) session token lifetime |
| `CORS_ALLOW_ORIGINS` | `*` | Comma-separated allowed origins, or `*` |

## Known MVP simplifications (documented, not hidden)

- The Intake Bookkeeper books every proposed entry as debit `<classified
  expense account>` / credit a fixed "Operating Cash" GL account (code
  `1000`). Determining the correct credit side in general (cash vs. credit
  card vs. accounts payable) is Reconciliation & Close Agent territory,
  not yet built.
- All four agent roles share one Postgres role (`datumai_ai_service`)
  rather than one role each — the plan's stated future-work item once more
  agents exist; the important boundary (AI vs. CPA) is already enforced.
- MFA on CPA approval is not implemented — flagged in the plan as a Phase 2
  requirement before any pilot with real client financials.
- `/api/v1/classify` (the original endpoint) has no auth in front of it —
  pre-existing from the original scaffold, flagged rather than silently
  left as-is.

See `DATUM_AI_BOOKKEEPING_TEAM_PLAN.md` for the full architecture, the
complete data model, the exception taxonomy, the security threat model, and
the phased roadmap.

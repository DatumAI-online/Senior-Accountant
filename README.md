# Datum AI — CPA-Supervised Bookkeeping Team

A modular-monolith FastAPI backend for a CPA-supervised AI bookkeeping
product. This repository started as a single-endpoint "Skill Brain" proof
of concept (Claude-based transaction classification) and now implements
the full Phase 1 demonstration loop from `DATUM_AI_BOOKKEEPING_TEAM_PLAN.md`
— all four AI agents plus the human CPA review/approval surface — which is
the canonical design document for this system. Read that first for the
full architecture, data model, and roadmap; this README covers setup and
what's actually running today.

## The core control, in one sentence

> The AI may prepare accounting work, but it may never approve its own
> work — enforced at the database level, not just in application code.

Concretely: all four AI agents connect to Postgres as `datumai_ai_service`,
a role with no grant path to `approved`/`rejected`/`posted`/`reversed`
entry status, no grant path to `approved`/`delivered` close status, no
`UPDATE` grant at all on `financial_reports`/`executive_summaries`, and no
grant on `review_decisions` at all. Only `datumai_cpa_service`, used
exclusively by `app/api/routes_cpa_review.py`, can write those. This is
proven by `tests/security/`, which connects directly to Postgres —
bypassing the app entirely — and asserts the forbidden writes fail with a
database permission error.

## What's implemented

**The full Phase 1 demonstration loop** (see
`tests/integration/test_full_demo_loop.py` for the loop run end to end):
a client uploads a document, the Intake Bookkeeper proposes an entry, the
Reconciliation & Close Agent reconciles the account and gates close
readiness, the CPA Review Copilot drafts a recommendation, a human CPA
approves the entry and the close, the Reporting & Insights Agent generates
statements and an executive summary, and the CPA approves the client
deliverable.

- **Data model** (`app/models/`): 25 tables — organizations, users,
  clients, chart of accounts, source documents, proposed journal entries,
  financial accounts, imported transactions, reconciliations, exceptions,
  client questions, financial reports, executive summaries, recommended
  actions, review decisions, workflow runs, tool invocations, and an
  append-only audit log.
- **Security** (`alembic/versions/0002_*.py`, `0004_*.py`): three Postgres
  roles (`datumai_admin`, `datumai_ai_service`, `datumai_cpa_service`),
  least-privilege grants, triggers blocking the AI role from ever writing
  a terminal entry status *or* a terminal close status, and a third
  trigger making `review_decisions`/`audit_events` unconditionally
  append-only.
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
- **Reconciliation & Close Agent** (`app/agents/reconciliation_close/`):
  deterministic (no Claude call) transaction matching between imported
  bank/CC feeds and proposed entries, balance aggregation, and a
  close-readiness checklist that gates `AccountingPeriod.close_status`
  through to `ready_for_cpa_review` — or flags unmatched transactions and
  reconciliation differences as exceptions instead.
- **CPA Review Copilot** (`app/agents/cpa_review_copilot/`): prioritizes
  the review queue (deterministic scoring by exception severity and
  confidence), computes historical-treatment statistics from past
  `ReviewDecision`s (deterministic), and drafts a Claude recommendation —
  `approve`/`reject`/`revise`/`escalate` — that is advisory text only; no
  tool in this agent's surface can execute any of those actions.
- **Reporting & Insights Agent** (`app/agents/reporting_insights/`):
  deterministic income statement / balance sheet / cash summary generation
  and period-over-period variance calculation, filtered to
  `approved`/`posted` entries only at the SQL level — then a Claude-drafted
  executive summary and action items that may only reference the numbers
  it was given. Refuses to run until the CPA has approved the period's
  close.
- **CPA review & approval** (`app/api/routes_cpa_review.py`): review queue,
  entry approve/reject/request-revision, period-level close approval
  (`start-review` → `approve-close`), and deliverable approval
  (`approve-deliverable`, which sets `FinancialReport.approved_by` /
  `ExecutiveSummary.approved_by` and moves the period to `delivered`) — the
  only file in the repository that can write a `ReviewDecision` or move any
  entity into a terminal state.
- **Tests** (`tests/`): 110+ tests across unit, integration, and security
  suites, all run against a real local Postgres instance (not mocked) —
  including the full 8-step demo loop over real HTTP with mocked Claude
  calls.

## What's NOT yet implemented (see the plan's roadmap)

QuickBooks Online integration, real email/document-storage integration
(client questions currently stay in-app), n8n orchestration, MFA on CPA
approval, multiple concurrent CPA reviewers. These are Phase 2+ per the
plan, not silently assumed.

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
├── models/                        # SQLAlchemy models (25 tables)
├── schemas/                       # Pydantic request/response DTOs
├── services/
│   ├── claude_client.py           # Generalized ClaudeSkillClient, used by every agent
│   ├── claude_service.py          # Legacy /classify endpoint, now built on ClaudeSkillClient
│   └── accounting/
│       ├── validation.py              # Deterministic debit=credit + GL account checks
│       ├── entry_state_machine.py     # Accounting Entry state machine (app-level layer)
│       └── close_state_machine.py     # Monthly Close state machine (app-level layer)
├── agents/
│   ├── common/                    # Shared tool helpers: exceptions, audit log, tool-invocation log
│   ├── intake_bookkeeper/         # Agent 1: document -> proposed entry
│   ├── reconciliation_close/      # Agent 2: bank/CC reconciliation + close checklist
│   ├── cpa_review_copilot/        # Agent 3: prioritization + advisory recommendation
│   └── reporting_insights/        # Agent 4: statements + variance + executive summary
└── api/
    ├── deps.py                        # Auth dependencies: role-scoped DB sessions
    ├── routes.py                      # Legacy /health, /classify
    ├── routes_auth.py                 # Human (CPA) login only
    ├── routes_agent_intake.py         # ai_intake-only
    ├── routes_agent_reconciliation.py # ai_reconciliation-only
    ├── routes_agent_copilot.py        # ai_copilot-only
    ├── routes_agent_reporting.py      # ai_reporting-only
    └── routes_cpa_review.py           # cpa-only: the entire approval surface

alembic/versions/
├── 0001_initial_schema.py             # Core tables (Phase 0)
├── 0002_security_roles_and_grants.py  # Postgres roles, grants, entry-status trigger
├── 0003_reconciliation_and_reporting_tables.py  # Phase 1 tables
├── 0004_reconciliation_reporting_grants.py      # Grants + close-status trigger
└── 0005_add_entry_date_to_proposed_journal_entries.py  # Business date for reconciliation matching

scripts/seed_dev.py                # Bootstraps a dev org/client/COA + service-account tokens
tests/
├── unit/                          # Deterministic logic: validation, both state machines, recon math
├── integration/                   # Per-agent flows + the full 8-step demo loop, real DB, mocked Claude
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
never approve its own work. `tests/integration/test_full_demo_loop.py` is
the single test that proves the whole pipeline holds together end to end.

## API surface

| Route | Auth | Purpose |
|---|---|---|
| `GET /api/v1/health` | none | Liveness check |
| `POST /api/v1/classify` | none *(legacy, flagged for auth hardening)* | Ad-hoc transaction classification |
| `POST /api/v1/auth/login` | none | Human (CPA) login only — service accounts never use this |
| `POST /api/v1/agent/intake/documents` | `role=ai_intake` | Upload a document, run the Intake Bookkeeper pipeline |
| `POST /api/v1/agent/reconciliation/transactions/import` | `role=ai_reconciliation` | Import a bank/CC transaction CSV |
| `POST /api/v1/agent/reconciliation/run` | `role=ai_reconciliation` | Reconcile all active accounts for a client/period, gate close readiness |
| `GET /api/v1/agent/copilot/recommendations` | `role=ai_copilot` | Prioritized review queue + advisory recommendations |
| `POST /api/v1/agent/reporting/generate` | `role=ai_reporting` | Generate statements + executive summary (requires close already approved) |
| `GET /api/v1/cpa/review-queue` | `role=cpa` | List pending-review entries with evidence and exceptions |
| `POST /api/v1/cpa/entries/{id}/approve` | `role=cpa` | Approve an entry (writes an immutable ReviewDecision) |
| `POST /api/v1/cpa/entries/{id}/reject` | `role=cpa` | Reject an entry |
| `POST /api/v1/cpa/entries/{id}/request-revision` | `role=cpa` | Send an entry back to the Intake Bookkeeper |
| `POST /api/v1/cpa/periods/{id}/start-review` | `role=cpa` | Open the review queue for a period |
| `POST /api/v1/cpa/periods/{id}/approve-close` | `role=cpa` | Approve the monthly close as a whole |
| `POST /api/v1/cpa/periods/{id}/approve-deliverable` | `role=cpa` | Approve statements + summary for client delivery |

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
  card vs. accounts payable) is flagged as follow-up work.
- All four agent roles share one Postgres role (`datumai_ai_service`)
  rather than one role each — the plan's stated future-work item once more
  agents exist; the important boundary (AI vs. CPA) is already enforced.
- Reconciliation matching is one deterministic rule (exact amount + date
  within a ±3-day window), not fuzzy matching — sufficient for the demo,
  documented as narrow.
- Client questions (`ClientQuestion` model) exist in the data model and
  state machine but have no agent wired up to draft them yet, and no
  outbound email — they'd currently only ever be created manually.
- MFA on CPA approval is not implemented — flagged in the plan as a Phase 2
  requirement before any pilot with real client financials.
- `/api/v1/classify` (the original endpoint) has no auth in front of it —
  pre-existing from the original scaffold, flagged rather than silently
  left as-is.

See `DATUM_AI_BOOKKEEPING_TEAM_PLAN.md` for the full architecture, the
complete data model, the exception taxonomy, the security threat model, and
the phased roadmap.

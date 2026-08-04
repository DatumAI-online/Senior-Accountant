"""security roles, grants, and immutability triggers

This migration is the database-level enforcement of the core control
principle in DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 10: "the AI may
prepare accounting work, but it may never approve its own work." Everything
here is verified directly (bypassing the application entirely) by
tests/security/test_db_grants.py.

Two application-facing Postgres roles are created:
  - datumai_ai_service  — used by all four AI agents (app.db.session.get_ai_db)
  - datumai_cpa_service — used only by CPA-facing endpoints (get_cpa_db)

Neither role is ever granted DELETE on anything. A trigger on
proposed_journal_entries additionally blocks datumai_ai_service from ever
writing status='approved'/'rejected'/'posted'/'reversed', regardless of
what any application bug or prompt-injected model output might attempt —
this is enforced independently of the table-level GRANT, which datumai_
ai_service does hold (it legitimately needs UPDATE for its own allowed
transitions like draft -> pending_review). review_decisions and
audit_events are made unconditionally append-only via a second trigger
that rejects UPDATE/DELETE from any role, including the schema owner,
short of a deliberate DROP TRIGGER by a superuser.

Passwords below are development defaults matching app/core/config.py's
defaults. In any real environment these must be generated secrets injected
via the deployment's secrets manager, never committed — see Section 10.1's
"Secrets management" note and Section 11's outstanding-review flag.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AI_SERVICE_ROLE = "datumai_ai_service"
CPA_SERVICE_ROLE = "datumai_cpa_service"

# Dev-only defaults — must match Settings.ai_service_database_url /
# Settings.cpa_service_database_url in app/core/config.py.
AI_SERVICE_PASSWORD = "datumai_ai_service_dev_pw"
CPA_SERVICE_PASSWORD = "datumai_cpa_service_dev_pw"

# Tables both service roles may at least SELECT (reference/context data).
READ_ONLY_REFERENCE_TABLES = [
    "organizations",
    "clients",
    "users",
    "engagements",
    "accounting_periods",
    "gl_accounts",
]

# Tables AI agents actively read and write while preparing work, but can
# never move into an approval/terminal state.
AI_READ_WRITE_TABLES = [
    "source_documents",
    "extracted_document_data",
    "exception_records",
    "workflow_runs",
    "tool_invocations",
]


def upgrade() -> None:
    _create_roles()
    _grant_connect_and_schema_usage()
    _grant_reference_table_reads()
    _grant_ai_service_workspace()
    _grant_cpa_service_workspace()
    _grant_append_only_tables()
    _create_entry_approval_guard_trigger()
    _create_immutability_triggers()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;")
    op.execute("DROP TRIGGER IF EXISTS trg_review_decisions_append_only ON review_decisions;")
    op.execute("DROP FUNCTION IF EXISTS prevent_mutation();")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_entry_status_approval_guard ON proposed_journal_entries;"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_entry_status_transition();")
    op.execute(f"REASSIGN OWNED BY {AI_SERVICE_ROLE} TO datumai_admin;")
    op.execute(f"REASSIGN OWNED BY {CPA_SERVICE_ROLE} TO datumai_admin;")
    op.execute(f"DROP OWNED BY {AI_SERVICE_ROLE};")
    op.execute(f"DROP OWNED BY {CPA_SERVICE_ROLE};")
    op.execute(f"DROP ROLE IF EXISTS {AI_SERVICE_ROLE};")
    op.execute(f"DROP ROLE IF EXISTS {CPA_SERVICE_ROLE};")


def _create_roles() -> None:
    for role, password in (
        (AI_SERVICE_ROLE, AI_SERVICE_PASSWORD),
        (CPA_SERVICE_ROLE, CPA_SERVICE_PASSWORD),
    ):
        op.execute(
            f"""
            DO $$
            BEGIN
               IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                  CREATE ROLE {role} WITH LOGIN PASSWORD '{password}'
                      NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
               END IF;
            END
            $$;
            """
        )


def _grant_connect_and_schema_usage() -> None:
    for role in (AI_SERVICE_ROLE, CPA_SERVICE_ROLE):
        op.execute(f"GRANT CONNECT ON DATABASE datumai_dev TO {role};")
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role};")


def _grant_reference_table_reads() -> None:
    for table in READ_ONLY_REFERENCE_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {AI_SERVICE_ROLE}, {CPA_SERVICE_ROLE};")


def _grant_ai_service_workspace() -> None:
    for table in AI_READ_WRITE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {AI_SERVICE_ROLE};")

    # client_accounting_profiles: read-only for AI. Policy changes are a
    # CPA-only write path (Section 13's "hard rule").
    op.execute(f"GRANT SELECT ON client_accounting_profiles TO {AI_SERVICE_ROLE};")

    # proposed_journal_entries / journal_entry_lines: AI proposes (INSERT)
    # and may update its OWN non-terminal fields on an entry (UPDATE is
    # granted at the table level; the trigger below is what actually
    # blocks it from ever writing a terminal status value). Lines are
    # write-once from the AI's perspective — no UPDATE grant, so a
    # revision means a new ProposedJournalEntry, not a mutated line.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON proposed_journal_entries TO {AI_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT, INSERT ON journal_entry_lines TO {AI_SERVICE_ROLE};")

    # review_decisions: READ-ONLY. The CPA Review Copilot's
    # compare_to_historical_treatment tool needs to read past decisions;
    # no AI credential may ever create one. No UPDATE/DELETE grant exists
    # for ANY role on this table (see _create_immutability_triggers).
    op.execute(f"GRANT SELECT ON review_decisions TO {AI_SERVICE_ROLE};")


def _grant_cpa_service_workspace() -> None:
    # CPA-facing endpoints can read everything AI can, plus:
    op.execute(f"GRANT SELECT ON client_accounting_profiles TO {CPA_SERVICE_ROLE};")
    op.execute(f"GRANT UPDATE ON client_accounting_profiles TO {CPA_SERVICE_ROLE};")
    for table in AI_READ_WRITE_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {CPA_SERVICE_ROLE};")

    # The CPA role is the only one permitted to move an entry into a
    # terminal state — allowed at the GRANT level and unrestricted by the
    # entry-status trigger (which only ever blocks datumai_ai_service).
    op.execute(f"GRANT SELECT, UPDATE ON proposed_journal_entries TO {CPA_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT ON journal_entry_lines TO {CPA_SERVICE_ROLE};")

    # Only the CPA role may create a ReviewDecision. No UPDATE/DELETE grant
    # exists for this table at all, for any role (append-only trigger).
    op.execute(f"GRANT SELECT, INSERT ON review_decisions TO {CPA_SERVICE_ROLE};")


def _grant_append_only_tables() -> None:
    # audit_events: both roles may append and read; neither may ever
    # UPDATE or DELETE (no such grant is issued, and the immutability
    # trigger blocks it unconditionally regardless of grants).
    op.execute(f"GRANT SELECT, INSERT ON audit_events TO {AI_SERVICE_ROLE}, {CPA_SERVICE_ROLE};")


def _create_entry_approval_guard_trigger() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_entry_status_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF session_user = 'datumai_ai_service'
               AND NEW.status IN ('approved', 'rejected', 'posted', 'reversed') THEN
                RAISE EXCEPTION
                    'datumai_ai_service may not set proposed_journal_entries.status to %. '
                    'Only datumai_cpa_service may perform this transition.', NEW.status
                    USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_entry_status_approval_guard
        BEFORE INSERT OR UPDATE ON proposed_journal_entries
        FOR EACH ROW
        EXECUTE FUNCTION enforce_entry_status_transition();
        """
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION enforce_entry_status_transition() "
        f"TO {AI_SERVICE_ROLE}, {CPA_SERVICE_ROLE};"
    )


def _create_immutability_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is not permitted on this table',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = '42501';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_review_decisions_append_only
        BEFORE UPDATE OR DELETE ON review_decisions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW
        EXECUTE FUNCTION prevent_mutation();
        """
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION prevent_mutation() TO {AI_SERVICE_ROLE}, {CPA_SERVICE_ROLE};"
    )

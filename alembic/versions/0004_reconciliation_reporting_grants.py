"""grants for reconciliation/reporting tables + close-status approval guard

Extends the Section 10 control to two more surfaces now that the
Reconciliation & Close Agent and Reporting & Insights Agent exist:

  - accounting_periods.close_status gets the same treatment as
    proposed_journal_entries.status in 0002: datumai_ai_service gets a
    table-level UPDATE grant (it legitimately drives most close-status
    transitions), but a trigger blocks it from ever writing 'approved' or
    'delivered' — only datumai_cpa_service can do that.
  - financial_reports / executive_summaries: datumai_ai_service can
    INSERT+SELECT (draft) but has no UPDATE grant at all, so it structurally
    cannot set approved_by. Only datumai_cpa_service can.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AI_SERVICE_ROLE = "datumai_ai_service"
CPA_SERVICE_ROLE = "datumai_cpa_service"

# Tables the Reconciliation & Close Agent actively reads and writes, but
# which never carry an approval decision themselves.
AI_RECON_READ_WRITE_TABLES = [
    "financial_accounts",
    "imported_transactions",
    "transaction_matches",
    "reconciliations",
    "reconciliation_items",
]


def upgrade() -> None:
    for table in AI_RECON_READ_WRITE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {AI_SERVICE_ROLE};")
        op.execute(f"GRANT SELECT ON {table} TO {CPA_SERVICE_ROLE};")

    # client_questions: AI drafts and can move itself between non-approval
    # states; CPA approves wording (approved_for_sending) and can always
    # read/update. This table intentionally does NOT get the DB-trigger
    # treatment — it's not an accounting decision, so the state machine
    # enforcement in app/services/accounting is considered sufficient here.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON client_questions TO {AI_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT, UPDATE ON client_questions TO {CPA_SERVICE_ROLE};")

    # financial_reports / executive_summaries / recommended_actions: AI
    # drafts (INSERT), nobody but CPA can approve (UPDATE to set
    # approved_by) — enforced by simply not granting AI service UPDATE at
    # all on the two tables that carry an approved_by column.
    op.execute(f"GRANT SELECT, INSERT ON financial_reports TO {AI_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT, UPDATE ON financial_reports TO {CPA_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT, INSERT ON executive_summaries TO {AI_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT, UPDATE ON executive_summaries TO {CPA_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT, INSERT ON recommended_actions TO {AI_SERVICE_ROLE};")
    op.execute(f"GRANT SELECT ON recommended_actions TO {CPA_SERVICE_ROLE};")

    # accounting_periods.close_status: same defense-in-depth pattern as
    # proposed_journal_entries.status. AI legitimately drives most close
    # transitions; only CPA may ever write 'approved' or 'delivered'.
    op.execute(f"GRANT UPDATE ON accounting_periods TO {AI_SERVICE_ROLE};")
    op.execute(f"GRANT UPDATE ON accounting_periods TO {CPA_SERVICE_ROLE};")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_close_status_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF session_user = 'datumai_ai_service'
               AND NEW.close_status IN ('approved', 'delivered') THEN
                RAISE EXCEPTION
                    'datumai_ai_service may not set accounting_periods.close_status to %. '
                    'Only datumai_cpa_service may perform this transition.', NEW.close_status
                    USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_close_status_approval_guard
        BEFORE INSERT OR UPDATE ON accounting_periods
        FOR EACH ROW
        EXECUTE FUNCTION enforce_close_status_transition();
        """
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION enforce_close_status_transition() "
        f"TO {AI_SERVICE_ROLE}, {CPA_SERVICE_ROLE};"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_close_status_approval_guard ON accounting_periods;")
    op.execute("DROP FUNCTION IF EXISTS enforce_close_status_transition();")
    for table in AI_RECON_READ_WRITE_TABLES + [
        "client_questions",
        "financial_reports",
        "executive_summaries",
        "recommended_actions",
    ]:
        op.execute(f"REVOKE ALL ON {table} FROM {AI_SERVICE_ROLE};")
        op.execute(f"REVOKE ALL ON {table} FROM {CPA_SERVICE_ROLE};")
    op.execute(f"REVOKE UPDATE ON accounting_periods FROM {AI_SERVICE_ROLE};")
    op.execute(f"REVOKE UPDATE ON accounting_periods FROM {CPA_SERVICE_ROLE};")

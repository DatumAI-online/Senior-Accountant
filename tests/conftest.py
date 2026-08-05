"""
Shared pytest fixtures. Env vars are pointed at datumai_test BEFORE any
`app.*` module is imported anywhere in the test session — app/db/session.py
creates its SQLAlchemy engines at import time, so this has to happen here,
at conftest module-import time, not inside a fixture function.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

os.environ["ADMIN_DATABASE_URL"] = (
    "postgresql+psycopg2://datumai_admin:datumai_admin_dev_pw@localhost:5432/datumai_test"
)
os.environ["AI_SERVICE_DATABASE_URL"] = (
    "postgresql+psycopg2://datumai_ai_service:datumai_ai_service_dev_pw@localhost:5432/datumai_test"
)
os.environ["CPA_SERVICE_DATABASE_URL"] = (
    "postgresql+psycopg2://datumai_cpa_service:datumai_cpa_service_dev_pw@localhost:5432/datumai_test"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-do-not-use-in-prod")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

APP_TABLES = [
    "audit_events",
    "tool_invocations",
    "workflow_runs",
    "review_decisions",
    "recommended_actions",
    "executive_summaries",
    "financial_reports",
    "client_questions",
    "reconciliation_items",
    "reconciliations",
    "transaction_matches",
    "imported_transactions",
    "financial_accounts",
    "exception_records",
    "journal_entry_lines",
    "proposed_journal_entries",
    "extracted_document_data",
    "source_documents",
    "gl_accounts",
    "accounting_periods",
    "engagements",
    "client_accounting_profiles",
    "clients",
    "users",
    "organizations",
]


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db():
    """Run Alembic against datumai_test once per test session, as a
    subprocess so it always reflects the just-set env vars regardless of
    any caching in this process."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        check=True,
        env=os.environ.copy(),
        capture_output=True,
    )
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    from app.db.session import AdminSessionLocal

    db = AdminSessionLocal()
    try:
        db.execute(text(f"TRUNCATE {', '.join(APP_TABLES)} RESTART IDENTITY CASCADE"))
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def admin_db():
    from app.db.session import AdminSessionLocal

    db = AdminSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def ai_db():
    from app.db.session import AiServiceSessionLocal

    db = AiServiceSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def cpa_db():
    from app.db.session import CpaServiceSessionLocal

    db = CpaServiceSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_client(admin_db):
    """Creates one organization, one demo client with a starter chart of
    accounts, one CPA user, and one AI-intake service-account user. Returns
    a dict of the created rows keyed by role, for tests to use directly."""
    from app.models.accounting_period import AccountingPeriod, GLAccount
    from app.models.accounting_profile import ClientAccountingProfile, Engagement
    from app.models.enums import CloseStatus, FinancialAccountType, GLAccountType, UserRole
    from app.models.organization import Client, Organization
    from app.models.reconciliation import FinancialAccount
    from app.models.user import User

    org = Organization(name="Test Org")
    admin_db.add(org)
    admin_db.flush()

    cpa_user = User(
        organization_id=org.id, email="cpa@test.local", full_name="Test CPA", role=UserRole.CPA
    )
    intake_user = User(
        organization_id=org.id,
        email="agent-intake@test.local",
        full_name="Intake Agent",
        role=UserRole.AI_INTAKE,
        is_service_account=True,
    )
    reconciliation_user = User(
        organization_id=org.id,
        email="agent-reconciliation@test.local",
        full_name="Reconciliation Agent",
        role=UserRole.AI_RECONCILIATION,
        is_service_account=True,
    )
    copilot_user = User(
        organization_id=org.id,
        email="agent-copilot@test.local",
        full_name="Copilot Agent",
        role=UserRole.AI_COPILOT,
        is_service_account=True,
    )
    reporting_user = User(
        organization_id=org.id,
        email="agent-reporting@test.local",
        full_name="Reporting Agent",
        role=UserRole.AI_REPORTING,
        is_service_account=True,
    )
    admin_db.add_all([cpa_user, intake_user, reconciliation_user, copilot_user, reporting_user])
    admin_db.flush()

    client = Client(organization_id=org.id, legal_name="Test Client LLC", entity_type="LLC")
    admin_db.add(client)
    admin_db.flush()

    admin_db.add(
        ClientAccountingProfile(client_id=client.id, industry="Consulting", materiality_threshold=500)
    )

    engagement = Engagement(client_id=client.id)
    admin_db.add(engagement)
    admin_db.flush()

    period = AccountingPeriod(
        engagement_id=engagement.id, period="2026-07", close_status=CloseStatus.COLLECTING_DOCUMENTS
    )
    admin_db.add(period)

    gl_accounts = {}
    for code, name, account_type in [
        ("1000", "Operating Cash", GLAccountType.ASSET),
        ("4000", "Service Revenue", GLAccountType.REVENUE),
        ("6100", "Software and Subscriptions", GLAccountType.EXPENSE),
        ("6300", "Contract Labor", GLAccountType.EXPENSE),
    ]:
        acct = GLAccount(client_id=client.id, code=code, name=name, account_type=account_type)
        admin_db.add(acct)
        admin_db.flush()
        gl_accounts[code] = acct

    financial_account = FinancialAccount(
        client_id=client.id,
        gl_account_id=gl_accounts["1000"].id,
        account_type=FinancialAccountType.BANK,
        institution="Test Bank",
        mask="4242",
    )
    admin_db.add(financial_account)

    admin_db.commit()

    return {
        "org": org,
        "client": client,
        "engagement": engagement,
        "period": period,
        "gl_accounts": gl_accounts,
        "financial_account": financial_account,
        "cpa_user": cpa_user,
        "intake_user": intake_user,
        "reconciliation_user": reconciliation_user,
        "copilot_user": copilot_user,
        "reporting_user": reporting_user,
    }


@pytest.fixture
def intake_token(seeded_client):
    from app.core.security import create_access_token

    user = seeded_client["intake_user"]
    return create_access_token(
        user_id=user.id, email=user.email, role=user.role, is_service_account=True
    )


@pytest.fixture
def cpa_token(seeded_client):
    from app.core.security import create_access_token

    user = seeded_client["cpa_user"]
    return create_access_token(
        user_id=user.id, email=user.email, role=user.role, is_service_account=False
    )


@pytest.fixture
def reconciliation_token(seeded_client):
    from app.core.security import create_access_token

    user = seeded_client["reconciliation_user"]
    return create_access_token(
        user_id=user.id, email=user.email, role=user.role, is_service_account=True
    )


@pytest.fixture
def copilot_token(seeded_client):
    from app.core.security import create_access_token

    user = seeded_client["copilot_user"]
    return create_access_token(
        user_id=user.id, email=user.email, role=user.role, is_service_account=True
    )


@pytest.fixture
def reporting_token(seeded_client):
    from app.core.security import create_access_token

    user = seeded_client["reporting_user"]
    return create_access_token(
        user_id=user.id, email=user.email, role=user.role, is_service_account=True
    )


@pytest.fixture
def api_client():
    from app.main import app

    return TestClient(app)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()

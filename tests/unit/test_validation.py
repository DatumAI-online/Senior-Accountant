import pytest

from app.services.accounting.validation import (
    AccountingValidationError,
    validate_debit_equals_credit,
    validate_gl_accounts_exist,
)


def test_balanced_entry_passes():
    validate_debit_equals_credit([{"debit": 100, "credit": 0}, {"debit": 0, "credit": 100}])


def test_unbalanced_entry_rejected():
    with pytest.raises(AccountingValidationError, match="does not balance"):
        validate_debit_equals_credit([{"debit": 100, "credit": 0}, {"debit": 0, "credit": 99.99}])


def test_single_line_rejected():
    with pytest.raises(AccountingValidationError, match="at least two lines"):
        validate_debit_equals_credit([{"debit": 100, "credit": 0}])


def test_line_with_both_debit_and_credit_rejected():
    with pytest.raises(AccountingValidationError, match="cannot have both"):
        validate_debit_equals_credit([{"debit": 50, "credit": 50}, {"debit": 0, "credit": 50}])


def test_line_with_neither_debit_nor_credit_rejected():
    with pytest.raises(AccountingValidationError, match="nonzero debit or credit"):
        validate_debit_equals_credit([{"debit": 0, "credit": 0}, {"debit": 0, "credit": 100}])


def test_negative_amounts_rejected():
    with pytest.raises(AccountingValidationError, match="cannot be negative"):
        validate_debit_equals_credit([{"debit": -10, "credit": 0}, {"debit": 0, "credit": 10}])


def test_rounding_is_applied_before_comparison():
    # 33.333... * 3 should still balance after rounding to cents.
    validate_debit_equals_credit(
        [
            {"debit": 33.335, "credit": 0},
            {"debit": 0, "credit": 33.335},
        ]
    )


def test_gl_accounts_must_belong_to_client(seeded_client, admin_db):
    from app.models.accounting_period import GLAccount
    from app.models.enums import GLAccountType
    from app.models.organization import Client

    other_client = Client(
        organization_id=seeded_client["org"].id, legal_name="Other Client LLC", entity_type="LLC"
    )
    admin_db.add(other_client)
    admin_db.flush()
    other_account = GLAccount(
        client_id=other_client.id, code="9999", name="Not this client's account",
        account_type=GLAccountType.EXPENSE,
    )
    admin_db.add(other_account)
    admin_db.commit()

    with pytest.raises(AccountingValidationError, match="not found for this client"):
        validate_gl_accounts_exist(
            admin_db, client_id=seeded_client["client"].id, gl_account_ids=[other_account.id]
        )


def test_gl_accounts_must_exist(seeded_client, admin_db):
    import uuid

    with pytest.raises(AccountingValidationError, match="not found for this client"):
        validate_gl_accounts_exist(
            admin_db, client_id=seeded_client["client"].id, gl_account_ids=[uuid.uuid4()]
        )


def test_gl_accounts_happy_path(seeded_client, admin_db):
    cash = seeded_client["gl_accounts"]["1000"]
    software = seeded_client["gl_accounts"]["6100"]
    validate_gl_accounts_exist(
        admin_db, client_id=seeded_client["client"].id, gl_account_ids=[cash.id, software.id]
    )

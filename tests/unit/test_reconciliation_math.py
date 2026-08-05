from decimal import Decimal

import pytest

from app.agents.reconciliation_close.tools import CsvParseError, parse_transaction_csv
from app.agents.reporting_insights.tools import compute_variance


def test_parse_transaction_csv_happy_path():
    csv_text = "date,amount,description,reference\n2026-07-03,-24.00,NOTION LABS,ref123\n"
    rows = parse_transaction_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["amount"] == Decimal("-24.00")
    assert rows[0]["description"] == "NOTION LABS"
    assert rows[0]["reference"] == "ref123"


def test_parse_transaction_csv_missing_reference_is_optional():
    csv_text = "date,amount,description\n2026-07-03,-24.00,NOTION LABS\n"
    rows = parse_transaction_csv(csv_text)
    assert rows[0]["reference"] is None


def test_parse_transaction_csv_missing_required_column_rejected():
    with pytest.raises(CsvParseError, match="must have columns"):
        parse_transaction_csv("date,description\n2026-07-03,NOTION LABS\n")


def test_parse_transaction_csv_bad_date_rejected():
    with pytest.raises(CsvParseError, match="could not parse"):
        parse_transaction_csv("date,amount,description\nnot-a-date,-24.00,NOTION LABS\n")


def test_parse_transaction_csv_bad_amount_rejected():
    with pytest.raises(CsvParseError, match="could not parse"):
        parse_transaction_csv("date,amount,description\n2026-07-03,not-a-number,NOTION LABS\n")


def test_compute_variance_no_prior_period():
    result = compute_variance(current={"net_income": 100}, prior=None, materiality_threshold=Decimal("50"))
    assert result["has_prior_period"] is False
    assert result["line_deltas"] == []


def test_compute_variance_flags_material_changes():
    current = {"revenue": {"Service Revenue": 10000}, "expenses": {}, "net_income": 8000}
    prior = {"revenue": {"Service Revenue": 5000}, "expenses": {}, "net_income": 3000}
    result = compute_variance(current=current, prior=prior, materiality_threshold=Decimal("500"))
    assert result["has_prior_period"] is True
    assert "Service Revenue" in result["material_flags"]
    assert result["net_income_delta"] == 5000


def test_compute_variance_ignores_immaterial_changes():
    current = {"revenue": {"Service Revenue": 10010}, "expenses": {}, "net_income": 10010}
    prior = {"revenue": {"Service Revenue": 10000}, "expenses": {}, "net_income": 10000}
    result = compute_variance(current=current, prior=prior, materiality_threshold=Decimal("500"))
    assert result["material_flags"] == []

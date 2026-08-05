import pytest

from app.models.enums import CloseStatus, UserRole
from app.services.accounting.close_state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidCloseTransition,
    assert_close_transition_allowed,
    is_ai_reachable_terminal_close_state,
)


def test_reconciliation_agent_can_advance_to_ready_for_review():
    assert_close_transition_allowed(
        from_status=CloseStatus.RECONCILING,
        to_status=CloseStatus.READY_FOR_CPA_REVIEW,
        actor_role=UserRole.AI_RECONCILIATION,
    )


@pytest.mark.parametrize("terminal", [CloseStatus.APPROVED, CloseStatus.DELIVERED])
def test_no_ai_role_can_ever_reach_a_terminal_close_state(terminal):
    for role in (
        UserRole.AI_INTAKE,
        UserRole.AI_RECONCILIATION,
        UserRole.AI_COPILOT,
        UserRole.AI_REPORTING,
    ):
        for from_status in CloseStatus:
            with pytest.raises(InvalidCloseTransition):
                assert_close_transition_allowed(
                    from_status=from_status, to_status=terminal, actor_role=role
                )


def test_cpa_can_approve_close():
    assert_close_transition_allowed(
        from_status=CloseStatus.UNDER_CPA_REVIEW, to_status=CloseStatus.APPROVED, actor_role=UserRole.CPA
    )


def test_cpa_can_approve_deliverable():
    assert_close_transition_allowed(
        from_status=CloseStatus.APPROVED, to_status=CloseStatus.DELIVERED, actor_role=UserRole.CPA
    )


def test_reconciliation_agent_cannot_approve_close():
    with pytest.raises(InvalidCloseTransition):
        assert_close_transition_allowed(
            from_status=CloseStatus.UNDER_CPA_REVIEW,
            to_status=CloseStatus.APPROVED,
            actor_role=UserRole.AI_RECONCILIATION,
        )


def test_static_table_never_allows_an_ai_role_into_a_terminal_close_state():
    violations = []
    for from_status, targets in ALLOWED_TRANSITIONS.items():
        for to_status, roles in targets.items():
            for role in roles:
                if is_ai_reachable_terminal_close_state(to_status, role):
                    violations.append((from_status, to_status, role))
    assert violations == []

import pytest

from app.models.enums import EntryStatus, UserRole
from app.services.accounting.entry_state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidEntryTransition,
    assert_transition_allowed,
    is_ai_reachable_terminal_state,
)


def test_ai_intake_can_propose_draft_to_pending_review():
    assert_transition_allowed(
        from_status=EntryStatus.DRAFT, to_status=EntryStatus.PENDING_REVIEW, actor_role=UserRole.AI_INTAKE
    )


@pytest.mark.parametrize("terminal", [EntryStatus.APPROVED, EntryStatus.REJECTED])
def test_ai_intake_cannot_move_pending_review_to_terminal_states(terminal):
    with pytest.raises(InvalidEntryTransition):
        assert_transition_allowed(
            from_status=EntryStatus.PENDING_REVIEW, to_status=terminal, actor_role=UserRole.AI_INTAKE
        )


@pytest.mark.parametrize(
    "role", [UserRole.AI_INTAKE, UserRole.AI_RECONCILIATION, UserRole.AI_COPILOT, UserRole.AI_REPORTING]
)
@pytest.mark.parametrize(
    "terminal", [EntryStatus.APPROVED, EntryStatus.REJECTED, EntryStatus.POSTED, EntryStatus.REVERSED]
)
def test_no_ai_role_can_ever_reach_a_terminal_state(role, terminal):
    for from_status in EntryStatus:
        with pytest.raises(InvalidEntryTransition):
            assert_transition_allowed(from_status=from_status, to_status=terminal, actor_role=role)


def test_cpa_can_approve_pending_review():
    assert_transition_allowed(
        from_status=EntryStatus.PENDING_REVIEW, to_status=EntryStatus.APPROVED, actor_role=UserRole.CPA
    )


def test_cpa_cannot_propose_draft_to_pending_review():
    """CPAs review; they don't do the AI's job of proposing entries."""
    with pytest.raises(InvalidEntryTransition):
        assert_transition_allowed(
            from_status=EntryStatus.DRAFT, to_status=EntryStatus.PENDING_REVIEW, actor_role=UserRole.CPA
        )


def test_nonexistent_transition_rejected():
    with pytest.raises(InvalidEntryTransition, match="not a permitted transition"):
        assert_transition_allowed(
            from_status=EntryStatus.REJECTED, to_status=EntryStatus.APPROVED, actor_role=UserRole.CPA
        )


def test_full_revision_cycle_is_reachable():
    # pending_review -> needs_revision (CPA) -> pending_review (AI) -> approved (CPA)
    assert_transition_allowed(
        from_status=EntryStatus.PENDING_REVIEW,
        to_status=EntryStatus.NEEDS_REVISION,
        actor_role=UserRole.CPA,
    )
    assert_transition_allowed(
        from_status=EntryStatus.NEEDS_REVISION,
        to_status=EntryStatus.PENDING_REVIEW,
        actor_role=UserRole.AI_INTAKE,
    )
    assert_transition_allowed(
        from_status=EntryStatus.PENDING_REVIEW, to_status=EntryStatus.APPROVED, actor_role=UserRole.CPA
    )


def test_static_table_never_allows_an_ai_role_into_a_terminal_state():
    """Exhaustively walk the transition table itself (not just spot-check
    calls) — the same assertion the security test suite makes about the
    live database, made here about the Python source of truth."""
    violations = []
    for from_status, targets in ALLOWED_TRANSITIONS.items():
        for to_status, roles in targets.items():
            for role in roles:
                if is_ai_reachable_terminal_state(to_status, role):
                    violations.append((from_status, to_status, role))
    assert violations == []

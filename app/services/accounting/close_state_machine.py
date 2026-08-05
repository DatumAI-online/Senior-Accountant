"""
Application-level enforcement of the Monthly Close state machine
(DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 7.2). Mirrors
entry_state_machine.py exactly: this is the fast-failing first line of
defense; the actual guarantee is the Postgres trigger in
alembic/versions/0004_reconciliation_reporting_grants.py, which blocks
datumai_ai_service from ever writing 'approved' or 'delivered' regardless
of what happens here.
"""

from app.models.enums import CloseStatus, UserRole

ALLOWED_TRANSITIONS: dict[CloseStatus, dict[CloseStatus, frozenset[UserRole]]] = {
    CloseStatus.NOT_STARTED: {
        CloseStatus.COLLECTING_DOCUMENTS: frozenset({UserRole.AI_INTAKE}),
    },
    CloseStatus.COLLECTING_DOCUMENTS: {
        CloseStatus.PROCESSING: frozenset({UserRole.AI_INTAKE}),
    },
    CloseStatus.PROCESSING: {
        CloseStatus.RECONCILING: frozenset({UserRole.AI_RECONCILIATION}),
    },
    CloseStatus.RECONCILING: {
        CloseStatus.WAITING_FOR_CLIENT: frozenset({UserRole.AI_RECONCILIATION}),
        CloseStatus.READY_FOR_CPA_REVIEW: frozenset({UserRole.AI_RECONCILIATION}),
    },
    CloseStatus.WAITING_FOR_CLIENT: {
        CloseStatus.RECONCILING: frozenset({UserRole.AI_RECONCILIATION}),
    },
    CloseStatus.READY_FOR_CPA_REVIEW: {
        CloseStatus.UNDER_CPA_REVIEW: frozenset({UserRole.CPA}),
    },
    CloseStatus.UNDER_CPA_REVIEW: {
        CloseStatus.REVISION_REQUIRED: frozenset({UserRole.CPA}),
        CloseStatus.APPROVED: frozenset({UserRole.CPA}),
    },
    CloseStatus.REVISION_REQUIRED: {
        CloseStatus.PROCESSING: frozenset({UserRole.AI_INTAKE}),
    },
    CloseStatus.APPROVED: {
        CloseStatus.DELIVERED: frozenset({UserRole.CPA}),
    },
}


class InvalidCloseTransition(PermissionError):
    """PermissionError subclass so route handlers can map it straight to
    HTTP 403/409 without extra branching."""


def assert_close_transition_allowed(
    *, from_status: CloseStatus, to_status: CloseStatus, actor_role: UserRole
) -> None:
    allowed_targets = ALLOWED_TRANSITIONS.get(from_status, {})
    allowed_roles = allowed_targets.get(to_status)

    if allowed_roles is None:
        raise InvalidCloseTransition(
            f"{from_status.value} -> {to_status.value} is not a permitted close transition."
        )
    if actor_role not in allowed_roles:
        raise InvalidCloseTransition(
            f"Role {actor_role.value} may not perform {from_status.value} -> {to_status.value}. "
            f"Allowed roles: {sorted(r.value for r in allowed_roles)}."
        )


def is_ai_reachable_terminal_close_state(to_status: CloseStatus, actor_role: UserRole) -> bool:
    return actor_role.is_ai_service_role and to_status.is_terminal_approval_state

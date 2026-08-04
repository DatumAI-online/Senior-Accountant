"""
Application-level enforcement of the Accounting Entry state machine
(DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 7.1). This is the FIRST line of
defense and exists to fail fast with a clear error message; the actual
guarantee that an AI credential can never reach an approval state is the
Postgres trigger in alembic/versions/0002_security_roles_and_grants.py,
which does not depend on this module being bug-free. Both layers are
tested — see tests/unit/test_entry_state_machine.py (this layer) and
tests/security/test_db_grants.py (the database layer).
"""

from app.models.enums import EntryStatus, UserRole

# {from_status: {to_status: {roles allowed to trigger this transition}}}
ALLOWED_TRANSITIONS: dict[EntryStatus, dict[EntryStatus, frozenset[UserRole]]] = {
    EntryStatus.DRAFT: {
        EntryStatus.PENDING_REVIEW: frozenset({UserRole.AI_INTAKE}),
    },
    EntryStatus.PENDING_REVIEW: {
        EntryStatus.NEEDS_CLIENT_INFORMATION: frozenset(
            {UserRole.AI_INTAKE, UserRole.AI_RECONCILIATION}
        ),
        EntryStatus.NEEDS_REVISION: frozenset({UserRole.CPA}),
        EntryStatus.APPROVED: frozenset({UserRole.CPA}),
        EntryStatus.REJECTED: frozenset({UserRole.CPA}),
    },
    EntryStatus.NEEDS_CLIENT_INFORMATION: {
        EntryStatus.PENDING_REVIEW: frozenset({UserRole.AI_INTAKE}),
    },
    EntryStatus.NEEDS_REVISION: {
        EntryStatus.PENDING_REVIEW: frozenset({UserRole.AI_INTAKE}),
    },
    EntryStatus.APPROVED: {
        EntryStatus.POSTED: frozenset({UserRole.CPA}),
    },
    EntryStatus.POSTED: {
        EntryStatus.REVERSED: frozenset({UserRole.CPA}),
    },
}


class InvalidEntryTransition(PermissionError):
    """Raised for a transition that either doesn't exist in the state
    machine or isn't permitted for the acting role. Deliberately a
    PermissionError subclass so route handlers can map it to HTTP 403
    without extra branching."""


def assert_transition_allowed(
    *, from_status: EntryStatus, to_status: EntryStatus, actor_role: UserRole
) -> None:
    allowed_targets = ALLOWED_TRANSITIONS.get(from_status, {})
    allowed_roles = allowed_targets.get(to_status)

    if allowed_roles is None:
        raise InvalidEntryTransition(
            f"{from_status.value} -> {to_status.value} is not a permitted transition."
        )
    if actor_role not in allowed_roles:
        raise InvalidEntryTransition(
            f"Role {actor_role.value} may not perform {from_status.value} -> {to_status.value}. "
            f"Allowed roles: {sorted(r.value for r in allowed_roles)}."
        )


def is_ai_reachable_terminal_state(to_status: EntryStatus, actor_role: UserRole) -> bool:
    """True if this (status, role) pair would let an AI role reach a
    terminal approval state. Used by tests/security tooling as a static
    check independent of assert_transition_allowed's control flow."""
    return actor_role.is_ai_service_role and to_status.is_terminal_approval_state

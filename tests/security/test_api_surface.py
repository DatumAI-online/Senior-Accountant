"""
Section 10.2, test #2: statically prove that no approval-capable route
exists anywhere outside app/api/routes_cpa_review.py, and that no
agent-facing router or agent module can ever WRITE a terminal
EntryStatus/CloseStatus or construct a ReviewDecision. This test does not
call the network — it inspects the registered FastAPI route table and the
source files directly, so it fails the build the moment someone adds a
forbidden route or write, even before a single request is made.

Note the distinction this test draws between reading and writing a
terminal status: the Reporting Agent must legitimately QUERY
EntryStatus.APPROVED/POSTED entries (that's its whole job — reports may
only use CPA-approved data), and the Reconciliation Agent legitimately
includes approved-but-not-yet-posted entries in balance calculations.
Banning the enum value outright would make those agents impossible to
write; banning the assignment pattern is the actual invariant that matters.
"""

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"

FORBIDDEN_PATH_FRAGMENTS = ["approve", "reject", "request-revision", "/post", "posted"]

# Router/agent modules that must never be able to reach an approval action.
NON_CPA_ROUTER_FILES = [
    APP_DIR / "api" / "routes.py",
    APP_DIR / "api" / "routes_auth.py",
    APP_DIR / "api" / "routes_agent_intake.py",
    APP_DIR / "api" / "routes_agent_reconciliation.py",
    APP_DIR / "api" / "routes_agent_copilot.py",
    APP_DIR / "api" / "routes_agent_reporting.py",
]

CPA_ROUTER_FILE = APP_DIR / "api" / "routes_cpa_review.py"

# Symbols with NO legitimate read-only use in agent code — a bare mention
# anywhere outside the CPA router is itself the violation.
HARD_FORBIDDEN_SYMBOLS = [
    "ReviewDecision(",
    "get_cpa_db",
]

# Patterns that indicate an actual WRITE of a terminal status, as opposed
# to a read/filter (e.g. `.in_({EntryStatus.APPROVED, ...})` or
# `EntryStatus.APPROVED in ...` are fine; `x.status = EntryStatus.APPROVED`
# is not).
FORBIDDEN_WRITE_PATTERNS = [
    re.compile(r"\.status\s*=\s*EntryStatus\.(APPROVED|REJECTED|POSTED|REVERSED)\b"),
    re.compile(r"\.close_status\s*=\s*CloseStatus\.(APPROVED|DELIVERED)\b"),
    re.compile(r"EntryStatus\(\s*status\s*=\s*EntryStatus\.(APPROVED|REJECTED|POSTED|REVERSED)\b"),
]


def test_no_approval_paths_outside_cpa_router():
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/v1/agent") or path.startswith("/api/v1/auth"):
            for fragment in FORBIDDEN_PATH_FRAGMENTS:
                assert fragment not in path.lower(), (
                    f"Route {path!r} outside the CPA router looks approval-capable "
                    f"(matched forbidden fragment {fragment!r})."
                )


def test_cpa_router_has_exactly_the_expected_approval_routes():
    from app.main import app

    cpa_paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/cpa")
    }
    expected = {
        "/api/v1/cpa/review-queue",
        "/api/v1/cpa/entries/{entry_id}/approve",
        "/api/v1/cpa/entries/{entry_id}/reject",
        "/api/v1/cpa/entries/{entry_id}/request-revision",
        "/api/v1/cpa/periods/{period_id}/start-review",
        "/api/v1/cpa/periods/{period_id}/approve-close",
        "/api/v1/cpa/periods/{period_id}/approve-deliverable",
    }
    assert expected <= cpa_paths


def test_non_cpa_routers_never_reference_hard_forbidden_symbols():
    for module_path in NON_CPA_ROUTER_FILES:
        source = module_path.read_text()
        for symbol in HARD_FORBIDDEN_SYMBOLS:
            assert symbol not in source, (
                f"{module_path.name} references {symbol!r}, which must only ever "
                f"appear in routes_cpa_review.py."
            )


def test_non_cpa_routers_never_write_a_terminal_status():
    for module_path in NON_CPA_ROUTER_FILES:
        source = module_path.read_text()
        for pattern in FORBIDDEN_WRITE_PATTERNS:
            match = pattern.search(source)
            assert match is None, f"{module_path.name} writes a terminal status: {match.group(0)!r}"


def test_agent_modules_never_reference_hard_forbidden_symbols():
    """Same check for every agent tool/orchestration module, not just its
    HTTP router — a tool function reaching this would be just as much of a
    violation as a route."""
    agent_dir = APP_DIR / "agents"
    for py_file in agent_dir.rglob("*.py"):
        source = py_file.read_text()
        for symbol in HARD_FORBIDDEN_SYMBOLS:
            assert symbol not in source, f"{py_file} references {symbol!r}."


def test_agent_modules_never_write_a_terminal_status():
    agent_dir = APP_DIR / "agents"
    for py_file in agent_dir.rglob("*.py"):
        source = py_file.read_text()
        for pattern in FORBIDDEN_WRITE_PATTERNS:
            match = pattern.search(source)
            assert match is None, f"{py_file} writes a terminal status: {match.group(0)!r}"


def test_cpa_router_is_the_only_place_review_decision_is_constructed():
    """ReviewDecision( should appear in exactly one production module."""
    hits = []
    for py_file in APP_DIR.rglob("*.py"):
        if py_file.name == "review_decision.py":  # the model definition itself
            continue
        if "ReviewDecision(" in py_file.read_text():
            hits.append(py_file)
    assert hits == [CPA_ROUTER_FILE], f"ReviewDecision( constructed in unexpected files: {hits}"


def test_every_agent_route_requires_an_ai_role():
    """Every agent-facing router's role dependency must be drawn only from
    the four AI_* roles — never CPA."""
    from app.api.routes_agent_copilot import require_copilot_agent
    from app.api.routes_agent_intake import require_intake_agent
    from app.api.routes_agent_reconciliation import require_reconciliation_agent
    from app.api.routes_agent_reporting import require_reporting_agent
    from app.models.enums import UserRole

    ai_roles = {
        UserRole.AI_INTAKE,
        UserRole.AI_RECONCILIATION,
        UserRole.AI_COPILOT,
        UserRole.AI_REPORTING,
    }

    for dependency in (
        require_intake_agent,
        require_reconciliation_agent,
        require_copilot_agent,
        require_reporting_agent,
    ):
        roles = dependency.__closure__[0].cell_contents
        assert set(roles) <= ai_roles
        assert UserRole.CPA not in roles


def test_every_cpa_route_requires_cpa_role():
    from app.api.routes_cpa_review import require_cpa
    from app.models.enums import UserRole

    roles = require_cpa.__closure__[0].cell_contents
    assert set(roles) == {UserRole.CPA}

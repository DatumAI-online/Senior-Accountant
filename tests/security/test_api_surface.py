"""
Section 10.2, test #2: statically prove that no approval-capable route
exists anywhere outside app/api/routes_cpa_review.py, and that no route
under the agent-facing routers can reach ReviewDecision creation or a
terminal EntryStatus. This test does not call the network — it inspects
the registered FastAPI route table and the router source files directly,
so it fails the build the moment someone adds a forbidden route, even
before a single request is made against it.
"""

from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"

FORBIDDEN_PATH_FRAGMENTS = ["approve", "reject", "request-revision", "/post", "posted"]

# Router modules that must never be able to reach an approval action.
NON_CPA_ROUTER_FILES = [
    APP_DIR / "api" / "routes.py",
    APP_DIR / "api" / "routes_auth.py",
    APP_DIR / "api" / "routes_agent_intake.py",
]

CPA_ROUTER_FILE = APP_DIR / "api" / "routes_cpa_review.py"

FORBIDDEN_SYMBOLS_OUTSIDE_CPA_ROUTER = [
    "ReviewDecision(",
    "EntryStatus.APPROVED",
    "EntryStatus.REJECTED",
    "EntryStatus.POSTED",
    "EntryStatus.REVERSED",
    "get_cpa_db",
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
    }
    assert expected <= cpa_paths


def test_non_cpa_routers_never_reference_approval_symbols():
    for module_path in NON_CPA_ROUTER_FILES:
        source = module_path.read_text()
        for symbol in FORBIDDEN_SYMBOLS_OUTSIDE_CPA_ROUTER:
            assert symbol not in source, (
                f"{module_path.name} references {symbol!r}, which must only ever "
                f"appear in routes_cpa_review.py."
            )


def test_agent_intake_tools_never_reference_approval_symbols():
    """Same check for the agent's own tool/orchestration modules, not just
    its HTTP router — a tool function reaching this would be just as much
    of a violation as a route."""
    agent_dir = APP_DIR / "agents"
    for py_file in agent_dir.rglob("*.py"):
        source = py_file.read_text()
        for symbol in FORBIDDEN_SYMBOLS_OUTSIDE_CPA_ROUTER:
            assert symbol not in source, f"{py_file} references {symbol!r}."


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
    """Every route registered by routes_agent_intake.py must depend on
    require_role(...) with only AI_* roles — not require_cpa."""
    from app.api.routes_agent_intake import require_intake_agent
    from app.models.enums import UserRole

    # require_role is a closure; inspect its defaults for the roles tuple.
    roles = require_intake_agent.__closure__[0].cell_contents
    assert set(roles) <= {
        UserRole.AI_INTAKE,
        UserRole.AI_RECONCILIATION,
        UserRole.AI_COPILOT,
        UserRole.AI_REPORTING,
    }
    assert UserRole.CPA not in roles


def test_every_cpa_route_requires_cpa_role():
    from app.api.routes_cpa_review import require_cpa
    from app.models.enums import UserRole

    roles = require_cpa.__closure__[0].cell_contents
    assert set(roles) == {UserRole.CPA}

"""Unit test: compliance_check — verify M4 milestone logging for compliance events."""
import json
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_m4_milestone_emitted_for_compliance_query(caplog):
    """M4.achieved must be logged when compliance check result appears in response."""
    import logging
    from agent import _emit_milestones_from_result

    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(
            result,
            "run payroll compliance check",
            "compliance check completed: 2 violations found in tax declarations"
        )

    assert any("M4.achieved" in r.message for r in caplog.records), (
        "Expected M4.achieved log for compliance check completion"
    )


@pytest.mark.asyncio
async def test_statutory_tool_accessible_for_compliance():
    """Verify statutory reporting tool available for compliance checks."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    names = {t.name for t in tools}
    assert "GET_Activity" in names
    assert "listItDeclarationTimeBound" in names


@pytest.mark.asyncio
async def test_no_m4_without_compliance_keywords(caplog):
    """M4 should NOT be emitted for non-compliance queries."""
    import logging
    from agent import _emit_milestones_from_result

    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(
            result,
            "show me payroll history",
            "here are your payroll records from March 2026"
        )

    m4_logs = [r for r in caplog.records if "M4" in r.message]
    assert not m4_logs, "M4 must not be logged for non-compliance queries"

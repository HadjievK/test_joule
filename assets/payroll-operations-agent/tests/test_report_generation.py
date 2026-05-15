"""Unit test: report_generation — verify M5 milestone logging when report generated."""
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_m5_milestone_emitted_for_report(caplog):
    """M5.achieved must be logged when payroll report appears in agent output."""
    import logging
    from agent import _emit_milestones_from_result

    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(
            result,
            "generate payroll report for Q1 2026",
            "payroll report generated: 45 employees processed, total net pay $278,000"
        )

    assert any("M5.achieved" in r.message for r in caplog.records), (
        "Expected M5.achieved log when payroll report is generated"
    )


@pytest.mark.asyncio
async def test_m5_not_emitted_for_simple_query(caplog):
    """M5 should not be logged for non-report queries."""
    import logging
    from agent import _emit_milestones_from_result

    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(
            result,
            "list employees",
            "here are 5 employees"
        )

    m5_logs = [r for r in caplog.records if "M5" in r.message]
    assert not m5_logs, "M5 should not be logged for non-report queries"


@pytest.mark.asyncio
async def test_all_needed_tools_for_complete_report():
    """Report generation requires access to payroll, time, compensation, and statutory data."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    names = {t.name for t in tools}
    required = {
        "listEmployeePayrollRunResults",
        "listEmployeePayrollRunResultsItems",
        "listEmpCompensation",
        "listEmployeeTimeSheets",
        "GET_Activity",
    }
    missing = required - names
    assert not missing, f"Report generation tools missing: {missing}"

"""Unit test: discrepancy detection — verify agent logic identifies mismatches."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


def _make_payroll_records(net_pay="6200.00"):
    return json.dumps({"results": [
        {"externalCode": "PR-2026-03-001", "payrollStatus": "Completed",
         "netPay": net_pay, "grossPay": "8500.00", "currency": "USD"},
    ]})


def _make_time_sheets(hours=176.0):
    return json.dumps({"results": [
        {"externalCode": "TS-E1001-2026-03", "userId": "E1001",
         "approvalStatus": "Approved", "totalHours": hours},
    ]})


@pytest.mark.asyncio
async def test_milestone_log_emitted_on_discrepancy(caplog):
    """Verify M3.achieved is logged when discrepancy keyword appears in response."""
    import logging
    from agent import _emit_milestones_from_result

    result = {
        "messages": [
            MagicMock(tool_calls=[], content=""),
            MagicMock(name=None, content="discrepancy found for employee E1001: hours mismatch"),
        ]
    }
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(result, "check discrepancies", "discrepancy found for employee E1001: hours mismatch")

    assert any("M3.achieved" in r.message for r in caplog.records), (
        "Expected M3.achieved log when discrepancy is detected"
    )


@pytest.mark.asyncio
async def test_milestone_log_missed_when_no_discrepancy(caplog):
    """Verify M3.missed is logged when query asks for discrepancy check but none found."""
    import logging
    from agent import _emit_milestones_from_result

    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(result, "check for discrepancies", "no discrepancies found in the payroll data")

    assert any("M3.missed" in r.message for r in caplog.records), (
        "Expected M3.missed log when query asks for discrepancy check but none found"
    )


@pytest.mark.asyncio
async def test_payroll_and_timesheet_tools_both_available():
    """Both time sheet and payroll tools must be available for cross-system comparison."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    names = {t.name for t in tools}
    assert "listEmployeePayrollRunResults" in names
    assert "listEmployeeTimeSheets" in names

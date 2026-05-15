"""Unit test: apply_payroll_correction — assert PUT tool exists and returns confirmation."""
import json
import pytest


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_update_payroll_run_result_tool_exists():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "updateEmployeePayrollRunResult"), None)
    assert tool is not None, "Expected updateEmployeePayrollRunResult (correction) tool"


@pytest.mark.asyncio
async def test_update_payroll_run_result_returns_updated_record():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next(t for t in tools if t.name == "updateEmployeePayrollRunResult")
    result = await tool.arun({"externalCode": "PR-2026-03-001"})
    data = json.loads(result)
    assert "externalCode" in data
    assert "payrollStatus" in data
    assert data["payrollStatus"] in ("Corrected", "Updated", "Completed", "Pending")


@pytest.mark.asyncio
async def test_update_time_record_tool_exists():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "updateExternalTimeRecord"), None)
    assert tool is not None, "Expected updateExternalTimeRecord tool for time corrections"


@pytest.mark.asyncio
async def test_update_time_record_returns_status():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next(t for t in tools if t.name == "updateExternalTimeRecord")
    result = await tool.arun({"externalCode": "ETR-E1001-001"})
    data = json.loads(result)
    assert "externalCode" in data or "status" in data

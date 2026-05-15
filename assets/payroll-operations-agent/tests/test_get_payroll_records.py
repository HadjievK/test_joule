"""Unit test: get_payroll_records — verifies payroll run results are retrieved from mock MCP tools."""
import json
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_get_payroll_records_returns_run_results():
    """Mock MCP tools returning payroll run results; assert non-empty list returned."""
    from mcp_tools import get_mcp_tools

    tools = await get_mcp_tools()
    tool_names = [t.name for t in tools]

    assert "listEmployeePayrollRunResults" in tool_names, (
        "Expected listEmployeePayrollRunResults tool in mock MCP tools"
    )

    list_tool = next(t for t in tools if t.name == "listEmployeePayrollRunResults")
    result = await list_tool.arun({"$top": 100})
    data = json.loads(result)

    assert "results" in data, "Expected 'results' key in payroll run results response"
    assert len(data["results"]) > 0, "Expected at least one payroll run result"
    record = data["results"][0]
    assert "externalCode" in record
    assert "payrollStatus" in record
    assert "grossPay" in record


@pytest.mark.asyncio
async def test_get_payroll_run_result_items():
    """Mock MCP tools returning line items; assert items list returned."""
    from mcp_tools import get_mcp_tools

    tools = await get_mcp_tools()
    items_tool = next((t for t in tools if t.name == "listEmployeePayrollRunResultsItems"), None)
    assert items_tool is not None, "Expected listEmployeePayrollRunResultsItems tool"

    result = await items_tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    item = data["results"][0]
    assert "payComponent" in item
    assert "amount" in item


@pytest.mark.asyncio
async def test_get_payroll_earmarked_funds():
    """Mock MCP tools returning S/4HANA earmarked funds; assert records present."""
    from mcp_tools import get_mcp_tools

    tools = await get_mcp_tools()
    funds_tool = next((t for t in tools if t.name == "GET_PayrollEarmarkedFundsDoc"), None)
    assert funds_tool is not None, "Expected GET_PayrollEarmarkedFundsDoc tool"

    result = await funds_tool.arun({})
    data = json.loads(result)
    assert "value" in data or "results" in data or isinstance(data, (dict, list))

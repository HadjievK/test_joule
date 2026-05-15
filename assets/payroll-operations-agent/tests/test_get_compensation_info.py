"""Unit test: get_compensation_info — verifies compensation data parsed correctly."""
import json
import pytest


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_list_emp_compensation():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listEmpCompensation"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    rec = data["results"][0]
    assert "userId" in rec
    assert "annualSalary" in rec
    assert "currency" in rec


@pytest.mark.asyncio
async def test_list_emp_pay_comp_recurring():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listEmpPayCompRecurring"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    assert "payComponent" in data["results"][0]
    assert "amount" in data["results"][0]


@pytest.mark.asyncio
async def test_list_one_time_deductions():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listOneTimeDeductions"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_list_recurring_deduction_items():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listRecurringDeductionItems"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0

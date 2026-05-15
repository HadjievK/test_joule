"""Unit test: get_benefits — verifies deduction items returned from mock tools."""
import json
import pytest


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_list_recurring_deductions():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listRecurringDeductionItems"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    item = data["results"][0]
    assert "payComponent" in item
    assert "amount" in item


@pytest.mark.asyncio
async def test_list_one_time_deductions_for_employee():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listOneTimeDeductions"), None)
    assert tool is not None
    result = await tool.arun({"$filter": "userId eq 'E1001'"})
    data = json.loads(result)
    # Should return a deductions object
    assert isinstance(data, dict)

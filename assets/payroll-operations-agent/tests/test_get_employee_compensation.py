"""Unit test: get_employee_compensation — verifies compensation management tool."""
import json
import pytest


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_query_employee_compensations():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "queryEmployeeCompensationEntries"), None)
    assert tool is not None
    result = await tool.arun({})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    rec = data["results"][0]
    assert "employeeId" in rec
    assert "amount" in rec
    assert "currency" in rec

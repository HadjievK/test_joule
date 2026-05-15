"""Unit test: get_time_sheets — verifies time sheet data is returned from mock MCP tools."""
import json
import pytest


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_list_employee_time_sheets():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listEmployeeTimeSheets"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    sheet = data["results"][0]
    assert "userId" in sheet
    assert "totalHours" in sheet
    assert "approvalStatus" in sheet


@pytest.mark.asyncio
async def test_list_time_collectors():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listTimeCollectors"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    assert "timeType" in data["results"][0]

"""Unit test: get_statutory_reporting_tasks — assert overdue items are present in mock data."""
import json
import pytest


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_list_activities_returns_tasks():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "GET_Activity"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "value" in data
    assert len(data["value"]) > 0


@pytest.mark.asyncio
async def test_overdue_activity_present_in_mock():
    """Mock data contains at least one overdue statutory activity."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next(t for t in tools if t.name == "GET_Activity")
    result = await tool.arun({})
    data = json.loads(result)
    activities = data.get("value", [])
    overdue = [a for a in activities if a.get("Overdue") or a.get("Status") == "Overdue"]
    assert len(overdue) > 0, "Expected at least one overdue statutory activity in mock data"


@pytest.mark.asyncio
async def test_get_activity_by_uuid():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "GET_Activity_StatryRptActivityUUID"), None)
    assert tool is not None
    result = await tool.arun({"StatryRptActivityUUID": "ACT-001"})
    data = json.loads(result)
    assert "ActivityName" in data or "StatryRptActivityUUID" in data

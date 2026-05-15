"""Unit test: get_income_tax_declarations — verifies declaration status returned."""
import json
import pytest


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_list_it_declaration_time_bound():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listItDeclarationTimeBound"), None)
    assert tool is not None
    result = await tool.arun({"$top": 100})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    rec = data["results"][0]
    assert "declarationStatus" in rec
    assert "fiscalYear" in rec
    assert "dueDate" in rec


@pytest.mark.asyncio
async def test_overdue_declaration_in_mock():
    """Verify at least one overdue income tax declaration in mock data."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next(t for t in tools if t.name == "listItDeclarationTimeBound")
    result = await tool.arun({})
    data = json.loads(result)
    declarations = data.get("results", [])
    overdue = [d for d in declarations if d.get("declarationStatus") == "Overdue"]
    assert len(overdue) > 0, "Expected at least one overdue tax declaration in mock data"


@pytest.mark.asyncio
async def test_list_declaration_types():
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "listDeclarationTypes"), None)
    assert tool is not None
    result = await tool.arun({})
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) > 0
    assert "name" in data["results"][0]

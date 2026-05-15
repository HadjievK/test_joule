"""Integration test: Full agent invoke with mocked LLM and mock MCP tools.

Tests that the PayrollOperationsAgent correctly orchestrates tool calls and
returns a structured response for end-to-end payroll operations scenarios.
All LLM calls are mocked — AI Core is not available during tests.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


def _make_ai_message(content: str, tool_calls: list | None = None):
    """Build a mock LangChain AIMessage."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    msg.type = "ai"
    return msg


def _make_tool_message(name: str, content: str):
    msg = MagicMock()
    msg.content = content
    msg.name = name
    msg.type = "tool"
    msg.tool_calls = []
    return msg


@pytest.mark.asyncio
async def test_agent_invoke_payroll_summary():
    """Agent invoke() with mocked _run_agent should return an AgentResponse."""
    from agent import PayrollOperationsAgent, AgentResponse

    agent = PayrollOperationsAgent()
    mock_response = "Here is the payroll summary for March 2026: 2 employees, gross pay $17,000, net pay $12,350."
    with patch.object(agent, "_run_agent", new=AsyncMock(return_value=mock_response)):
        result = await agent.invoke("Show payroll summary for March 2026", context_id="ctx-test-001")

    assert isinstance(result, AgentResponse)
    assert result.status == "completed"
    assert "payroll" in result.message.lower()


@pytest.mark.asyncio
async def test_agent_stream_yields_text():
    """Agent stream() must yield at least one dict chunk with content."""
    from agent import PayrollOperationsAgent

    agent = PayrollOperationsAgent()
    mock_response = "Payroll data retrieved for pay period 2026-03."
    yielded = []
    with patch.object(agent, "_run_agent", new=AsyncMock(return_value=mock_response)):
        async for chunk in agent.stream("Get payroll data for March 2026", context_id="ctx-test-002"):
            yielded.append(chunk)

    assert len(yielded) > 0, "Agent stream() must yield at least one chunk"
    # Last chunk must be the completed response
    final = yielded[-1]
    assert isinstance(final, dict)
    assert final.get("is_task_complete") is True
    assert "payroll" in final.get("content", "").lower()


@pytest.mark.asyncio
async def test_agent_milestone_m1_emitted_on_data_retrieval(caplog):
    """M1.achieved must be logged when payroll data retrieval tools are called."""
    import logging
    from agent import _emit_milestones_from_result

    tool_call = MagicMock()
    tool_call.tool_calls = [{"name": "listEmployeePayrollRunResults", "args": {}}]
    tool_call.content = ""

    result = {
        "messages": [
            tool_call,
            _make_tool_message("listEmployeePayrollRunResults", json.dumps({"results": [{"externalCode": "PR-001"}]})),
        ]
    }
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(
            result,
            "retrieve payroll data",
            "payroll run results retrieved for March 2026"
        )

    assert any("M1.achieved" in r.message for r in caplog.records), (
        "Expected M1.achieved log when payroll run tool is called"
    )


@pytest.mark.asyncio
async def test_agent_uses_mcp_tools_not_direct_http():
    """Verify agent never imports requests or httpx in production code paths."""
    import ast
    from pathlib import Path

    app_dir = Path(__file__).parent.parent / "app"
    for py_file in app_dir.glob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in ("requests", "httpx", "urllib.request"), (
                        f"Direct HTTP client '{alias.name}' found in {py_file.name} — use MCP tools instead"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in ("requests", "httpx"), (
                    f"Direct HTTP client '{node.module}' imported in {py_file.name} — use MCP tools instead"
                )


@pytest.mark.asyncio
async def test_mock_tools_cover_all_milestone_scenarios():
    """All 5 milestone scenarios must have corresponding mock MCP tools."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    names = {t.name for t in tools}

    # M1: Data retrieval
    assert any("PayrollRunResult" in n or "payroll" in n.lower() for n in names), "M1 tool missing"
    # M2: Trigger payroll run
    assert any("create" in n.lower() and "payroll" in n.lower() for n in names), "M2 create tool missing"
    # M3: Discrepancy — requires time sheets + payroll
    assert any("TimeSheet" in n or "timesheet" in n.lower() for n in names), "M3 time sheet tool missing"
    # M4: Compliance
    assert any("Activity" in n or "Declaration" in n for n in names), "M4 compliance tool missing"
    # M5: Report — requires compensation + earmarked funds
    assert any("Compensation" in n or "compensation" in n.lower() for n in names), "M5 compensation tool missing"
    assert any("EarmarkedFunds" in n for n in names), "M5 earmarked funds tool missing"

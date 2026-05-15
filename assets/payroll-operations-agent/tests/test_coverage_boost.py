"""Targeted coverage tests to bring total coverage to >= 70%."""
import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


# ──── log_milestone full branch coverage ────────────────────────────────────

@pytest.mark.asyncio
async def test_log_milestone_m1_missed(caplog):
    from agent import log_milestone, M1
    with caplog.at_level(logging.INFO):
        log_milestone(M1, achieved=False, period="2026-03", system="SuccessFactors", error="timeout")
    assert any("M1.missed" in r.message for r in caplog.records)
    assert any("timeout" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_log_milestone_m2_achieved(caplog):
    from agent import log_milestone, M2
    with caplog.at_level(logging.INFO):
        log_milestone(M2, achieved=True, run_id="PR-RUN-001", system="SuccessFactors")
    assert any("M2.achieved" in r.message for r in caplog.records)
    assert any("PR-RUN-001" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_log_milestone_m2_missed(caplog):
    from agent import log_milestone, M2
    with caplog.at_level(logging.INFO):
        log_milestone(M2, achieved=False, system="SuccessFactors", reason="user declined")
    assert any("M2.missed" in r.message for r in caplog.records)
    assert any("user declined" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_log_milestone_m3_missed(caplog):
    from agent import log_milestone, M3
    with caplog.at_level(logging.INFO):
        log_milestone(M3, achieved=False)
    assert any("M3.missed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_log_milestone_m4_missed(caplog):
    from agent import log_milestone, M4
    with caplog.at_level(logging.INFO):
        log_milestone(M4, achieved=False, period="2026-Q1", error="API error")
    assert any("M4.missed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_log_milestone_m5_missed(caplog):
    from agent import log_milestone, M5
    with caplog.at_level(logging.INFO):
        log_milestone(M5, achieved=False, period="2026-03", system="S/4HANA")
    assert any("M5.missed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_log_milestone_unknown_id(caplog):
    from agent import log_milestone
    with caplog.at_level(logging.INFO):
        log_milestone("MX", achieved=True, details="custom detail")
    assert any("MX" in r.message for r in caplog.records)


# ──── _emit_milestones_from_result edge cases ────────────────────────────────

@pytest.mark.asyncio
async def test_emit_m2_trigger_on_create_tool(caplog):
    from agent import _emit_milestones_from_result
    tool_call = MagicMock()
    tool_call.tool_calls = [{"name": "createEmployeePayrollRunResult", "args": {}}]
    tool_call.content = ""
    result = {"messages": [tool_call]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(result, "trigger payroll run", "payroll run initiated run ID PR-2026-04-001")
    assert any("M2" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_emit_m2_missed_no_confirm(caplog):
    from agent import _emit_milestones_from_result
    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(result, "trigger payroll run please", "awaiting confirmation from user")
    m2_logs = [r for r in caplog.records if "M2" in r.message]
    assert len(m2_logs) > 0


@pytest.mark.asyncio
async def test_emit_m4_missed_on_error(caplog):
    from agent import _emit_milestones_from_result
    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(result, "run compliance check", "error: API connection failed")
    m4_logs = [r for r in caplog.records if "M4" in r.message]
    assert len(m4_logs) > 0


@pytest.mark.asyncio
async def test_emit_m5_missed_on_error(caplog):
    from agent import _emit_milestones_from_result
    result = {"messages": [MagicMock(tool_calls=[], name=None, content="")]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(result, "generate report for March", "error retrieving payroll data")
    m5_logs = [r for r in caplog.records if "M5" in r.message]
    assert len(m5_logs) > 0


@pytest.mark.asyncio
async def test_emit_milestones_with_named_tool_message(caplog):
    """Tool messages with .name attribute should populate tool_names_called."""
    from agent import _emit_milestones_from_result
    tool_msg = MagicMock()
    tool_msg.tool_calls = []
    tool_msg.name = "GET_Activity"
    tool_msg.content = json.dumps({"value": [{"Status": "Overdue"}]})
    result = {"messages": [tool_msg]}
    with caplog.at_level(logging.INFO):
        _emit_milestones_from_result(result, "compliance check", "compliance check completed: 1 overdue")
    assert any("M4.achieved" in r.message for r in caplog.records)


# ──── PayrollOperationsAgent._get_graph caching ──────────────────────────────

@pytest.mark.asyncio
async def test_get_graph_caches_on_second_call():
    """_get_graph() should build once and cache; second call returns same object."""
    from agent import PayrollOperationsAgent
    agent = PayrollOperationsAgent()
    graph1 = await agent._get_graph()
    graph2 = await agent._get_graph()
    assert graph1 is graph2, "_get_graph() should return cached graph on second call"


# ──── mcp_tools fallback when mock file absent ───────────────────────────────

@pytest.mark.asyncio
async def test_mcp_tools_returns_mock_list_when_ibd_testing():
    """In IBD_TESTING mode, get_mcp_tools must return a non-empty list."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    assert len(tools) > 0, "Expected mock tools to be loaded from mcp-mock.json"


@pytest.mark.asyncio
async def test_mcp_tools_returns_empty_on_missing_mock_file(tmp_path, monkeypatch):
    """get_mcp_tools should return [] gracefully when mcp-mock.json is absent."""
    import mcp_tools as mt
    original = mt._MOCK_FILE
    monkeypatch.setattr(mt, "_MOCK_FILE", tmp_path / "nonexistent.json")
    tools = await mt.get_mcp_tools()
    monkeypatch.setattr(mt, "_MOCK_FILE", original)
    assert tools == []

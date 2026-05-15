"""Unit test: trigger_payroll_run — assert confirmation required; run ID returned on mock approval."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.asyncio
async def test_create_payroll_run_result_tool_exists():
    """Verify the payroll run creation (write) tool is available."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next((t for t in tools if t.name == "createEmployeePayrollRunResult"), None)
    assert tool is not None, "Expected createEmployeePayrollRunResult tool in mock tools"


@pytest.mark.asyncio
async def test_create_payroll_run_returns_run_id():
    """Calling create tool with valid params returns a run externalCode."""
    from mcp_tools import get_mcp_tools
    tools = await get_mcp_tools()
    tool = next(t for t in tools if t.name == "createEmployeePayrollRunResult")
    result = await tool.arun({
        "externalCode": "PR-2026-04-001",
        "payPeriodStartDate": "2026-04-01",
        "payPeriodEndDate": "2026-04-30",
    })
    data = json.loads(result)
    assert "externalCode" in data, "Expected externalCode in payroll run response"
    assert "payrollStatus" in data


@pytest.mark.asyncio
async def test_agent_system_prompt_requires_confirmation():
    """Verify system prompt instructs agent to require confirmation for write actions."""
    from agent import get_system_prompt
    prompt = get_system_prompt()
    assert "confirmation" in prompt.lower() or "confirm" in prompt.lower() or "approval" in prompt.lower(), (
        "System prompt must require confirmation before write operations"
    )
    assert "write" in prompt.lower() or "trigger" in prompt.lower()

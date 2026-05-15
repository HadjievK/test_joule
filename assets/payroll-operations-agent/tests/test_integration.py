"""Integration test: end-to-end agent flow with mocked LLM and MCP tools."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

APP_PATH = Path(__file__).parent.parent / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))


@pytest.mark.integration
async def test_end_to_end_payroll_status_query():
    """Full agent flow: payroll status query → time sheet check → report generation."""
    from agent import SampleAgent

    mock_response = AIMessage(
        content=(
            "Payroll Status Report — Period: 2024-01\n\n"
            "SAP SuccessFactors: 1 run completed, 150 employees, gross $750,000.\n"
            "SAP S/4HANA: 1 run completed, 148 employees, gross $740,000.\n"
            "⚠️ Headcount discrepancy detected: SF=150, S4=148 (delta: 2). "
            "Please review before finalizing.\n\n"
            "Time sheets: 2 retrieved. 1 has zero hours (EMP002) — flagged for review.\n\n"
            "M1.achieved: payroll data retrieved from [SF, S4HANA] for period 2024-01 — 300 records"
        )
    )

    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    agent = SampleAgent.__new__(SampleAgent)
    agent.llm = mock_llm
    agent._graph = None

    with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
        mock_tools.return_value = []

        response = await agent.invoke(
            "Show me the payroll run status for January 2024 across both systems and validate time sheets",
            context_id="test-context-001",
        )

    assert response.status == "completed"
    assert "SAP SuccessFactors" in response.message
    assert "S/4HANA" in response.message
    assert "150" in response.message


@pytest.mark.integration
async def test_compliance_check_flow():
    """Compliance check flow with mocked LLM."""
    from agent import SampleAgent

    mock_response = AIMessage(
        content=(
            "Compliance Check Results — 2024-01\n\n"
            "Income Tax Declarations: EMP001 — declared $60,000, withheld $12,000 ✓\n"
            "Statutory Reporting Tasks: 1 open — QUARTERLY_TAX due 2024-04-30 (Finance Controller)\n\n"
            "M4.achieved: compliance check completed — 1 compliant, 1 flagged\n\n"
            "Action required: Complete QUARTERLY_TAX task before due date."
        )
    )

    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    agent = SampleAgent.__new__(SampleAgent)
    agent.llm = mock_llm
    agent._graph = None

    with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
        mock_tools.return_value = []

        response = await agent.invoke(
            "Run compliance check for company 1000 for period 2024-01",
            context_id="test-context-002",
        )

    assert response.status == "completed"
    assert "compliance" in response.message.lower() or "Compliance" in response.message


@pytest.mark.integration
async def test_payroll_run_initiation_requires_confirmation():
    """Payroll run initiation should surface confirmation request."""
    from agent import SampleAgent

    mock_response = AIMessage(
        content=(
            "⚠️ Pre-Run Summary — Payroll Run Request\n\n"
            "System: SAP SuccessFactors\n"
            "Period: 2024-02\n"
            "Employee count: 150\n"
            "Warnings: 1 time sheet missing (EMP002)\n\n"
            "Please confirm to proceed with payroll run. "
            "Type 'confirm' to initiate or 'cancel' to abort."
        )
    )

    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    agent = SampleAgent.__new__(SampleAgent)
    agent.llm = mock_llm
    agent._graph = None

    with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
        mock_tools.return_value = []

        response = await agent.invoke(
            "Trigger payroll run for February 2024",
            context_id="test-context-003",
        )

    assert response.status == "completed"
    # The agent should surface a confirmation request, not immediately trigger
    assert "confirm" in response.message.lower() or "pre-run" in response.message.lower() or "warning" in response.message.lower()

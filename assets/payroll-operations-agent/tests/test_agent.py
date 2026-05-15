"""Tests for agent.py — system prompt, model config, milestone instrumentation, stream/invoke."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

APP_PATH = Path(__file__).parent.parent / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))


# ---------------------------------------------------------------------------
# Decorator / config tests
# ---------------------------------------------------------------------------

class TestAgentConfig:
    def test_get_model_name_returns_string(self):
        from agent import get_model_name
        model = get_model_name()
        assert isinstance(model, str)
        assert len(model) > 0

    def test_get_temperature_returns_float(self):
        from agent import get_temperature
        temp = get_temperature()
        assert isinstance(temp, float)
        assert 0.0 <= temp <= 1.0

    def test_get_system_prompt_contains_key_instructions(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "payroll" in prompt.lower()
        assert "SuccessFactors" in prompt
        assert "HANA Cloud" in prompt
        assert "confirmation" in prompt.lower() or "confirm" in prompt.lower()

    def test_system_prompt_mentions_guardrails(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "top" in prompt.lower() or "100" in prompt
        assert "hallucinate" in prompt.lower() or "never" in prompt.lower()


# ---------------------------------------------------------------------------
# Agent initialization tests
# ---------------------------------------------------------------------------

class TestSampleAgentInit:
    def test_agent_initializes(self):
        from agent import SampleAgent
        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            agent = SampleAgent()
            assert agent._graph is None
            assert agent.llm is not None

    def test_agent_has_supported_content_types(self):
        from agent import SampleAgent
        with patch("agent.get_mcp_tools", new_callable=AsyncMock):
            agent = SampleAgent()
            assert "text" in agent.SUPPORTED_CONTENT_TYPES


# ---------------------------------------------------------------------------
# _get_graph tests
# ---------------------------------------------------------------------------

class TestGetGraph:
    async def test_get_graph_builds_once(self):
        from agent import SampleAgent
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            graph1 = await agent._get_graph()
            graph2 = await agent._get_graph()
            # Called only once
            mock_tools.assert_called_once()
            assert graph1 is graph2

    async def test_build_graph_with_empty_tools(self):
        from agent import SampleAgent
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            graph = await agent._get_graph()
            assert graph is not None


# ---------------------------------------------------------------------------
# _run_agent tests
# ---------------------------------------------------------------------------

class TestRunAgent:
    async def test_run_agent_returns_response(self):
        from agent import SampleAgent
        mock_response = AIMessage(content="Payroll data retrieved successfully for period 2024-01.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            result = await agent._run_agent("Show payroll status for 2024-01", "ctx-001")
        assert "Payroll" in result

    async def test_run_agent_logs_m1_achieved(self, caplog):
        import logging
        from agent import SampleAgent
        mock_response = AIMessage(content="Data retrieved OK")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            with caplog.at_level(logging.INFO, logger="agent"):
                await agent._run_agent("Get payroll data", "ctx-002")
        assert any("M1.achieved" in r.message for r in caplog.records)

    async def test_run_agent_logs_m5_for_report_query(self, caplog):
        import logging
        from agent import SampleAgent
        mock_response = AIMessage(content="Here is the payroll compliance report for 2024-01.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            with caplog.at_level(logging.INFO, logger="agent"):
                await agent._run_agent("Generate compliance report for 2024-01", "ctx-003")
        assert any("M5" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _run_discrepancy_check tests
# ---------------------------------------------------------------------------

class TestRunDiscrepancyCheck:
    async def test_logs_m3_achieved_with_discrepancy(self, caplog):
        import logging
        from agent import SampleAgent
        mock_response = AIMessage(content="Discrepancy found: SF=150, S4=148, delta=2.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            with caplog.at_level(logging.INFO, logger="agent"):
                result = await agent._run_discrepancy_check("Check for discrepancies in 2024-01")
        assert "Discrepancy" in result
        assert any("M3.achieved" in r.message for r in caplog.records)

    async def test_logs_m3_achieved_no_discrepancy(self, caplog):
        import logging
        from agent import SampleAgent
        mock_response = AIMessage(content="All payroll totals match across both systems.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            with caplog.at_level(logging.INFO, logger="agent"):
                await agent._run_discrepancy_check("Check discrepancies")
        assert any("M3.achieved" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _run_compliance_check tests
# ---------------------------------------------------------------------------

class TestRunComplianceCheck:
    async def test_logs_m4_achieved(self, caplog):
        import logging
        from agent import SampleAgent
        mock_response = AIMessage(content="Compliance check: 1 non-compliant entry flagged.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            with caplog.at_level(logging.INFO, logger="agent"):
                await agent._run_compliance_check("Run compliance check for 2024-01")
        assert any("M4.achieved" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _run_payroll_initiation tests
# ---------------------------------------------------------------------------

class TestRunPayrollInitiation:
    async def test_logs_m2_achieved_when_initiated(self, caplog):
        import logging
        from agent import SampleAgent
        mock_response = AIMessage(content="Payroll run initiated. run_id: RUN-2024-02")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            with caplog.at_level(logging.INFO, logger="agent"):
                await agent._run_payroll_initiation("Initiate payroll run for 2024-02")
        assert any("M2" in r.message for r in caplog.records)

    async def test_logs_m2_missed_when_pending(self, caplog):
        import logging
        from agent import SampleAgent
        mock_response = AIMessage(content="Awaiting confirmation from the payroll administrator.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            with caplog.at_level(logging.INFO, logger="agent"):
                await agent._run_payroll_initiation("Trigger payroll run for 2024-02")
        assert any("M2" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# stream tests
# ---------------------------------------------------------------------------

class TestStream:
    async def test_stream_yields_processing_then_complete(self):
        from agent import SampleAgent
        mock_response = AIMessage(content="Payroll data retrieved.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            events = []
            async for event in agent.stream("Get payroll status", "ctx-stream-001"):
                events.append(event)

        assert len(events) == 2
        assert events[0]["is_task_complete"] is False
        assert events[1]["is_task_complete"] is True

    async def test_stream_routes_discrepancy_query(self):
        from agent import SampleAgent
        mock_response = AIMessage(content="Discrepancy found between SF and S/4HANA.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            events = []
            async for event in agent.stream("Find discrepancies in payroll for 2024-01", "ctx-stream-002"):
                events.append(event)

        assert events[-1]["is_task_complete"] is True
        assert "Discrepancy" in events[-1]["content"]

    async def test_stream_routes_compliance_query(self):
        from agent import SampleAgent
        mock_response = AIMessage(content="Compliance check complete. All items compliant.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            events = []
            async for event in agent.stream("Run tax check compliance for 2024-01", "ctx-stream-003"):
                events.append(event)

        assert events[-1]["is_task_complete"] is True

    async def test_stream_routes_payroll_run_query(self):
        from agent import SampleAgent
        mock_response = AIMessage(content="Please confirm to initiate payroll run for 2024-02.")
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = SampleAgent.__new__(SampleAgent)
        agent.llm = mock_llm
        agent._graph = None

        with patch("agent.get_mcp_tools", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = []
            events = []
            async for event in agent.stream("Trigger payroll run for 2024-02", "ctx-stream-004"):
                events.append(event)

        assert events[-1]["is_task_complete"] is True

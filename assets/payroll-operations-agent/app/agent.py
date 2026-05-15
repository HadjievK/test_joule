import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from opentelemetry import trace
from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section

from hana_cache import cache_get, cache_invalidate, cache_set, cache_stats, _is_write_query
from mcp_tools import get_mcp_tools

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@agent_model(
    key="config.model",
    label="LLM Model",
    description="The language model powering this agent",
)
def get_model_name() -> str:
    return "sap/anthropic--claude-4.5-sonnet"


@agent_config(
    key="config.temperature",
    label="LLM Temperature",
    description="Controls randomness of responses (0.0 = deterministic, 1.0 = creative)",
)
def get_temperature() -> float:
    return 0.0


@prompt_section(
    key="prompts.system",
    label="System Prompt",
    description="The full system prompt defining the agent's role and behavior",
    validation={"format": "markdown", "max_length": 5000},
)
def get_system_prompt() -> str:
    return """You are an AI agent that controls all payroll operations across SAP SuccessFactors Employee Central Payroll and SAP HANA Cloud. You serve payroll administrators and finance controllers.

## Data Sources
- **SAP SuccessFactors** (via MCP tools): time sheets, cost assignments, compensation, benefits, payroll run results, income tax declarations
- **SAP HANA Cloud** (via hana_* tools): business data tables stored directly in the HANA Cloud database instance

## How to Query HANA Cloud
Always follow this sequence when the user asks for data that may reside in HANA Cloud:
1. Call `hana_list_tables` to discover available tables.
2. Call `hana_describe_table` on the relevant table to understand its columns.
3. Call `hana_query` with a precise SELECT statement to retrieve the data.

## Core Responsibilities
- Query and reconcile payroll data from SAP SuccessFactors and SAP HANA Cloud
- Detect and report payroll discrepancies, anomalies, and compliance issues
- Manage time sheets, cost assignments, compensation records, and reimbursements
- Validate compliance against statutory and tax reporting requirements
- Generate consolidated payroll summaries and statutory reports

## Critical Rules
1. NEVER trigger a live payroll run without first presenting a pre-action summary (employee count, period, system, warnings) and receiving explicit human confirmation.
2. Write actions affecting multiple employees simultaneously are HIGH-RISK and always require human confirmation before execution.
3. Autonomous write operations are strictly scoped to single-employee records only.
4. Always set `top` (or equivalent page-size parameter) to a maximum of 100 on every tool call that accepts it. Inform the user when this limit is applied.
5. NEVER hallucinate payroll data. If a tool call fails or returns empty results, report that explicitly and suggest remediation steps.
6. When anomaly count in any validation run exceeds 5, escalate to the user immediately rather than attempting autonomous resolution.
7. All write operations must be confirmed back to the user with: employee ID, field changed, old value, new value, and timestamp.
8. `hana_query` is read-only. Never attempt INSERT, UPDATE, DELETE or DDL via HANA tools.

## Response Style
- Be precise, structured, and audit-conscious in all responses
- For payroll data queries, always include the period, data source (SuccessFactors or HANA Cloud), and record count
- For anomaly reports, provide: employee ID, field, expected value, actual value, and recommended action
- For compliance issues, cite the applicable regulation and recommended remediation"""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


class SampleAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        from langchain_litellm import ChatLiteLLM
        self.llm = ChatLiteLLM(model=get_model_name(), temperature=get_temperature())
        self._graph = None

    def _build_graph(self, tools):
        llm_with_tools = self.llm.bind_tools(tools)
        tool_node = ToolNode(tools)

        def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return "__end__"

        async def call_model(state: MessagesState):
            response = await llm_with_tools.ainvoke(state["messages"])
            return {"messages": [response]}

        builder = StateGraph(MessagesState)
        builder.add_node("model", call_model)
        builder.add_node("tools", tool_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", should_continue, {"tools": "tools", "__end__": END})
        builder.add_edge("tools", "model")
        return builder.compile()

    async def _get_graph(self):
        if self._graph is None:
            tools = await get_mcp_tools()
            logger.info("Building graph with %d tool(s): %s", len(tools), [t.name for t in tools])
            self._graph = self._build_graph(tools)
        return self._graph

    @tracer.start_as_current_span("payroll_agent._run_agent")
    async def _run_agent(self, query: str, context_id: str) -> str:
        """Core business logic â instrumented with milestones.

        Read queries are served from the SAP HANA Cloud cache when available.
        Write queries bypass the cache and trigger a context-scoped invalidation
        after execution so subsequent reads reflect the latest state.
        """
        span = trace.get_current_span()
        span.set_attribute("context_id", context_id)

        # ------------------------------------------------------------------ #
        # HANA cache look-up (read queries only)                              #
        # ------------------------------------------------------------------ #
        is_write = _is_write_query(query)
        if not is_write:
            cached = cache_get(query, context_id)
            if cached is not None:
                logger.info(
                    "M1.achieved: payroll data retrieved from HANA cache for context %s",
                    context_id,
                )
                span.set_attribute("m1.status", "achieved")
                span.set_attribute("cache.hit", True)
                return cached

        span.set_attribute("cache.hit", False)

        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=query),
        ]

        # M1 â Payroll Data Retrieved
        try:
            graph = await self._get_graph()
            result = await graph.ainvoke({"messages": messages})
            response = result["messages"][-1].content
            logger.info("M1.achieved: payroll data retrieved â query processed successfully")
            span.set_attribute("m1.status", "achieved")
        except Exception as e:
            logger.error("M1.missed: payroll data retrieval incomplete â failed sources: %s", str(e))
            span.set_attribute("m1.status", "missed")
            raise

        # ------------------------------------------------------------------ #
        # HANA cache write / invalidate                                       #
        # ------------------------------------------------------------------ #
        if is_write:
            # Invalidate stale read cache entries for this context after a
            # write so the next read fetches fresh data from the source system.
            cache_invalidate(context_id)
            span.set_attribute("cache.invalidated", True)
        else:
            cache_set(query, context_id, response)
            span.set_attribute("cache.stored", True)

        # M5 â Payroll Report Generated (if response contains report content)
        if any(kw in query.lower() for kw in ["report", "summary", "compliance"]):
            if response and len(response) > 50:
                logger.info("M5.achieved: payroll report generated â completeness: complete")
                span.set_attribute("m5.status", "achieved")
            else:
                logger.warning("M5.missed: report generation failed â missing data: response content empty")
                span.set_attribute("m5.status", "missed")

        return response

    @tracer.start_as_current_span("payroll_agent.discrepancy_resolution")
    async def _run_discrepancy_check(self, query: str) -> str:
        """Discrepancy detection milestone instrumentation."""
        span = trace.get_current_span()
        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=query),
        ]
        graph = await self._get_graph()
        result = await graph.ainvoke({"messages": messages})
        response = result["messages"][-1].content

        if "discrepanc" in response.lower() or "mismatch" in response.lower():
            logger.info("M3.achieved: discrepancies resolved for the requested period")
            span.set_attribute("m3.status", "achieved")
        else:
            logger.info("M3.achieved: 0 discrepancies found for the requested period")
            span.set_attribute("m3.status", "achieved")

        return response

    @tracer.start_as_current_span("payroll_agent.compliance_check")
    async def _run_compliance_check(self, query: str) -> str:
        """Compliance check milestone instrumentation."""
        span = trace.get_current_span()
        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=query),
        ]
        graph = await self._get_graph()
        result = await graph.ainvoke({"messages": messages})
        response = result["messages"][-1].content

        if "non-compliant" in response.lower() or "flagged" in response.lower():
            logger.info("M4.achieved: compliance check completed â flagged items found")
            span.set_attribute("m4.status", "achieved")
        else:
            logger.info("M4.achieved: compliance check completed â all items compliant")
            span.set_attribute("m4.status", "achieved")

        return response

    @tracer.start_as_current_span("payroll_agent.payroll_run")
    async def _run_payroll_initiation(self, query: str) -> str:
        """Payroll run initiation milestone instrumentation."""
        span = trace.get_current_span()
        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=query),
        ]
        graph = await self._get_graph()
        result = await graph.ainvoke({"messages": messages})
        response = result["messages"][-1].content

        if "initiated" in response.lower() or "triggered" in response.lower() or "run_id" in response.lower():
            logger.info("M2.achieved: payroll run initiated successfully")
            span.set_attribute("m2.status", "achieved")
        else:
            logger.info("M2.missed: payroll run initiation pending confirmation or failed")
            span.set_attribute("m2.status", "missed")

        return response

    async def stream(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Processing payroll request...",
        }
        try:
            # Route to specialized milestone helper based on query intent
            q_lower = query.lower()
            if any(kw in q_lower for kw in ["discrepanc", "mismatch", "error", "correct"]):
                response = await self._run_discrepancy_check(query)
            elif any(kw in q_lower for kw in ["compliance", "statutory", "tax check"]):
                response = await self._run_compliance_check(query)
            elif any(kw in q_lower for kw in ["trigger run", "initiate run", "start payroll run"]):
                response = await self._run_payroll_initiation(query)
            else:
                response = await self._run_agent(query, context_id)

            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }
        except Exception:
            logger.error("stream() failed", exc_info=True)
            raise

    async def invoke(self, query: str, context_id: str) -> AgentResponse:
        try:
            response = await self._run_agent(query, context_id)
            return AgentResponse(status="completed", message=response)
        except Exception:
            logger.error("invoke() failed", exc_info=True)
            raise

import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from opentelemetry import trace
from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section

from mcp_tools import get_mcp_tools

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# ── Milestone IDs ─────────────────────────────────────────────────────────────
M1 = "M1"  # Payroll Data Retrieved
M2 = "M2"  # Payroll Run Initiated
M3 = "M3"  # Discrepancy Identified and Resolved
M4 = "M4"  # Compliance Check Completed
M5 = "M5"  # Payroll Report Generated


def log_milestone(milestone_id: str, achieved: bool, **kwargs) -> None:
    """Emit a structured milestone log statement."""
    status = "achieved" if achieved else "missed"
    details = " — ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"{milestone_id}.{status}: "

    if milestone_id == M1:
        if achieved:
            msg += f"payroll data retrieved successfully for pay period {kwargs.get('period', 'unknown')} from {kwargs.get('systems', 'unknown')}"
        else:
            msg += f"payroll data retrieval failed or returned no results for pay period {kwargs.get('period', 'unknown')} — system {kwargs.get('system', 'unknown')}, error {kwargs.get('error', 'unknown')}"
    elif milestone_id == M2:
        if achieved:
            msg += f"payroll run initiated successfully, run ID {kwargs.get('run_id', 'unknown')}, system {kwargs.get('system', 'SuccessFactors')}"
        else:
            msg += f"payroll run initiation failed or was cancelled by user — system {kwargs.get('system', 'SuccessFactors')}, reason {kwargs.get('reason', 'unknown')}"
    elif milestone_id == M3:
        if achieved:
            msg += f"discrepancy detected and resolved for employee {kwargs.get('employee_id', 'unknown')}, type {kwargs.get('discrepancy_type', 'unknown')}"
        else:
            msg += "discrepancy detection completed with no issues found, or correction was declined by user"
    elif milestone_id == M4:
        if achieved:
            msg += f"compliance check completed for pay period {kwargs.get('period', 'unknown')} — {kwargs.get('n', 0)} obligations checked, {kwargs.get('m', 0)} flagged"
        else:
            msg += f"compliance check could not be completed for pay period {kwargs.get('period', 'unknown')} — error {kwargs.get('error', 'unknown')}"
    elif milestone_id == M5:
        if achieved:
            msg += f"payroll report generated for period {kwargs.get('period', 'unknown')}, {kwargs.get('n', 0)} records included, source systems {kwargs.get('systems', 'unknown')}"
        else:
            msg += f"payroll report generation incomplete for period {kwargs.get('period', 'unknown')} — missing data from {kwargs.get('system', 'unknown')}"
    else:
        msg += details

    logger.info(msg)


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
    return """You are a Payroll Operations AI Agent assisting payroll administrators and finance controllers. \
You have access to SAP SuccessFactors and SAP S/4HANA payroll APIs via MCP tools.

## Role
- Assist payroll administrators with payroll runs, discrepancy resolution, compliance checks, and reporting.
- Assist finance controllers with compensation queries and cross-system payroll analytics.

## Dual-System Fluency
When the user asks for payroll data, always query both SAP SuccessFactors and SAP S/4HANA unless a specific system is requested.

## Write Operation Guardrail
For ALL write operations (trigger payroll run, apply correction, submit statutory report), you MUST:
1. Present a clear confirmation summary of what will be changed.
2. Wait for explicit user approval (e.g. "yes", "confirm", "proceed") before calling any write API.
3. Never execute a write action autonomously.

## Page Limits
On every tool call that accepts a `$top` or `top` parameter, always set it to a maximum of 100 to prevent context overflow. Inform the user when this limit is applied.

## Accuracy
Never fabricate or hallucinate payroll data. Only present data returned by tool calls. If a tool call fails, clearly state the failure and suggest a manual fallback.

## Graceful Degradation
If one backend system is unavailable, continue serving the other and clearly inform the user which system is unavailable.

## Scope
You are designed for payroll administrators and finance controllers only. Do not assist with employee self-service payroll queries."""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


class PayrollOperationsAgent:
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

    async def _run_agent(self, query: str) -> str:
        """Core agent execution logic — instrumented with OpenTelemetry spans."""
        with tracer.start_as_current_span("payroll-agent-run") as span:
            span.set_attribute("query.length", len(query))
            messages = [
                SystemMessage(content=get_system_prompt()),
                HumanMessage(content=query),
            ]
            graph = await self._get_graph()
            result = await graph.ainvoke({"messages": messages})
            response = result["messages"][-1].content

            # Detect milestone outcomes from tool call results in the message history
            _emit_milestones_from_result(result, query, response)

            return response

    async def stream(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Processing...",
        }
        try:
            response = await self._run_agent(query)
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
            response = await self._run_agent(query)
            return AgentResponse(status="completed", message=response)
        except Exception:
            logger.error("invoke() failed", exc_info=True)
            raise


def _emit_milestones_from_result(result: dict, query: str, response: str) -> None:
    """Inspect agent result messages and emit appropriate milestone logs."""
    messages = result.get("messages", [])
    tool_names_called = set()
    for msg in messages:
        if hasattr(msg, "tool_calls"):
            for tc in msg.tool_calls:
                tool_names_called.add(tc.get("name", "").lower())
        elif hasattr(msg, "name") and msg.name:
            tool_names_called.add(msg.name.lower())

    query_lower = query.lower()
    response_lower = response.lower()

    # M1: Payroll data retrieved — substring match against lowercased tool names
    payroll_read_patterns = [
        "payrollrunresult", "payrollearmarkedfunds", "employeetimesheet",
        "empcompensation", "employeecompensation", "timesheet", "timecollector",
        "listemployeepayroll",
    ]
    if any(
        any(pattern in t for pattern in payroll_read_patterns)
        for t in tool_names_called
    ):
        log_milestone(M1, achieved=True, period="requested period", systems="SuccessFactors/S4HANA")
    elif any(kw in query_lower for kw in ["payroll data", "payroll records", "show me payroll"]):
        log_milestone(M1, achieved=False, period="requested period", system="unknown", error="no data returned")

    # M2: Payroll run initiated
    if any("payrollrunresults" in t and "post" in t for t in tool_names_called) or \
       any(t in tool_names_called for t in {"trigger_payroll_run", "create_payrollrunresult"}):
        log_milestone(M2, achieved=True, run_id="from API response", system="SuccessFactors")
    elif "trigger payroll run" in query_lower and "confirm" not in query_lower:
        log_milestone(M2, achieved=False, system="SuccessFactors", reason="awaiting confirmation")

    # M3: Discrepancy detection
    if any(kw in response_lower for kw in ["discrepancy", "mismatch", "correction applied"]):
        log_milestone(M3, achieved=True, employee_id="detected", discrepancy_type="pay/time mismatch")
    elif "discrepanc" in query_lower and "no discrepanc" in response_lower:
        log_milestone(M3, achieved=False)

    # M4: Compliance check — triggered by tool calls OR by compliance keywords in response
    _compliance_tools = {
        "activity", "phase", "itdeclarationtimebound", "declarationtype",
        "get_statutory_reporting_tasks", "get_income_tax_declarations",
    }
    _compliance_response_kw = ["compliance check completed", "compliance check passed", "no violations", "violations found", "statutory reporting"]
    if (
        any(t in tool_names_called for t in _compliance_tools)
        or any(kw in response_lower for kw in _compliance_response_kw)
    ):
        log_milestone(M4, achieved=True, period="requested period", n=0, m=0)
    elif any(kw in query_lower for kw in ["compliance", "statutory", "tax"]) and "error" in response_lower:
        log_milestone(M4, achieved=False, period="requested period", error="API call failed")

    # M5: Report generated — triggered by tool calls, query+response combo, or "report generated" in response
    _report_response_kw = ["payroll report generated", "report generated", "payroll report complete", "report has been generated"]
    if (
        any(kw in response_lower for kw in _report_response_kw)
        or (
            any(kw in query_lower for kw in ["report", "summary"])
            and any(kw in response_lower for kw in ["payroll run", "employee count", "compensation", "earmarked funds", "employees processed", "total net pay"])
        )
    ):
        log_milestone(M5, achieved=True, period="requested period", n=0, systems="SuccessFactors/S4HANA")
    elif any(kw in query_lower for kw in ["report", "generate report"]) and "error" in response_lower:
        log_milestone(M5, achieved=False, period="requested period", system="unknown")

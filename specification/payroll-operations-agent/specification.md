# Specification: payroll-operations-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [ ] Read the project input (`product-requirements-document.md` and `intent.md`)
- [ ] Bootstrap agent code in `assets/payroll-operations-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/payroll-operations-agent/`, use copy commands — do NOT create files manually)
- [ ] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## API Integration — MCP Translation

> All SAP API interactions MUST go through MCP tools. No direct HTTP clients allowed.

- [ ] Verify `specification/payroll-operations-agent/api-specs/` contains the following 7 downloaded spec files:
  - `employee-central-payroll.json` — ORD ID: `sap.sf:apiResource:ECEmployeeCentralPayroll:v1`
  - `payroll-time-sheet.json` — ORD ID: `sap.sf:apiResource:ECPayrollTimeSheets:v1`
  - `compensation-information.json` — ORD ID: `sap.sf:apiResource:ECCompensationInformation:v1`
  - `compensation-management.json` — ORD ID: `sap.sf:apiResource:employeeCompensation:v1`
  - `income-tax-declaration.json` — ORD ID: `sap.sf:apiResource:ECIncomeTaxDeclaration:v1`
  - `payroll-earmarked-funds.json` — ORD ID: `sap.s4:apiResource:CE_PAYROLLEARMARKEDFUNDSDOC_0001:v1`
  - `statutory-reporting-task.json` — ORD ID: `sap.s4:apiResource:CE_STATUTORYREPORTINGTASK_0001:v1`
- [ ] Invoke `mcp-translation-file` skill for each API spec file above to generate MCP translation files and server cards
- [ ] Invoke `setup-solution` skill to register generated MCP server assets in `solution.yaml`
- [ ] Record MCP server names and ORD IDs for wiring into agent `asset.yaml`

## Agent Tools

Wire all SAP API interactions through MCP tools loaded via `get_mcp_tools()`. Never hard-code tool names. Implement the following tool-backed capabilities:

### REQ-01 — Payroll Data Query (M1)
- [ ] Implement `get_payroll_records` tool logic:
  - MCP call to `EmployeePayrollRunResults` (GET `/EmployeePayrollRunResults`) in `employee-central-payroll` — filter by pay period date range and optional employee ID; set `$top=100` on all list calls
  - MCP call to `EmployeePayrollRunResultsItems` (GET `/EmployeePayrollRunResultsItems`) to retrieve line-item detail
  - MCP call to `PayrollEarmarkedFundsDoc` (GET `/PayrollEarmarkedFundsDoc`) in `payroll-earmarked-funds` — retrieve S/4HANA payroll earmarked funds for the same period
  - Merge and present consolidated cross-system payroll summary to the user
  - Emit `M1.achieved` log when at least one non-empty result set is returned; emit `M1.missed` if all calls return empty or error

- [ ] Implement `get_time_sheets` tool logic:
  - MCP call to `EmployeeTimeSheet` (GET `/EmployeeTimeSheet`) in `payroll-time-sheet` — filter by employee and date; set `$top=100`
  - MCP call to `TimeCollector` (GET `/TimeCollector`) for aggregated time data
  - Return structured list of time sheet entries per employee

- [ ] Implement `get_compensation_info` tool logic:
  - MCP call to `EmpCompensation` (GET `/EmpCompensation?$expand=empCompensationCalculatedNav`) in `compensation-information`
  - MCP call to `EmpPayCompRecurring` (GET `/EmpPayCompRecurring`) for recurring pay components
  - Accept filter by userId, department, or cost centre; set `$top=100`

- [ ] Implement `get_employee_compensation` tool logic:
  - MCP call to `employeeCompensations` (GET `/employeeCompensations`) in `compensation-management`
  - Support filtering by employee ID or department

### REQ-02 — Payroll Run Initiation (M2)
- [ ] Implement `trigger_payroll_run` tool logic:
  - Before calling the API, the agent MUST present a confirmation summary to the user and await explicit approval
  - On approval: MCP call to POST `/EmployeePayrollRunResults` in `employee-central-payroll` with validated run parameters
  - Return run ID, status, and next steps from the API response
  - Emit `M2.achieved` log on successful API response with run ID; emit `M2.missed` if cancelled by user or API call fails

### REQ-03 — Payroll Discrepancy Detection and Resolution (M3)
- [ ] Implement discrepancy detection logic in the agent's reasoning layer:
  - After `get_payroll_records` and `get_time_sheets` are called, compare time sheet hours/amounts against payroll run results for each employee
  - Identify mismatches: hours discrepancy, pay amount mismatch, missing time records
  - Return discrepancy list with: employee ID, discrepancy type, expected value, actual value, magnitude
  - Emit `M3.achieved` log when at least one discrepancy is found and surfaced or resolved; emit `M3.missed` when no discrepancies found or resolution declined

- [ ] Implement `apply_payroll_correction` tool logic:
  - Present proposed correction to user and await explicit confirmation before executing
  - On approval: MCP call to PUT `/EmployeePayrollRunResults(...)` in `employee-central-payroll` with corrected values
  - On approval for time record correction: MCP call to PUT `/ExternalTimeRecord('{externalCode}')` in `payroll-time-sheet`
  - Return updated record confirmation

### REQ-04 — Statutory Compliance Check (M4)
- [ ] Implement `get_statutory_reporting_tasks` tool logic:
  - MCP call to `Activity` (GET `/Activity`) in `statutory-reporting-task` — list all statutory reporting activities; set `$top=100`
  - MCP call to `Phase` (GET `/Phase`) to retrieve reporting phase status
  - Identify overdue or non-compliant activities (past due date, status not complete)
  - Return compliance status per obligation with regulation reference

- [ ] Implement `get_income_tax_declarations` tool logic:
  - MCP call to `ItDeclarationTimeBound` (GET `/ItDeclarationTimeBound`) in `income-tax-declaration` — retrieve time-bound declarations
  - MCP call to `DeclarationType` (GET `/DeclarationType`) to enrich with declaration type metadata
  - Flag missing or overdue declarations
  - Emit `M4.achieved` log when compliance check completes and status is returned; emit `M4.missed` on API failure

### REQ-05 — Payroll Report Generation (M5)
- [ ] Implement report generation logic in the agent's reasoning layer:
  - Orchestrate sequential calls: `get_payroll_records` → `get_time_sheets` → `get_compensation_info` → `get_statutory_reporting_tasks`
  - Aggregate into a structured payroll summary report:
    - Total payroll run count and status for the period
    - Employee count processed
    - Total compensation amount (from compensation data)
    - Earmarked funds total (from S/4HANA)
    - Statutory compliance summary (obligations checked / flagged)
  - Present report as a formatted response with section headers
  - Emit `M5.achieved` log when report is successfully compiled and returned; emit `M5.missed` when data from one or more systems is unavailable

### REQ-06 — Compensation Query (Finance Controller)
- [ ] Implement `get_benefits` tool logic:
  - MCP call to `OneTimeDeduction` (GET `/OneTimeDeduction`) in `compensation-information` for one-time deductions
  - MCP call to `RecurringDeductionItem` (GET `/RecurringDeductionItem`) for recurring deductions
  - Filter by employee ID or organisational unit

## Agent System Prompt

- [ ] Configure system prompt in `app/agent.py` `@prompt_section` with the following instructions:
  - Role: "You are a Payroll Operations AI Agent assisting payroll administrators and finance controllers. You have access to SAP SuccessFactors and SAP S/4HANA payroll APIs."
  - Dual-system fluency: "When the user asks for payroll data, always query both SAP SuccessFactors and SAP S/4HANA unless a specific system is requested."
  - Confirmation guardrail: "For ALL write operations (trigger payroll run, apply correction, submit report), you MUST present a confirmation summary and wait for explicit user approval before calling any write API."
  - Page limit: "On every tool call that accepts a `$top` or `top` parameter, always set it to a maximum of 100 to prevent context overflow. Inform the user when this limit is applied."
  - Accuracy: "Never fabricate or hallucinate payroll data. Only present data returned by tool calls. If a tool call fails, clearly state the failure and suggest a manual fallback."
  - Graceful degradation: "If one backend system is unavailable, continue serving the other and clearly inform the user which system is unavailable."
  - Scope: "You are designed for payroll administrators and finance controllers only. Do not assist with employee self-service payroll queries."

## Business Step Instrumentation

- [ ] Implement OpenTelemetry instrumentation for all 5 milestones. Extract business logic from `stream()` into a `_run_agent()` async helper; instrument that helper using decorator or context-manager form — NEVER use `with tracer.start_as_current_span(...)` inside an async generator:

  | ID | Span name | Log on achieved | Log on missed |
  |----|-----------|-----------------|---------------|
  | M1 | `payroll-data-retrieved` | `M1.achieved: payroll data retrieved successfully for pay period {period} from {systems}` | `M1.missed: payroll data retrieval failed or returned no results for pay period {period} — system {system}, error {error}` |
  | M2 | `payroll-run-initiated` | `M2.achieved: payroll run initiated successfully, run ID {run_id}, system {system}` | `M2.missed: payroll run initiation failed or was cancelled by user — system {system}, reason {reason}` |
  | M3 | `discrepancy-identified-resolved` | `M3.achieved: discrepancy detected and resolved for employee {employee_id}, type {discrepancy_type}` | `M3.missed: discrepancy detection completed with no issues found, or correction was declined by user` |
  | M4 | `compliance-check-completed` | `M4.achieved: compliance check completed for pay period {period} — {n} obligations checked, {m} flagged` | `M4.missed: compliance check could not be completed for pay period {period} — error {error}` |
  | M5 | `payroll-report-generated` | `M5.achieved: payroll report generated for period {period}, {n} records included, source systems {systems}` | `M5.missed: payroll report generation incomplete for period {period} — missing data from {system}` |

- [ ] Verify `auto_instrument()` is called at top of `main.py` before any AI framework imports

## agent.yaml Requirements

- [ ] Add `requires` entries in `assets/payroll-operations-agent/asset.yaml` for every MCP server generated by `mcp-translation-file`:
  ```yaml
  requires:
    - name: <mcp-server-name-ecpayroll>
      kind: mcp-server
      ordId: <ord-id>
    - name: <mcp-server-name-timesheet>
      kind: mcp-server
      ordId: <ord-id>
    # ... one entry per MCP server asset
  ```

## Generate Mock Config

- [ ] After `mcp-translation-file` and `setup-solution` are complete, invoke `mcp-mock-config` skill to generate `mcp-mock.json` with realistic payroll mock data:
  - `EmployeePayrollRunResults`: 2–3 mock run records with externalCode, status, pay period, amount
  - `EmployeeTimeSheet`: 2 mock time sheet entries with hours worked
  - `EmpCompensation`: 1–2 mock compensation records with base salary and currency
  - `PayrollEarmarkedFundsDoc`: 1 mock fund document with amount and status
  - `Activity` (statutory): 2 mock activities — one compliant, one overdue
  - `ItDeclarationTimeBound`: 1 mock declaration record

## Testing

- [ ] `conftest.py` only sets `IBD_TESTING=true`
- [ ] Write unit tests in `assets/payroll-operations-agent/tests/` — one per tool:
  - `test_get_payroll_records.py` — mock MCP tools returning payroll run results; assert consolidated cross-system summary returned
  - `test_get_time_sheets.py` — mock time sheet MCP response; assert employee time entries returned
  - `test_get_compensation_info.py` — mock compensation MCP response; assert compensation data parsed correctly
  - `test_get_employee_compensation.py` — mock compensation management response; assert filter by employee applied
  - `test_trigger_payroll_run.py` — mock write MCP tool; assert confirmation is requested before API call; assert run ID returned on approval
  - `test_apply_payroll_correction.py` — mock write MCP tool; assert correction summary shown; assert PUT call made only after confirmation
  - `test_get_statutory_reporting_tasks.py` — mock statutory activity response; assert overdue items flagged
  - `test_get_income_tax_declarations.py` — mock income tax MCP response; assert declaration status returned
  - `test_get_benefits.py` — mock deductions MCP response; assert deduction items returned
  - `test_discrepancy_detection.py` — provide mock payroll and time sheet data with deliberate mismatch; assert discrepancy list returned with correct fields
  - `test_payroll_report.py` — mock all tool responses; assert report contains all 5 sections (run count, employee count, compensation, earmarked funds, compliance)
  - Run each test immediately after writing it
- [ ] Write one integration test `tests/test_integration.py`:
  - Mock LLM (patch `ChatLiteLLM`) and mock MCP tools
  - Invoke agent `invoke` function with "Show me payroll data for March 2026"
  - Assert agent calls `get_payroll_records` and returns a non-empty consolidated response
- [ ] Run `pytest` from `assets/payroll-operations-agent/` (no args) — fix failures before proceeding
- [ ] Verify `grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/payroll-operations-agent/app/agent.py` returns 3
- [ ] Ensure coverage ≥ 70%; add targeted tests if below threshold
- [ ] Run final `pytest` from `assets/payroll-operations-agent/` (no args) to generate `test_report.json`
- [ ] Verify `assets/payroll-operations-agent/test_report.json` exists

## Agent Evaluation (Post-Testing)

- [ ] Invoke `sap-aeval-generate-tool-schema` skill from `assets/payroll-operations-agent/` to generate `tools.json`
- [ ] Invoke `sap-aeval-generate-testcase` skill with `specification/payroll-operations-agent/specification.md` and `tools.json` to generate `aeval/eval.yaml` and test cases in `aeval/testcases/`
- [ ] Review generated test cases; replace all placeholder values with realistic payroll data (pay periods, employee IDs, amounts)

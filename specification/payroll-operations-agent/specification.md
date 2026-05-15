# Specification: payroll-operations-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [x] Read `product-requirements-document.md` and `intent.md`
- [x] Bootstrap agent code in `assets/payroll-operations-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/payroll-operations-agent/`, use copy commands â do NOT create files manually)
- [x] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## Agent Identity & System Prompt

- [x] Set agent name to `Payroll Operations Agent` and description to `AI agent that controls all payroll operations across SAP SuccessFactors Employee Central Payroll and SAP S/4HANA â including payroll data retrieval, run initiation, discrepancy detection and resolution, compliance validation, and report generation.`
- [x] Write system prompt under `@prompt_section` in `app/agent.py`:
  - The agent serves payroll administrators and finance controllers; it must be precise, structured, and audit-conscious in all responses
  - The agent MUST NEVER trigger a live payroll run or cancel an S/4HANA run without first presenting a pre-action summary and receiving explicit human confirmation
  - Write actions affecting multiple employees simultaneously are high-risk and always require human confirmation
  - Always set `top` (or equivalent page-size) to a maximum of 100 on every tool call that accepts it; inform the user when this limit is applied
  - Never hallucinate payroll data â if a tool call fails or returns empty, report that explicitly and suggest remediation
  - When anomaly count in any validation exceeds 5, escalate to the user immediately rather than attempting autonomous resolution
  - All write operations must be confirmed back to the user with: employee ID, field changed, old value, new value, and timestamp

## MCP Tool Integration

- [x] Verify `specification/payroll-operations-agent/api-specs/` contains all 9 spec files:
  - `employee-central-payroll.json` (`sap.sf:apiResource:ECEmployeeCentralPayroll:v1`)
  - `payroll-time-sheets.json` (`sap.sf:apiResource:ECPayrollTimeSheets:v1`)
  - `employee-cost-assignment.json` (`sap.sf:apiResource:EmpCostAssignment:v1`)
  - `income-tax-declaration.json` (`sap.sf:apiResource:ECIncomeTaxDeclaration:v1`)
  - `global-benefits.json` (`sap.sf:apiResource:ECGlobalBenefits:v1`)
  - `s4-payroll-earmarked-funds.json` (`sap.s4:apiResource:CE_PAYROLLEARMARKEDFUNDSDOC_0001:v1`)
  - `s4-statutory-reporting-task.json` (`sap.s4:apiResource:CE_STATUTORYREPORTINGTASK_0001:v1`)
  - `s4-retrieve-run-results.json` (`RetrieveRunResultAPI`)
  - `s4-cancel-run.json` (`CancelRunAPI`)
- [x] Invoke `mcp-translation-file` skill to generate MCP translation files and server cards from all 9 API spec files
- [x] Invoke `setup-solution` skill to create and register MCP server assets for each generated translation file
- [x] Wire MCP tool loading in `app/agent.py` using `get_mcp_tools()` from `mcp_tools.py` â follow the canonical lazy-load pattern from `guidelines-agent.md`; NEVER create direct HTTP clients (`requests`, `httpx`, OData clients)
- [x] After `mcp-translation-file` and `setup-solution` complete, invoke `mcp-mock-config` skill to generate `mcp-mock.json`

## REQ-01: Payroll Data Retrieval â Both Systems

- [x] Implement tool `get_sf_payroll_run_status`: queries `GET /EmployeePayrollRunResults` from `employee-central-payroll.json`; accepts optional `externalCode` and `mdfSystemEffectiveStartDate` filters
- [x] Implement tool `get_sf_payroll_run_items`: queries `GET /EmployeePayrollRunResultsItems` for line items of a given SF payroll run
- [x] Implement tool `get_s4_payroll_run_results`: queries S/4HANA payroll run results via `s4-retrieve-run-results.json`
- [x] Implement tool `get_s4_earmarked_funds`: queries `s4-payroll-earmarked-funds.json` for payroll earmarked funds documents; accepts fiscal year and company code filters
- [x] Agent logic: on cross-system status query, retrieve from both systems for the same period and return a unified summary (total employees, gross amounts, status per system)

## REQ-02: Payroll Run Initiation â Human Approval Required

- [x] Implement tool `trigger_sf_payroll_run`: posts a payroll run initiation to SuccessFactors Employee Central Payroll (write â MUST require human confirmation before execution)
- [x] Agent logic: before triggering, validate completeness of time sheets and absence of open anomalies; present a pre-run summary to the user listing employee count, period, system, and any warnings; wait for explicit confirmation before calling the tool

## REQ-03: Discrepancy Detection and Resolution

- [x] Implement tool `get_sf_payroll_run_items` (if not already done in REQ-01) for detailed item-level comparison
- [x] Implement tool `update_time_sheet_entry`: patches an existing time sheet entry via `payroll-time-sheets.json` (write â single employee scope)
- [x] Implement tool `create_time_sheet_entry`: posts a new time sheet entry via `payroll-time-sheets.json` (write â single employee scope)
- [x] Agent logic: cross-reference SF and S/4HANA payroll totals; flag discrepancies with: employee ID, field, SF value, S/4HANA value, delta; for single-employee corrections, apply autonomously and log; for multi-employee corrections, present list and require confirmation

## REQ-04: Compliance Validation â Both Systems

- [x] Implement tool `get_income_tax_declarations`: queries `GET` endpoints from `income-tax-declaration.json`; accepts employee ID and tax year filters
- [x] Implement tool `get_statutory_reporting_tasks`: queries `s4-statutory-reporting-task.json` for open statutory reporting tasks; accepts company code and due date filters
- [x] Agent logic: cross-check income tax declaration status against payroll deduction records; flag entries where declared tax differs from withheld tax; surface overdue statutory tasks with due date and responsible party

## REQ-05: Payroll Reporting â Cross-System Aggregation

- [x] Implement `generate_payroll_report` (local computation, no direct API call):
  - Accepts payroll period identifier
  - Aggregates: total headcount, gross payroll, total deductions, net payroll, anomaly count â from both systems
  - Includes compliance status summary (compliant count, flagged count) from REQ-04 results
  - Returns structured report labelled with period, generation timestamp, and completeness status

## REQ-06: Time Sheet Management

- [x] Implement tool `get_time_sheets`: queries `GET /EmployeeTimeSheet` from `payroll-time-sheets.json`; accepts employee ID and period filters
- [x] Implement tool `get_time_sheet_entries`: queries `GET /EmployeeTimeSheetEntry` for individual entries of a given time sheet
- [x] Implement tool `get_time_valuation_results`: queries `GET /EmployeeTimeValuationResult` for calculated time values and allowances
- [x] Agent logic: detect missing time sheets (employees in payroll scope with no submitted sheet) and zero-hour entries; surface as prioritised anomaly list

## REQ-07: Compensation & Cost Assignment Management

- [x] Implement tool `get_compensation_info`: queries compensation information via `employee-central-payroll.json` endpoints; accepts employee ID filter
- [x] Implement tool `get_cost_assignments`: queries `GET /EmpCostAssignment` from `employee-cost-assignment.json`; accepts employee ID and effective date filters
- [x] Implement tool `upsert_cost_assignment`: posts to `/upsert?purgeType=record` in `employee-cost-assignment.json` to create or update a cost assignment (write â single employee scope)
- [x] Implement tool `update_compensation_info`: patches compensation information for a single employee via `employee-central-payroll.json` write endpoints (write â single employee scope)
- [x] Agent logic: on update requests, retrieve current value first, present oldânew diff to user, apply, then log the change

## REQ-08: Expense Reimbursement Management

- [x] Implement tool `get_reimbursement_records`: queries reimbursement-related entities from `employee-central-payroll.json`; accepts employee ID and status filters
- [x] Implement tool `create_reimbursement_record`: posts a new reimbursement record (write â single employee scope); accepts employee ID, amount, currency, and expense type
- [x] Agent logic: confirm created record back to user with generated record ID and submitted field values

## REQ-09: Global Benefits Visibility

- [x] Implement tool `get_global_benefits`: queries benefit plan and enrollment entities from `global-benefits.json`; accepts employee ID and benefit type filters
- [x] Agent logic: surface active benefits per employee with benefit type, provider, coverage amount, and associated payroll deduction amount when available

## S/4HANA Run Cancellation â Human Approval Required

- [x] Implement tool `cancel_s4_payroll_run`: calls cancellation endpoint from `s4-cancel-run.json` (write â MUST require human confirmation)
- [x] Agent logic: before cancelling, retrieve current run status; present run ID, affected employee count, current status, and irreversibility warning; wait for explicit confirmation before calling the tool; log approver, timestamp, and run ID on completion

## Business Step Instrumentation (Milestones)

- [x] Extract all business logic from `stream()` into plain async helper `_run_agent()`; instrument that helper â NEVER wrap `yield` inside `with tracer.start_as_current_span(...)`
- [x] M1 â Payroll Data Retrieved:
  - Achieved: `M1.achieved: payroll data retrieved from [systems] for period [period_id] â [record_count] records`
  - Missed: `M1.missed: payroll data retrieval incomplete â failed sources: [source_list]`
- [x] M2 â Payroll Run Initiated:
  - Achieved: `M2.achieved: payroll run initiated in [system] for period [period_id] â run_id: [run_id]`
  - Missed: `M2.missed: payroll run initiation failed â reason: [error_detail]`
- [x] M3 â Discrepancy Identified and Resolved:
  - Achieved: `M3.achieved: [discrepancy_count] discrepancies resolved for period [period_id]`
  - Missed: `M3.missed: discrepancy resolution incomplete â [unresolved_count] items outstanding`
- [x] M4 â Compliance Check Completed:
  - Achieved: `M4.achieved: compliance check completed â [compliant_count] compliant, [flagged_count] flagged`
  - Missed: `M4.missed: compliance check incomplete â missing data: [field_list]`
- [x] M5 â Payroll Report Generated:
  - Achieved: `M5.achieved: payroll report generated for period [period_id] â completeness: [status]`
  - Missed: `M5.missed: report generation failed â missing data: [field_list]`
- [x] Add OpenTelemetry custom spans using `@tracer.start_as_current_span` decorator on each milestone helper method
- [x] Verify `auto_instrument()` is called at top of `main.py` before any AI framework imports

## Testing

- [x] `conftest.py` only sets `IBD_TESTING=true`
- [x] Write unit test for `get_sf_payroll_run_status`; run immediately
- [x] Write unit test for `get_sf_payroll_run_items`; run immediately
- [x] Write unit test for `get_s4_payroll_run_results`; run immediately
- [x] Write unit test for `get_s4_earmarked_funds`; run immediately
- [x] Write unit test for `trigger_sf_payroll_run` (verify confirmation gate blocks execution without approval); run immediately
- [x] Write unit test for `get_time_sheets`; run immediately
- [x] Write unit test for `get_time_sheet_entries`; run immediately
- [x] Write unit test for `update_time_sheet_entry`; run immediately
- [x] Write unit test for `create_time_sheet_entry`; run immediately
- [x] Write unit test for `get_income_tax_declarations`; run immediately
- [x] Write unit test for `get_statutory_reporting_tasks`; run immediately
- [x] Write unit test for `get_cost_assignments`; run immediately
- [x] Write unit test for `upsert_cost_assignment`; run immediately
- [x] Write unit test for `get_global_benefits`; run immediately
- [x] Write unit test for `cancel_s4_payroll_run` (verify confirmation gate blocks execution without approval); run immediately
- [x] Write unit test for `generate_payroll_report`; run immediately
- [x] Write one integration test: query payroll run status (both systems) â validate time sheets â run compliance check â generate report; mock LLM and all MCP tools
- [x] Run `pytest` from `assets/payroll-operations-agent/` (no args) â if coverage < 70%, add tests
- [x] Verify `app/agent.py` has exactly 3 decorated functions â run `grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/payroll-operations-agent/app/agent.py` and confirm output is 3
- [x] Run `pytest` again from `assets/payroll-operations-agent/` (no args) to produce final `test_report.json`
- [x] Verify `test_report.json` exists in `assets/payroll-operations-agent/`

## Validation

- [x] `grep -r "M[0-9]\.achieved" assets/payroll-operations-agent/app/` â must return results
- [x] `grep -r "sap_cloud_sdk.agent_decorators" assets/payroll-operations-agent/app/` â must return results
- [x] `grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/payroll-operations-agent/app/agent.py` â must return 3
- [x] `ls assets/payroll-operations-agent/test_report.json` â must exist

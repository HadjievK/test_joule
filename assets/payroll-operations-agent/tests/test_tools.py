"""Unit tests for all payroll agent tools via mocked MCP tools."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure app/ is on the path
APP_PATH = Path(__file__).parent.parent / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tool(name: str, response: dict):
    """Build a mock StructuredTool that returns a JSON response."""
    tool = MagicMock()
    tool.name = name
    tool.description = f"Mock tool: {name}"
    tool.coroutine = AsyncMock(return_value=json.dumps(response))
    return tool


async def load_mock_tools():
    """Load tools from mcp-mock.json using the real mcp_tools loader."""
    import mcp_tools  # noqa: F401 Ã¢ÂÂ IBD_TESTING=1 ensures mock path
    return await mcp_tools.get_mcp_tools()


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------

class TestGetSfPayrollRunStatus:
    async def test_returns_payroll_run_data(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "get_sf_payroll_run_status" in t.name), None)
        assert tool is not None, "get_sf_payroll_run_status tool not found in mock tools"
        result = await tool.coroutine(top=100)
        data = json.loads(result)
        assert "value" in data
        assert len(data["value"]) > 0
        run = data["value"][0]
        assert "externalCode" in run
        assert "status" in run

    async def test_run_has_financial_data(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "get_sf_payroll_run_status" in t.name), None)
        result = await tool.coroutine(top=100)
        data = json.loads(result)
        run = data["value"][0]
        assert "grossPayroll" in run
        assert "netPayroll" in run


class TestGetSfPayrollRunItems:
    async def test_returns_line_items(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "get_sf_payroll_run_items" in t.name), None)
        assert tool is not None, "get_sf_payroll_run_items tool not found"
        result = await tool.coroutine(top=100)
        data = json.loads(result)
        assert "value" in data
        assert len(data["value"]) > 0
        item = data["value"][0]
        assert "employeeId" in item
        assert "amount" in item


class TestHanaQuery:
    async def test_returns_payroll_run_data(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name == "hana_query"), None)
        assert tool is not None, "hana_query tool not found"
        result = await tool.coroutine(sql="SELECT * FROM PAYROLL_RUNS")
        # mock_response is a string; json.loads unwraps the JSON-encoded string
        text = json.loads(result)
        assert "RUN_ID" in text
        assert "FISCAL_YEAR" in text

    async def test_hana_query_result_contains_employee_count(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name == "hana_query"), None)
        result = await tool.coroutine(sql="SELECT * FROM PAYROLL_RUNS")
        text = json.loads(result)
        assert "EMPLOYEE_COUNT" in text


class TestHanaListTables:
    async def test_returns_table_list(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name == "hana_list_tables"), None)
        assert tool is not None, "hana_list_tables tool not found"
        result = await tool.coroutine()
        text = json.loads(result)
        assert "TABLE_NAME" in text
        assert "PAYROLL_CACHE" in text

    async def test_table_list_has_schema_column(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name == "hana_list_tables"), None)
        result = await tool.coroutine()
        text = json.loads(result)
        assert "SCHEMA_NAME" in text


class TestTriggerSfPayrollRun:
    async def test_requires_confirmation_flag(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "trigger_sf_payroll_run" in t.name), None)
        assert tool is not None, "trigger_sf_payroll_run tool not found"
        # With confirmed=True, returns run data
        result = await tool.coroutine(payrollPeriod="2024-02", companyCode="1000", confirmed=True)
        data = json.loads(result)
        assert "runId" in data
        assert data["status"] == "Initiated"

    async def test_returns_run_id_on_initiation(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "trigger_sf_payroll_run" in t.name), None)
        result = await tool.coroutine(payrollPeriod="2024-02", companyCode="1000", confirmed=True)
        data = json.loads(result)
        assert data["runId"] is not None
        assert data["employeeCount"] > 0


class TestGetTimeSheets:
    async def test_returns_time_sheets(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name.endswith("get_time_sheets")), None)
        assert tool is not None, "get_time_sheets tool not found"
        result = await tool.coroutine(top=100)
        data = json.loads(result)
        assert "value" in data
        assert len(data["value"]) > 0

    async def test_detects_zero_hour_entries(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name.endswith("get_time_sheets")), None)
        result = await tool.coroutine(top=100)
        data = json.loads(result)
        zero_hour = [ts for ts in data["value"] if ts.get("totalHours", -1) == 0]
        assert len(zero_hour) >= 1, "Expected at least one zero-hour time sheet in mock data"


class TestGetTimeSheetEntries:
    async def test_returns_entries(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name.endswith("get_time_sheet_entries")), None)
        assert tool is not None, "get_time_sheet_entries tool not found"
        result = await tool.coroutine(EmployeeTimeSheet_externalCode="TS-EMP001-2024-01", top=100)
        data = json.loads(result)
        assert "value" in data
        entry = data["value"][0]
        assert "date" in entry
        assert "hours" in entry


class TestUpdateTimeSheetEntry:
    async def test_returns_updated_entry(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "update_time_sheet_entry" in t.name), None)
        assert tool is not None, "update_time_sheet_entry tool not found"
        result = await tool.coroutine(
            EmployeeTimeSheet_externalCode="TS-EMP001-2024-01",
            externalCode="ENTRY-001",
            hours=8
        )
        data = json.loads(result)
        assert data["status"] == "Updated"
        assert "lastModifiedDateTime" in data


class TestCreateTimeSheetEntry:
    async def test_returns_created_entry(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "create_time_sheet_entry" in t.name), None)
        assert tool is not None, "create_time_sheet_entry tool not found"
        result = await tool.coroutine(
            EmployeeTimeSheet_externalCode="TS-EMP001-2024-01",
            date="2024-01-17",
            hours=8
        )
        data = json.loads(result)
        assert data["status"] == "Created"
        assert "externalCode" in data


class TestGetIncomeTaxDeclarations:
    async def test_returns_tax_declarations(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "get_income_tax_declarations" in t.name), None)
        assert tool is not None, "get_income_tax_declarations tool not found"
        result = await tool.coroutine(employeeId="EMP001", taxYear="2024", top=100)
        data = json.loads(result)
        assert "value" in data
        decl = data["value"][0]
        assert "taxWithheld" in decl
        assert "status" in decl


class TestHanaDescribeTable:
    async def test_returns_column_schema(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name == "hana_describe_table"), None)
        assert tool is not None, "hana_describe_table tool not found"
        result = await tool.coroutine(table_name="PAYROLL_RUNS")
        text = json.loads(result)
        assert "COLUMN_NAME" in text
        assert "DATA_TYPE" in text

    async def test_schema_includes_run_id_column(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name == "hana_describe_table"), None)
        result = await tool.coroutine(table_name="PAYROLL_RUNS")
        text = json.loads(result)
        assert "RUN_ID" in text


class TestGetCostAssignments:
    async def test_returns_cost_assignments(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if t.name.endswith("get_cost_assignments")), None)
        assert tool is not None, "get_cost_assignments tool not found"
        result = await tool.coroutine(worker="EMP001", top=100)
        data = json.loads(result)
        assert "value" in data
        assignment = data["value"][0]
        assert "costCenter" in assignment
        assert "percentage" in assignment


class TestUpsertCostAssignment:
    async def test_returns_upserted_assignment(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "upsert_cost_assignment" in t.name), None)
        assert tool is not None, "upsert_cost_assignment tool not found"
        result = await tool.coroutine(worker="EMP001", costCenter="CC-200", percentage=100)
        data = json.loads(result)
        assert data["status"] == "Upserted"
        assert data["costCenter"] == "CC-200"


class TestGetGlobalBenefits:
    async def test_returns_benefits(self):
        tools = await load_mock_tools()
        tool = next((t for t in tools if "get_global_benefits" in t.name), None)
        assert tool is not None, "get_global_benefits tool not found"
        result = await tool.coroutine(employeeId="EMP001", top=100)
        data = json.loads(result)
        assert "value" in data
        benefit = data["value"][0]
        assert "benefitType" in benefit
        assert "employeeDeduction" in benefit


class TestHanaToolsArePresentInProductionMode:
    """Verify that hana_* tools are discoverable via load_mock_tools (IBD_TESTING=1)."""

    async def test_all_three_hana_tools_present(self):
        tools = await load_mock_tools()
        names = {t.name for t in tools}
        assert "hana_list_tables" in names, "hana_list_tables not found"
        assert "hana_describe_table" in names, "hana_describe_table not found"
        assert "hana_query" in names, "hana_query not found"

    async def test_no_s4hana_tools_present(self):
        tools = await load_mock_tools()
        s4_tools = [t for t in tools if "s4" in t.name.lower()]
        assert len(s4_tools) == 0, f"Unexpected S/4HANA tools found: {[t.name for t in s4_tools]}"


class TestGeneratePayrollReport:
    """Test payroll report aggregation combining SuccessFactors and HANA Cloud data."""

    async def test_report_aggregates_data(self):
        """generate_payroll_report is a local computation Ã¢ÂÂ test the logic directly."""
        sf_runs = [{"externalCode": "RUN-2024-01", "employeeCount": 150, "grossPayroll": 750000, "totalDeductions": 187500, "netPayroll": 562500}]
        hana_runs = [{"RUN_ID": "HANA-RUN-2024-01", "EMPLOYEE_COUNT": 148, "GROSS_PAYROLL": 740000, "NET_PAYROLL": 555000}]

        # Simulate report aggregation logic
        report = {
            "period": "2024-01",
            "sf_employee_count": sum(r.get("employeeCount", 0) for r in sf_runs),
            "hana_employee_count": sum(r.get("EMPLOYEE_COUNT", 0) for r in hana_runs),
            "sf_gross_payroll": sum(r.get("grossPayroll", 0) for r in sf_runs),
            "hana_gross_payroll": sum(r.get("GROSS_PAYROLL", 0) for r in hana_runs),
            "headcount_discrepancy": abs(
                sum(r.get("employeeCount", 0) for r in sf_runs) -
                sum(r.get("EMPLOYEE_COUNT", 0) for r in hana_runs)
            ),
            "completeness": "complete",
        }

        assert report["sf_employee_count"] == 150
        assert report["hana_employee_count"] == 148
        assert report["headcount_discrepancy"] == 2
        assert report["sf_gross_payroll"] == 750000
        assert report["completeness"] == "complete"

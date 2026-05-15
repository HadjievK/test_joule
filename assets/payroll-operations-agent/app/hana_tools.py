"""
SAP HANA Cloud direct-query tools for the Payroll Operations Agent.

Exposes three LangChain-compatible StructuredTools that allow the agent to
explore and query business data stored in the HANA Cloud instance configured
in hana_cache.py.

Tools:
  - hana_list_tables     : Discover all accessible tables / views
  - hana_describe_table  : Inspect columns, types and nullability of a table
  - hana_query           : Execute a read-only SELECT statement (max 200 rows)

Write operations (INSERT / UPDATE / DELETE / DDL) are explicitly blocked.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hana_cache import _HanaConnectionPool

logger = logging.getLogger(__name__)

_MAX_ROWS = 200
_WRITE_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|UPSERT|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def _get_conn():
    return _HanaConnectionPool.get_instance().get_connection()


# ---------------------------------------------------------------------------
# Tool: hana_list_tables
# ---------------------------------------------------------------------------

class _ListTablesInput(BaseModel):
    schema_name: Optional[str] = Field(
        default=None,
        description="Optional schema/owner name to filter tables. Leave empty to list all accessible tables.",
    )


def _list_tables(schema_name: Optional[str] = None) -> str:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        if schema_name:
            cur.execute(
                "SELECT SCHEMA_NAME, TABLE_NAME, TABLE_TYPE "
                "FROM SYS.TABLES "
                "WHERE SCHEMA_NAME = ? "
                "ORDER BY TABLE_NAME",
                (schema_name.upper(),),
            )
        else:
            cur.execute(
                "SELECT SCHEMA_NAME, TABLE_NAME, TABLE_TYPE "
                "FROM SYS.TABLES "
                "WHERE IS_SYSTEM_TABLE = 'FALSE' "
                "ORDER BY SCHEMA_NAME, TABLE_NAME"
            )
        rows = cur.fetchall()
        cur.close()
        if not rows:
            return "No accessible tables found."
        lines = ["SCHEMA_NAME | TABLE_NAME | TYPE"]
        lines += [f"{r[0]} | {r[1]} | {r[2]}" for r in rows]
        return "\n".join(lines)
    except Exception as exc:
        logger.error("hana_list_tables failed: %s", exc)
        return f"Error listing tables: {exc}"


hana_list_tables = StructuredTool(
    name="hana_list_tables",
    description=(
        "List all accessible tables and views in the SAP HANA Cloud database. "
        "Use this first to discover which business data tables are available before querying."
    ),
    args_schema=_ListTablesInput,
    func=_list_tables,
)


# ---------------------------------------------------------------------------
# Tool: hana_describe_table
# ---------------------------------------------------------------------------

class _DescribeTableInput(BaseModel):
    table_name: str = Field(description="Name of the table to describe (e.g. PAYROLL_RESULTS).")
    schema_name: Optional[str] = Field(
        default=None,
        description="Schema/owner of the table. Leave empty to auto-resolve.",
    )


def _describe_table(table_name: str, schema_name: Optional[str] = None) -> str:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        if schema_name:
            cur.execute(
                "SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH, IS_NULLABLE, DEFAULT_VALUE "
                "FROM SYS.TABLE_COLUMNS "
                "WHERE TABLE_NAME = ? AND SCHEMA_NAME = ? "
                "ORDER BY POSITION",
                (table_name.upper(), schema_name.upper()),
            )
        else:
            cur.execute(
                "SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH, IS_NULLABLE, DEFAULT_VALUE "
                "FROM SYS.TABLE_COLUMNS "
                "WHERE TABLE_NAME = ? "
                "ORDER BY SCHEMA_NAME, POSITION",
                (table_name.upper(),),
            )
        rows = cur.fetchall()
        cur.close()
        if not rows:
            return f"Table '{table_name}' not found or has no columns."
        lines = ["COLUMN_NAME | DATA_TYPE | LENGTH | NULLABLE | DEFAULT"]
        lines += [f"{r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]}" for r in rows]
        return "\n".join(lines)
    except Exception as exc:
        logger.error("hana_describe_table failed: %s", exc)
        return f"Error describing table '{table_name}': {exc}"


hana_describe_table = StructuredTool(
    name="hana_describe_table",
    description=(
        "Describe the columns, data types, and nullability of a HANA Cloud table. "
        "Use this before writing a query to understand the table schema."
    ),
    args_schema=_DescribeTableInput,
    func=_describe_table,
)


# ---------------------------------------------------------------------------
# Tool: hana_query
# ---------------------------------------------------------------------------

class _QueryInput(BaseModel):
    sql: str = Field(
        description=(
            "A read-only SELECT SQL statement to execute against HANA Cloud. "
            f"Results are capped at {_MAX_ROWS} rows. "
            "Write operations (INSERT, UPDATE, DELETE, DDL) are not permitted."
        )
    )


def _run_query(sql: str) -> str:
    # Safety: block write operations
    if _WRITE_PATTERN.search(sql):
        return (
            "Blocked: only SELECT statements are permitted. "
            "Write operations must go through the dedicated payroll mutation tools."
        )
    # Enforce row cap via TOP if not already present
    sql_stripped = sql.strip().rstrip(";")
    if not re.search(r"\bLIMIT\b|\bTOP\b|\bFETCH\s+FIRST\b", sql_stripped, re.IGNORECASE):
        # Wrap in a subquery with TOP
        sql_stripped = (
            f"SELECT TOP {_MAX_ROWS} * FROM ({sql_stripped}) AS _capped"
        )
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(sql_stripped)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchmany(_MAX_ROWS)
        cur.close()
        if not rows:
            return "Query returned no results."
        header = " | ".join(columns)
        separator = "-" * len(header)
        lines = [header, separator]
        for row in rows:
            lines.append(" | ".join("" if v is None else str(v) for v in row))
        truncation_note = f"\n(showing up to {_MAX_ROWS} rows)" if len(rows) == _MAX_ROWS else ""
        return "\n".join(lines) + truncation_note
    except Exception as exc:
        logger.error("hana_query failed: %s", exc)
        return f"Query error: {exc}"


hana_query = StructuredTool(
    name="hana_query",
    description=(
        "Execute a read-only SELECT SQL query against the SAP HANA Cloud database. "
        "Use hana_list_tables to discover available tables and hana_describe_table to inspect columns first. "
        f"Results are capped at {_MAX_ROWS} rows. Write operations are blocked."
    ),
    args_schema=_QueryInput,
    func=_run_query,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_hana_tools() -> list:
    """Return the list of HANA Cloud LangChain tools."""
    return [hana_list_tables, hana_describe_table, hana_query]

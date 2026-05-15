"""MCP Client for Agent Gateway Integration."""

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

_MCP_RETRY_ATTEMPTS = 4
_MCP_RETRY_DELAY = 4.0

AGW_RESOURCE_NAME = "agent-gateway"
MCP_MAX_RESPONSE_CHARS = int(os.environ.get("MCP_MAX_RESPONSE_CHARS", 100_000))


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code < 400 or exc.response.status_code >= 500
    return True


@dataclass
class IntegrationDependency:
    ord_id: str
    global_tenant_id: str

    @classmethod
    def from_dict(cls, data: dict) -> "IntegrationDependency":
        return cls(
            ord_id=data.get("ordId", ""),
            global_tenant_id=data.get("data", {}).get("globalTenantId", ""),
        )


@dataclass
class AgwCredentials:
    auth_type: str
    certificate: str
    client_id: str
    expires_at: str
    gateway_url: str
    private_key: str
    token_service_url: str
    uri: str
    integration_dependencies: list[IntegrationDependency] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "AgwCredentials":
        raw_deps = data.get("integrationDependencies", [])
        integration_dependencies = [
            IntegrationDependency.from_dict(dep)
            for dep in raw_deps
            if dep.get("ordId") and dep.get("data", {}).get("globalTenantId")
        ]
        return cls(
            auth_type=data.get("authType", ""),
            certificate=data.get("certificate", ""),
            client_id=data.get("clientid", ""),
            expires_at=data.get("expiresAt", ""),
            gateway_url=data.get("gatewayUrl", ""),
            private_key=data.get("privateKey", ""),
            token_service_url=data.get("tokenServiceUrl", ""),
            uri=data.get("uri", ""),
            integration_dependencies=integration_dependencies,
        )

    def mcp_url(self, dependency: IntegrationDependency) -> str:
        return f"{self.gateway_url.rstrip('/')}/v1/mcp/{dependency.ord_id}/{dependency.global_tenant_id}"


def _abbreviate_server_name(server_label: str) -> str:
    name = server_label
    for suffix in ("_mcp_demo", "_demo"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return "".join(w[0] for w in name.split("_") if w)


@dataclass
class MCPTool:
    name: str
    server_name: str
    description: str
    input_schema: dict
    url: str

    @property
    def namespaced_name(self) -> str:
        raw = f"{self.server_name}__{self.name}"
        sanitized = re.sub(r"[^a-zA-Z0-9\-_]", "_", raw)
        if len(sanitized) <= 64:
            return sanitized
        suffix = hashlib.sha256(sanitized.encode()).hexdigest()[:8]
        return f"{sanitized[:55]}_{suffix}"


UMS_CREDENTIALS_PATH = "/etc/ums/credentials/credentials"


def load_agw_credentials() -> "AgwCredentials | None":
    data = None
    if os.path.exists(UMS_CREDENTIALS_PATH):
        try:
            with open(UMS_CREDENTIALS_PATH, "r") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("Failed to read credentials from %s: %s", UMS_CREDENTIALS_PATH, e)
            return None
    if data is None:
        credentials_json = os.environ.get("AGW_CREDENTIALS_JSON", "")
        if credentials_json:
            try:
                data = json.loads(credentials_json)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse AGW_CREDENTIALS_JSON: %s", e)
                return None
    if data is None:
        return None
    try:
        credentials = AgwCredentials.from_dict(data)
        if not credentials.gateway_url or not credentials.client_id:
            return None
        return credentials
    except Exception as e:
        logger.error("Failed to load AGW credentials: %s", e)
        return None


async def get_oauth_token(credentials: AgwCredentials) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as cert_file:
        cert_file.write(credentials.certificate)
        cert_path = cert_file.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as key_file:
        key_file.write(credentials.private_key)
        key_path = key_file.name
    try:
        async with httpx.AsyncClient(cert=(cert_path, key_path), timeout=30.0) as client:
            response = await client.post(
                credentials.token_service_url,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={
                    "client_id": credentials.client_id,
                    "grant_type": "client_credentials",
                    "resource": f"urn:sap:identity:application:provider:name:{AGW_RESOURCE_NAME}",
                },
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise ValueError("No access_token in response")
            return f"Bearer {access_token}"
    finally:
        try:
            os.unlink(cert_path)
            os.unlink(key_path)
        except Exception:
            pass


class MCPClient:
    def __init__(self, credentials: "AgwCredentials | None" = None):
        self.credentials = credentials or load_agw_credentials()

    async def _get_auth_header(self) -> str:
        if not self.credentials:
            raise ValueError("No AGW credentials available")
        return await get_oauth_token(self.credentials)

    async def get_mcp_tools(self, mcp_server_filter: "list[str] | None" = None) -> list[MCPTool]:
        if not self.credentials or not self.credentials.integration_dependencies:
            return []
        dependencies = self.credentials.integration_dependencies
        if mcp_server_filter is not None:
            filter_set = set(mcp_server_filter)
            dependencies = [d for d in dependencies if d.ord_id in filter_set]
        all_tools: list[MCPTool] = []
        for dependency in dependencies:
            mcp_url = self.credentials.mcp_url(dependency)
            last_exc = None
            for attempt in range(1 + _MCP_RETRY_ATTEMPTS):
                try:
                    auth_header = await self._get_auth_header()
                    async with httpx.AsyncClient(headers={"Authorization": auth_header}, timeout=30.0) as http_client:
                        async with streamable_http_client(mcp_url, http_client=http_client) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                ord_parts = dependency.ord_id.split(":")
                                server_label = ord_parts[-2] if len(ord_parts) >= 2 else dependency.ord_id
                                server_name = _abbreviate_server_name(server_label)
                                result = await session.list_tools()
                                tools = [
                                    MCPTool(
                                        name=t.name,
                                        server_name=server_name,
                                        description=f"[{server_label}] {t.description or ''}".strip(),
                                        input_schema=t.inputSchema or {},
                                        url=mcp_url,
                                    )
                                    for t in result.tools
                                ]
                    all_tools.extend(tools)
                    last_exc = None
                    break
                except Exception as e:
                    if not _is_retryable_error(e):
                        break
                    last_exc = e
                    if attempt < _MCP_RETRY_ATTEMPTS:
                        await asyncio.sleep(_MCP_RETRY_DELAY)
        return all_tools

    async def call_tool(self, tool: MCPTool, **kwargs) -> str:
        if not self.credentials:
            raise ValueError("No AGW credentials available")
        last_exc = None
        for attempt in range(1 + _MCP_RETRY_ATTEMPTS):
            try:
                auth_header = await self._get_auth_header()
                _call_result = None
                try:
                    async with httpx.AsyncClient(headers={"Authorization": auth_header}, timeout=60.0) as http_client:
                        async with streamable_http_client(tool.url, http_client=http_client) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                _call_result = await session.call_tool(tool.name, kwargs)
                except (ExceptionGroup, BaseExceptionGroup) as eg:
                    if _call_result is None:
                        raise
                if _call_result is None:
                    raise RuntimeError("call_tool returned None")
                response = str(_call_result.content[0].text if _call_result.content else "")
                if len(response) > MCP_MAX_RESPONSE_CHARS:
                    response = response[:MCP_MAX_RESPONSE_CHARS] + "\n...[truncated]"
                return response
            except Exception as e:
                if not _is_retryable_error(e):
                    raise
                last_exc = e
                if attempt < _MCP_RETRY_ATTEMPTS:
                    await asyncio.sleep(_MCP_RETRY_DELAY)
        raise last_exc  # type: ignore[misc]


class MCPToolConverter:
    def __init__(self, mcp_client: MCPClient):
        self.mcp_client = mcp_client

    def to_langchain(self, mcp_tool: MCPTool):
        from langchain_core.tools import StructuredTool
        from pydantic import create_model

        mcp_client = self.mcp_client

        async def run(**kwargs) -> str:
            return await mcp_client.call_tool(mcp_tool, **kwargs)

        properties = mcp_tool.input_schema.get("properties", {})
        required = set(mcp_tool.input_schema.get("required", []))
        fields = {}
        for name, prop in properties.items():
            prop_type = prop.get("type", "string")
            python_type = str
            if prop_type == "integer":
                python_type = int
            elif prop_type == "number":
                python_type = float
            elif prop_type == "boolean":
                python_type = bool
            if name in required:
                fields[name] = (python_type, ...)
            else:
                fields[name] = (python_type | None, None)
        args_schema = create_model(f"{mcp_tool.name}_args", **fields) if fields else None
        return StructuredTool.from_function(
            coroutine=run,
            name=mcp_tool.namespaced_name,
            description=mcp_tool.description,
            args_schema=args_schema,
        )

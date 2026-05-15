"""Structure tests: verify agent module exports, decorators, and class definitions."""
import pytest
import ast
import sys
from pathlib import Path


@pytest.fixture(autouse=True)
def use_agent_path(add_agent_to_path):
    pass


@pytest.mark.structure
def test_agent_module_importable():
    """agent module must be importable without errors."""
    import agent  # noqa: F401


@pytest.mark.structure
def test_payroll_operations_agent_class_exists():
    """PayrollOperationsAgent class must be defined in agent.py."""
    from agent import PayrollOperationsAgent
    assert PayrollOperationsAgent is not None


@pytest.mark.structure
def test_agent_has_stream_method():
    from agent import PayrollOperationsAgent
    assert hasattr(PayrollOperationsAgent, "stream"), "Agent must have stream() method"


@pytest.mark.structure
def test_agent_has_invoke_method():
    from agent import PayrollOperationsAgent
    assert hasattr(PayrollOperationsAgent, "invoke"), "Agent must have invoke() method"


@pytest.mark.structure
def test_get_system_prompt_exported():
    from agent import get_system_prompt
    prompt = get_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 100, "System prompt must be non-trivial"


@pytest.mark.structure
def test_three_required_decorators_present():
    """agent.py must have exactly @agent_model, @agent_config, @prompt_section."""
    agent_path = Path(__file__).parent.parent / "app" / "agent.py"
    source = agent_path.read_text()
    tree = ast.parse(source)
    decorator_names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                # @name or @name(...)
                if isinstance(deco, ast.Name):
                    decorator_names.add(deco.id)
                elif isinstance(deco, ast.Attribute):
                    decorator_names.add(deco.attr)
                elif isinstance(deco, ast.Call):
                    inner = deco.func
                    if isinstance(inner, ast.Name):
                        decorator_names.add(inner.id)
                    elif isinstance(inner, ast.Attribute):
                        decorator_names.add(inner.attr)
    required = {"agent_model", "agent_config", "prompt_section"}
    missing = required - decorator_names
    assert not missing, f"Missing decorators in agent.py: {missing}"


@pytest.mark.structure
def test_auto_instrument_called_first_in_main():
    """main.py must call auto_instrument() before any AI framework imports."""
    main_path = Path(__file__).parent.parent / "app" / "main.py"
    source = main_path.read_text()
    lines = [l.strip() for l in source.splitlines() if l.strip()]
    code_lines = [l for l in lines if not l.startswith("#") and l]
    # Find auto_instrument call line index
    ai_idx = None
    for i, line in enumerate(code_lines):
        if "auto_instrument" in line and "()" in line:
            ai_idx = i
            break
    assert ai_idx is not None, "auto_instrument() call not found in main.py"
    # Verify no langchain/langgraph/openai imports appear before it
    forbidden_before = ["from langchain", "import langchain", "from langgraph", "import langgraph"]
    for line in code_lines[:ai_idx]:
        for forbidden in forbidden_before:
            assert forbidden not in line, (
                f"AI framework import '{line}' found before auto_instrument() in main.py"
            )


@pytest.mark.structure
def test_no_create_react_agent_usage():
    """create_react_agent from langgraph.prebuilt must not be used (deprecated)."""
    agent_path = Path(__file__).parent.parent / "app" / "agent.py"
    source = agent_path.read_text()
    assert "create_react_agent" not in source, (
        "Deprecated create_react_agent from langgraph.prebuilt must not be used"
    )


@pytest.mark.structure
def test_no_dotenv_files():
    """No .env files should exist in the agent directory."""
    agent_root = Path(__file__).parent.parent
    env_files = list(agent_root.glob("**/.env")) + list(agent_root.glob("**/.env.*"))
    assert not env_files, f"Found .env files: {env_files}"


@pytest.mark.structure
def test_top_limit_respected_in_system_prompt():
    """System prompt should mention $top or query limits."""
    from agent import get_system_prompt
    prompt = get_system_prompt()
    assert "$top" in prompt or "100" in prompt or "limit" in prompt.lower(), (
        "System prompt should reference $top or query limits"
    )


@pytest.mark.structure
def test_milestone_log_function_exists():
    """log_milestone() helper must be present in agent module."""
    from agent import log_milestone
    assert callable(log_milestone)


@pytest.mark.structure
def test_mcp_mock_json_has_all_7_servers():
    """mcp-mock.json must reference all 7 MCP servers."""
    import json
    mock_path = Path(__file__).parent.parent / "mcp-mock.json"
    assert mock_path.exists(), "mcp-mock.json not found"
    data = json.loads(mock_path.read_text())
    servers = data.get("servers", {})
    assert len(servers) == 7, f"Expected 7 MCP servers, got {len(servers)}"

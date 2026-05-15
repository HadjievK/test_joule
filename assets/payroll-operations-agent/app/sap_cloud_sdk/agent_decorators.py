"""SAP Cloud SDK agent decorators for configuration, model selection, and prompts."""
import functools
import logging

logger = logging.getLogger(__name__)


def agent_model(key=None, label=None, description=None, **kwargs):
    """Decorator: marks a function as the agent's LLM model selector."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper._agent_model_key = key
        wrapper._agent_model_label = label
        return wrapper
    return decorator


def agent_config(key=None, label=None, description=None, **kwargs):
    """Decorator: marks a function as providing an agent configuration value."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper._agent_config_key = key
        wrapper._agent_config_label = label
        return wrapper
    return decorator


def prompt_section(key=None, label=None, description=None, validation=None, **kwargs):
    """Decorator: marks a function as providing a named prompt section."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper._prompt_section_key = key
        wrapper._prompt_section_label = label
        return wrapper
    return decorator

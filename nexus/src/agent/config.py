"""Agent runtime configuration."""

from __future__ import annotations

import os

from src.agent.models import ChatConfig
from src.agent.tools import available_tool_names

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-4.1"
MAX_HISTORY_MESSAGES = int(os.getenv("MERIDIAN_AGENT_MAX_HISTORY_MESSAGES", "18"))
MAX_TOOL_ROUNDS = int(os.getenv("MERIDIAN_AGENT_MAX_TOOL_ROUNDS", "3"))
MAX_TOOL_RESULT_CHARS = int(os.getenv("MERIDIAN_AGENT_TOOL_RESULT_CHARS", "9000"))
AGENT_TURN_TIMEOUT_SECONDS = int(os.getenv("MERIDIAN_AGENT_TURN_TIMEOUT_SECONDS", "60"))
MODEL_REQUEST_TIMEOUT_SECONDS = int(os.getenv("MERIDIAN_MODEL_REQUEST_TIMEOUT_SECONDS", "45"))


def model_provider() -> str:
    return os.getenv("MERIDIAN_MODEL_PROVIDER") or os.getenv("MODEL_PROVIDER") or DEFAULT_PROVIDER


def model_name() -> str:
    return (
        os.getenv("MERIDIAN_MODEL_NAME")
        or os.getenv("MODEL_NAME")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_MODEL
    )


def model_base_url() -> str | None:
    return os.getenv("MERIDIAN_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL")


def model_api_key() -> str | None:
    return os.getenv("MERIDIAN_MODEL_API_KEY") or os.getenv("OPENAI_API_KEY")


def get_chat_config() -> ChatConfig:
    provider = model_provider().lower()
    return ChatConfig(
        provider=provider,
        model=model_name(),
        configured=bool(model_api_key()),
        base_url=model_base_url(),
        max_tool_rounds=MAX_TOOL_ROUNDS,
        tools=available_tool_names(),
    )

"""Model provider adapters for the Meridian Agent runtime."""

from __future__ import annotations

from typing import Any

from src.agent.config import MODEL_REQUEST_TIMEOUT_SECONDS, get_chat_config, model_api_key
from src.agent.models import ChatConfig, ModelProviderError


class LangChainModelAdapter:
    """Thin adapter around LangChain chat models.

    Only OpenAI and OpenAI-compatible endpoints are wired now.  Other providers
    should be added here without changing `/api/chat` or Console.
    """

    def __init__(self, config: ChatConfig | None = None) -> None:
        self.config = config or get_chat_config()

    def create_model(self) -> Any:
        provider = self.config.provider
        if provider not in {"openai", "openai-compatible"}:
            raise ModelProviderError(
                f"模型供应商 {provider!r} 还没有适配器。请先使用 openai 或 openai-compatible。"
            )

        api_key = model_api_key()
        if not api_key:
            raise ModelProviderError(
                "缺少模型 API Key。请设置 MERIDIAN_MODEL_API_KEY 或 OPENAI_API_KEY。"
            )

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ModelProviderError(
                "缺少 LangChain OpenAI 适配器。请在 nexus 环境安装 langchain 和 langchain-openai。"
            ) from exc

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "api_key": api_key,
            "temperature": 0,
            "timeout": MODEL_REQUEST_TIMEOUT_SECONDS,
        }
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return ChatOpenAI(**kwargs)

"""Agent tool-calling runtime."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError

from src.agent.config import MAX_HISTORY_MESSAGES, MAX_TOOL_RESULT_CHARS, MAX_TOOL_ROUNDS
from src.agent.models import ChatMessage, ChatToolCall, ModelProviderError, ToolExecutor
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.providers import LangChainModelAdapter
from src.agent.sessions import new_id
from src.agent.tools import TOOL_ARG_MODELS, compact_tool_result, tool_schemas, validate_tool_args


class AgentRuntime:
    def __init__(
        self,
        model_adapter: LangChainModelAdapter,
        tool_executor: ToolExecutor,
    ) -> None:
        self.model_adapter = model_adapter
        self.tool_executor = tool_executor

    async def run(self, history: list[ChatMessage]) -> tuple[str, list[ChatToolCall]]:
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        except ImportError as exc:
            raise ModelProviderError(
                "缺少 LangChain Core。请在 nexus 环境安装 langchain。"
            ) from exc

        model = self.model_adapter.create_model()
        if hasattr(model, "bind_tools"):
            model = model.bind_tools(tool_schemas())
        else:
            model = model.bind(tools=tool_schemas())

        messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
        for item in history[-MAX_HISTORY_MESSAGES:]:
            if item.role == "user":
                messages.append(HumanMessage(content=item.content))
            elif item.role == "assistant":
                messages.append(AIMessage(content=item.content))

        tool_records: list[ChatToolCall] = []
        last_text = ""

        for _ in range(MAX_TOOL_ROUNDS):
            response = await model.ainvoke(messages)
            last_text = _message_text(response.content).strip()
            tool_calls = _extract_tool_calls(response)
            if not tool_calls:
                return last_text, tool_records

            messages.append(response)
            for call in tool_calls:
                record = await self._execute_tool_call(call)
                tool_records.append(record)
                messages.append(
                    ToolMessage(
                        content=json.dumps(record.result, ensure_ascii=False, default=str),
                        tool_call_id=record.id,
                    )
                )

        response = await self.model_adapter.create_model().ainvoke(messages)
        last_text = _message_text(response.content).strip()
        if last_text:
            return last_text, tool_records
        return "我已经调用了工具，但还没有形成可靠结论。建议缩小时间范围或提供 request_id。", tool_records

    async def _execute_tool_call(self, call: dict[str, Any]) -> ChatToolCall:
        tool_name = call["name"]
        raw_args = call.get("args") or {}
        started = time.perf_counter()

        if tool_name not in TOOL_ARG_MODELS:
            return ChatToolCall(
                id=call["id"],
                name=tool_name,
                arguments=raw_args,
                result={"error": "unknown_tool", "tool": tool_name},
                error="unknown_tool",
            )

        try:
            args = validate_tool_args(tool_name, raw_args)
        except ValidationError as exc:
            return ChatToolCall(
                id=call["id"],
                name=tool_name,
                arguments=raw_args,
                result={"error": "invalid_tool_arguments", "detail": exc.errors()},
                error="invalid_tool_arguments",
            )

        try:
            result = await self.tool_executor(tool_name, args)
            error = result.get("error") if isinstance(result, dict) else None
        except Exception as exc:  # pragma: no cover - defensive boundary
            result = {"error": "tool_execution_failed", "detail": str(exc)}
            error = "tool_execution_failed"

        return ChatToolCall(
            id=call["id"],
            name=tool_name,
            arguments=args,
            result=compact_tool_result(result, MAX_TOOL_RESULT_CHARS),
            error=error,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part)
    return json.dumps(content, ensure_ascii=False, default=str)


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    normalized = getattr(message, "tool_calls", None) or []
    if normalized:
        calls: list[dict[str, Any]] = []
        for call in normalized:
            name = call.get("name")
            if not name:
                continue
            calls.append(
                {
                    "id": call.get("id") or new_id("tool"),
                    "name": name,
                    "args": call.get("args") or {},
                }
            )
        return calls

    additional = getattr(message, "additional_kwargs", None) or {}
    raw_calls = additional.get("tool_calls") or []
    calls = []
    for call in raw_calls:
        function = call.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        try:
            args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append({"id": call.get("id") or new_id("tool"), "name": name, "args": args})
    return calls

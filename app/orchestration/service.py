"""High-level Intranet Assistant service orchestrating chat flows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from app.audit import AuditSink, new_event
from app.auth.service import Identity
from app.config import Settings
from app.documents.models import SourceCitation
from app.llm.service import ChatMessage, LocalLLMClient
from app.orchestration.graph import (
    AssistantState,
    _format_system_prompt,
    build_async_orchestration_graph,
    build_orchestration_graph,
)
from app.orchestration.mcp import MCPToolRegistry

logger = logging.getLogger("app.orchestration")


@dataclass(frozen=True)
class ChatResult:
    response: str
    citations: tuple[SourceCitation, ...]
    tool_trace: str | None = None


class IntranetAssistantService:
    """Service orchestrating employee inquiries using LangGraph and approved MCP tools."""

    def __init__(
        self,
        settings: Settings,
        llm_client: LocalLLMClient,
        tool_registry: MCPToolRegistry,
        audit_sink: AuditSink,
    ) -> None:
        self._settings = settings
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._audit_sink = audit_sink
        self._system_prompt = _format_system_prompt(tool_registry)
        self._max_iterations = settings.orchestration_max_iterations
        self._graph = build_orchestration_graph(
            llm_client=self._llm_client,
            tool_registry=self._tool_registry,
            max_iterations=self._max_iterations,
        )
        self._async_graph = build_async_orchestration_graph(
            llm_client=self._llm_client,
            tool_registry=self._tool_registry,
            max_iterations=self._max_iterations,
        )

    def _prepare_initial_state(
        self,
        message: str,
        identity: Identity,
        request_id: str,
        history: Sequence[ChatMessage] | None = None,
    ) -> AssistantState:
        if "chat:use" not in identity.permissions:
            self._audit_sink.record(
                new_event("assistant_chat", "denied", request_id, identity.subject, "chat")
            )
            raise PermissionError("chat:use permission required")

        system_prompt = _format_system_prompt(self._tool_registry, identity)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system_prompt)
        ]
        if history:
            messages.extend(history)
        messages.append(ChatMessage(role="user", content=message))

        return {
            "query": message,
            "messages": messages,
            "identity": identity,
            "request_id": request_id,
            "citations": [],
            "tool_traces": [],
            "step_count": 0,
            "max_iterations": self._max_iterations,
            "pending_tool_name": None,
            "pending_tool_args": None,
            "final_response": None,
            "error": None,
        }

    def _format_result(self, result_state: dict[str, Any], identity: Identity, request_id: str) -> ChatResult:
        final_response = result_state.get("final_response") or "I could not produce a response."
        citations = tuple(result_state.get("citations", []))
        tool_traces = result_state.get("tool_traces", [])
        tool_trace = " | ".join(tool_traces) if tool_traces else None

        self._audit_sink.record(
            new_event(
                "assistant_chat",
                "allowed",
                request_id,
                identity.subject,
                f"citations={len(citations)}",
            )
        )
        return ChatResult(response=final_response, citations=citations, tool_trace=tool_trace)

    def ask(
        self,
        message: str,
        identity: Identity,
        request_id: str,
        history: Sequence[ChatMessage] | None = None,
    ) -> ChatResult:
        """Process a user query synchronously through the LangGraph flow."""
        initial_state = self._prepare_initial_state(message, identity, request_id, history)
        result_state = self._graph.invoke(initial_state)
        return self._format_result(result_state, identity, request_id)

    async def aask(
        self,
        message: str,
        identity: Identity,
        request_id: str,
        history: Sequence[ChatMessage] | None = None,
    ) -> ChatResult:
        """Process a user query asynchronously through the LangGraph flow without blocking."""
        initial_state = self._prepare_initial_state(message, identity, request_id, history)
        result_state = await self._async_graph.ainvoke(initial_state)
        return self._format_result(result_state, identity, request_id)

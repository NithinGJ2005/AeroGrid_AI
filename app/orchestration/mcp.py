"""Model Context Protocol (MCP) internal tool contracts and registry.

MCP provides standardized tool definitions and execution contracts. Crucially,
MCP is NOT an authentication or authorization boundary: each tool independently
verifies server-side permissions and logs privacy-preserving audit events.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.audit import AuditSink, new_event
from app.auth.service import Identity
from app.db.service import (
    DatabasePermissionError,
    DatabaseQueryError,
    DatabaseQueryService,
    QueryInputError,
    UnknownQueryError,
)
from app.documents.models import SourceCitation
from app.documents.service import DocumentIndexer


class MCPError(Exception):
    """Base error for MCP tool operations."""


class MCPToolNotFoundError(MCPError):
    """Raised when an unapproved or nonexistent tool is requested."""


class MCPAuthorizationError(MCPError):
    """Raised when the requesting identity lacks required tool permissions."""


class MCPValidationError(MCPError):
    """Raised when input parameters fail schema validation."""


class MCPExecutionError(MCPError):
    """Raised when internal tool execution fails."""


@dataclass(frozen=True)
class MCPToolResult:
    content: str
    citations: tuple[SourceCitation, ...] = ()
    data: Any = None
    truncated: bool = False
    error: str | None = None


class BaseMCPTool(ABC):
    """Base interface for all internal MCP tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier of the tool."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does and when to use it."""

    @property
    @abstractmethod
    def parameter_model(self) -> type[BaseModel]:
        """Pydantic model describing the accepted parameters schema."""

    @property
    @abstractmethod
    def required_permission(self) -> str:
        """Server-side permission required to invoke this tool."""

    def get_descriptor(self) -> dict[str, Any]:
        """Return the standard MCP descriptor with JSON Schema for parameters."""
        schema = self.parameter_model.model_json_schema()
        # Remove top-level title to keep descriptor lean
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": schema,
            "required_permission": self.required_permission,
        }

    @abstractmethod
    def execute(self, parameters: dict[str, Any], identity: Identity, request_id: str) -> MCPToolResult:
        """Execute the tool with independent authorization and schema validation."""


class DocumentSearchParameters(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Natural language search terms")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum number of document chunks to return")


class DocumentSearchMCPTool(BaseMCPTool):
    """MCP tool for authorized lexical document search across approved directory roots."""

    def __init__(self, indexer: DocumentIndexer, audit_sink: AuditSink) -> None:
        self._indexer = indexer
        self._audit_sink = audit_sink

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return (
            "Search internal organizational documents (policies, guides, benefits) by keywords. "
            "Returns text excerpts and safe source citations."
        )

    @property
    def parameter_model(self) -> type[BaseModel]:
        return DocumentSearchParameters

    @property
    def required_permission(self) -> str:
        return "documents:search"

    def execute(self, parameters: dict[str, Any], identity: Identity, request_id: str) -> MCPToolResult:
        # Independent authorization check
        if self.required_permission not in identity.permissions:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "denied", request_id, identity.subject, self.name)
            )
            raise MCPAuthorizationError(f"Permission '{self.required_permission}' is required")

        # Strict parameter schema validation
        try:
            validated = self.parameter_model.model_validate(parameters)
        except ValidationError as error:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "denied", request_id, identity.subject, self.name)
            )
            raise MCPValidationError(f"Invalid parameters for {self.name}") from error

        try:
            results = self._indexer.search(validated.query, identity, limit=validated.limit)
        except Exception as error:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "failed", request_id, identity.subject, self.name)
            )
            raise MCPExecutionError("Document search failed") from error

        self._audit_sink.record(
            new_event("mcp_tool_execute", "allowed", request_id, identity.subject, self.name)
        )

        if not results:
            return MCPToolResult(content="No matching documents found.", citations=(), data={"count": 0})

        citations: list[SourceCitation] = []
        chunks_text: list[str] = []
        for r in results:
            citations.append(r.citation)
            page_info = f", Page {r.citation.page}" if r.citation.page is not None else ""
            chunks_text.append(f"[{r.citation.filename}{page_info}]\n{r.content}")

        formatted_content = "\n\n".join(chunks_text)
        return MCPToolResult(
            content=formatted_content,
            citations=tuple(citations),
            data={"count": len(results)},
        )


class DatabaseQueryParameters(BaseModel):
    query_id: str = Field(min_length=1, max_length=100, description="Approved catalog query identifier")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Named parameters matching query specification")


class DatabaseQueryMCPTool(BaseMCPTool):
    """MCP tool for executing code-reviewed, parameterized queries from the approved catalog."""

    def __init__(self, db_service: DatabaseQueryService, audit_sink: AuditSink) -> None:
        self._db_service = db_service
        self._audit_sink = audit_sink

    @property
    def name(self) -> str:
        return "query_database"

    @property
    def description(self) -> str:
        queries = ", ".join(f"'{k}'" for k in self._db_service._catalog.keys())
        return (
            f"Execute approved, parameterized catalog queries against internal company databases. "
            f"Available approved query_id options: {queries}. "
            f"Example: use query_id='directory.by_department' with parameters={{'department': '<name>'}} to look up employee directories by department. "
            f"No raw SQL or unapproved queries are accepted."
        )

    @property
    def parameter_model(self) -> type[BaseModel]:
        return DatabaseQueryParameters

    @property
    def required_permission(self) -> str:
        return "database:read"

    def execute(self, parameters: dict[str, Any], identity: Identity, request_id: str) -> MCPToolResult:
        # Independent authorization check
        if self.required_permission not in identity.permissions:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "denied", request_id, identity.subject, self.name)
            )
            raise MCPAuthorizationError(f"Permission '{self.required_permission}' is required")

        # Parameter schema validation
        try:
            validated = self.parameter_model.model_validate(parameters)
        except ValidationError as error:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "denied", request_id, identity.subject, self.name)
            )
            raise MCPValidationError(f"Invalid parameters for {self.name}") from error

        try:
            result = self._db_service.execute(
                query_id=validated.query_id,
                raw_parameters=validated.parameters,
                identity=identity,
                request_id=request_id,
            )
        except DatabasePermissionError as error:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "denied", request_id, identity.subject, f"{self.name}:{validated.query_id}")
            )
            raise MCPAuthorizationError("Database query access denied: insufficient permissions") from error
        except (UnknownQueryError, QueryInputError) as error:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "denied", request_id, identity.subject, self.name)
            )
            raise MCPValidationError(str(error)) from error
        except DatabaseQueryError as error:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "failed", request_id, identity.subject, self.name)
            )
            raise MCPExecutionError("Database query execution failed") from error

        self._audit_sink.record(
            new_event("mcp_tool_execute", "allowed", request_id, identity.subject, self.name)
        )

        formatted_content = json.dumps(
            {
                "query_id": result.query_id,
                "columns": result.columns,
                "rows": result.rows,
                "truncated": result.truncated,
            },
            default=str,
        )

        citations: tuple[SourceCitation, ...] = ()
        if result.rows:
            citations = (
                SourceCitation(
                    document_id=f"db-{result.query_id}",
                    filename="sample_db.sqlite3 [table: employee_directory]",
                    page=None,
                ),
            )

        return MCPToolResult(
            content=formatted_content,
            citations=citations,
            data={"columns": result.columns, "rows": result.rows},
            truncated=result.truncated,
        )


class MCPToolRegistry:
    """Registry managing available MCP tools and handling invocation requests."""

    def __init__(self, audit_sink: AuditSink) -> None:
        self._tools: dict[str, BaseMCPTool] = {}
        self._audit_sink = audit_sink

    def register(self, tool: BaseMCPTool) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseMCPTool | None:
        return self._tools.get(name)

    def list_descriptors(self) -> list[dict[str, Any]]:
        return [tool.get_descriptor() for tool in self._tools.values()]

    def list_descriptors_for_identity(self, identity: Identity) -> list[dict[str, Any]]:
        """Return only tool descriptors that the given identity has permission to execute."""
        return [
            tool.get_descriptor()
            for tool in self._tools.values()
            if tool.required_permission in identity.permissions
        ]

    def execute(
        self, tool_name: str, parameters: dict[str, Any], identity: Identity, request_id: str
    ) -> MCPToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            self._audit_sink.record(
                new_event("mcp_tool_execute", "denied", request_id, identity.subject, tool_name)
            )
            raise MCPToolNotFoundError(f"Tool '{tool_name}' is not recognized")
        return tool.execute(parameters, identity, request_id)

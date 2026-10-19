"""API response schemas shared by routes and exception handlers."""

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error: str = Field(examples=["invalid_request"])
    message: str = Field(examples=["The request could not be processed."])
    request_id: str


class HealthResponse(BaseModel):
    status: str
    request_id: str


class SessionResponse(BaseModel):
    subject: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class SourceCitationResponse(BaseModel):
    document_id: str
    filename: str
    page: int | None = None


class ChatResponse(BaseModel):
    response: str
    citations: list[SourceCitationResponse] = Field(default_factory=list)
    tool_trace: str | None = None
    request_id: str


class MCPToolDescriptor(BaseModel):
    name: str
    description: str
    parameters: dict[str, object]
    required_permission: str


class MCPToolsListResponse(BaseModel):
    tools: list[MCPToolDescriptor]


class MCPCallRequest(BaseModel):
    parameters: dict[str, object] = Field(default_factory=dict)


class MCPCallResponse(BaseModel):
    tool: str
    content: str
    citations: list[SourceCitationResponse] = Field(default_factory=list)
    request_id: str
    truncated: bool = False


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=100)
    client_type: str = Field(default="api", description="Client type: 'browser' (cookie-only) or 'api' (returns bearer token)")


class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str | None = None
    csrf_token: str = ""
    expires_in: int
    user: dict[str, object]


class LogoutResponse(BaseModel):
    status: str = "logged_out"
    message: str = "Session successfully terminated"


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=100)


class UserProvisionRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    roles: list[str] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    roles: list[str] | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    username: str
    full_name: str
    roles: list[str]
    is_active: bool
    is_demo: bool = False


class UserListResponse(BaseModel):
    users: list[UserResponse]


class AdminAuditEvent(BaseModel):
    id: int
    actor: str
    action: str
    target: str
    details: dict[str, object]
    timestamp: str
    outcome: str


class AdminAuditListResponse(BaseModel):
    events: list[AdminAuditEvent]

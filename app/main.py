"""FastAPI application factory and operational endpoints."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from pathlib import Path

import anyio
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.audit import InMemoryAuditSink, JsonlAuditSink, new_event
from app.auth.accounts import AccountStore, SessionRevocationStore
from app.auth.service import Identity, bearer_token, build_authenticator
from app.config import Environment, Settings, get_settings
from app.db.catalog import SAMPLE_QUERY_CATALOG
from app.db.service import DatabaseQueryService, create_read_only_engine
from app.documents.service import DocumentIndexer
from app.llm.service import InferenceOverloaded, InferenceUnavailable, LocalLLMClient
from app.logging_config import configure_logging
from app.orchestration.mcp import (
    DatabaseQueryMCPTool,
    DocumentSearchMCPTool,
    MCPAuthorizationError,
    MCPError,
    MCPExecutionError,
    MCPToolNotFoundError,
    MCPToolRegistry,
    MCPValidationError,
)
from app.orchestration.service import IntranetAssistantService
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MCPCallRequest,
    MCPCallResponse,
    MCPToolDescriptor,
    MCPToolsListResponse,
    SessionResponse,
    SourceCitationResponse,
    UserListResponse,
    UserProvisionRequest,
    UserResponse,
    UserUpdateRequest,
    AdminAuditListResponse,
    PasswordResetRequest,
)
from app.security import AuthorizationFailure, current_identity, require_permission, validate_csrf

logger = logging.getLogger("app")


def safe_error_response(status_code: int, error: str, message: str, request_id: str) -> JSONResponse:
    """Return a client-safe error without exposing exception details."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, message=message, request_id=request_id).model_dump(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging()
    logger.info("application_starting", extra={"environment": settings.app_env.value})
    try:
        limiter_tokens = getattr(settings, "anyio_thread_limiter", 60)
        anyio.to_thread.current_default_thread_limiter().total_tokens = limiter_tokens
    except Exception:
        pass
    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False
        llm_client = getattr(app.state, "llm_client", None)
        if llm_client is not None:
            if hasattr(llm_client, "aclose"):
                await llm_client.aclose()
            elif hasattr(llm_client, "close"):
                llm_client.close()
        logger.info("application_stopped")


def create_app(
    settings: Settings | None = None,
    llm_client: LocalLLMClient | None = None,
    document_indexer: DocumentIndexer | None = None,
    database_service: DatabaseQueryService | None = None,
    account_store: AccountStore | None = None,
    revocation_store: SessionRevocationStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None, lifespan=lifespan)
    cors_origins = (
        list(settings.allowed_origins)
        if settings.allowed_origins
        else ["http://127.0.0.1:8000", "http://localhost:8000"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.ready = False
    app.state.account_store = (
        account_store
        if account_store is not None
        else AccountStore(
            db_path=settings.auth_db_path,
            is_production=(settings.app_env is Environment.PRODUCTION),
            iterations=settings.password_hash_iterations,
            demo_accounts=settings.dev_demo_accounts,
        )
    )
    app.state.revocation_store = (
        revocation_store
        if revocation_store is not None
        else app.state.account_store
    )
    app.state.authenticator = build_authenticator(
        settings,
        account_store=app.state.account_store,
        revocation_store=app.state.revocation_store,
    )
    audit_sink = (
        JsonlAuditSink(settings.audit_log_path) if settings.audit_log_path else InMemoryAuditSink()
    )
    app.state.audit_sink = audit_sink

    # Initialize Document Indexer if roots configured or explicitly provided
    if document_indexer is not None:
        app.state.document_indexer = document_indexer
    elif settings.document_roots:
        try:
            indexer = DocumentIndexer(
                roots=settings.document_roots,
                chunk_size=settings.document_chunk_size,
                chunk_overlap=settings.document_chunk_overlap,
            )
            indexer.reindex()
            app.state.document_indexer = indexer
        except Exception:
            logger.warning("document_indexer_init_failed", exc_info=True)
            app.state.document_indexer = None
    else:
        app.state.document_indexer = None

    # Initialize Database Service if URL configured or explicitly provided
    if database_service is not None:
        app.state.database_service = database_service
    elif settings.database_url:
        try:
            engine = create_read_only_engine(settings.database_url)
            app.state.database_service = DatabaseQueryService(
                engine=engine,
                catalog=SAMPLE_QUERY_CATALOG,
                audit_sink=audit_sink,
                max_result_rows=settings.database_max_result_rows,
                timeout_seconds=settings.database_query_timeout_seconds,
            )
        except Exception:
            logger.warning("database_service_init_failed", exc_info=True)
            app.state.database_service = None
    else:
        app.state.database_service = None

    # Initialize MCP Tool Registry and register tools
    tool_registry = MCPToolRegistry(audit_sink)
    if app.state.document_indexer is not None:
        tool_registry.register(DocumentSearchMCPTool(app.state.document_indexer, audit_sink))
    if app.state.database_service is not None:
        tool_registry.register(DatabaseQueryMCPTool(app.state.database_service, audit_sink))
    app.state.tool_registry = tool_registry

    # Initialize Local LLM Client if configured or explicitly provided
    if llm_client is not None:
        app.state.llm_client = llm_client
    elif settings.llm_enabled and settings.llm_base_url:
        try:
            app.state.llm_client = LocalLLMClient(settings)
        except Exception:
            logger.warning("llm_client_init_failed", exc_info=True)
            app.state.llm_client = None
    else:
        app.state.llm_client = None

    # Initialize Intranet Assistant Service
    if app.state.llm_client is not None:
        app.state.assistant_service = IntranetAssistantService(
            settings=settings,
            llm_client=app.state.llm_client,
            tool_registry=tool_registry,
            audit_sink=audit_sink,
        )
    else:
        app.state.assistant_service = None

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID")
        request_id = supplied_request_id if supplied_request_id and supplied_request_id.isprintable() else str(uuid.uuid4())
        supplied_correlation_id = request.headers.get("X-Correlation-ID")
        correlation_id = (
            supplied_correlation_id
            if supplied_correlation_id and supplied_correlation_id.isprintable()
            else request_id
        )
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Do not emit exception text or tracebacks: either may contain secrets, SQL, or paths.
            logger.error(
                "unhandled_request_error",
                extra={"request_id": request_id, "correlation_id": correlation_id},
            )
            response = safe_error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "internal_error",
                "An unexpected error occurred.",
                request_id,
            )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info(
            "request_complete",
            extra={
                "request_id": request_id,
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return safe_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_request",
            "The request could not be processed.",
            request_id,
        )

    @app.exception_handler(AuthorizationFailure)
    async def authorization_error(request: Request, error: AuthorizationFailure) -> JSONResponse:
        default_msg = (
            "Authentication is required or invalid."
            if error.status_code == status.HTTP_401_UNAUTHORIZED
            else "You do not have permission for this resource."
        )
        msg = str(error) if str(error) and str(error) != str(error.status_code) else default_msg
        return safe_error_response(
            error.status_code,
            "authentication_required" if error.status_code == status.HTTP_401_UNAUTHORIZED else "forbidden",
            msg,
            getattr(request.state, "request_id", str(uuid.uuid4())),
        )

    @app.exception_handler(InferenceOverloaded)
    async def inference_overloaded_handler(request: Request, _: InferenceOverloaded) -> JSONResponse:
        return safe_error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "service_overloaded",
            "The assistant service is currently at capacity. Please try again shortly.",
            getattr(request.state, "request_id", str(uuid.uuid4())),
        )

    @app.exception_handler(InferenceUnavailable)
    async def inference_unavailable_handler(request: Request, _: InferenceUnavailable) -> JSONResponse:
        return safe_error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "service_unavailable",
            "The assistant inference service is currently unavailable.",
            getattr(request.state, "request_id", str(uuid.uuid4())),
        )

    @app.exception_handler(MCPAuthorizationError)
    async def mcp_auth_handler(request: Request, error: MCPAuthorizationError) -> JSONResponse:
        return safe_error_response(
            status.HTTP_403_FORBIDDEN,
            "forbidden",
            str(error),
            getattr(request.state, "request_id", str(uuid.uuid4())),
        )

    @app.exception_handler(MCPValidationError)
    async def mcp_validation_handler(request: Request, error: MCPValidationError) -> JSONResponse:
        return safe_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_request",
            str(error),
            getattr(request.state, "request_id", str(uuid.uuid4())),
        )

    @app.exception_handler(MCPToolNotFoundError)
    async def mcp_not_found_handler(request: Request, error: MCPToolNotFoundError) -> JSONResponse:
        return safe_error_response(
            status.HTTP_404_NOT_FOUND,
            "tool_not_found",
            str(error),
            getattr(request.state, "request_id", str(uuid.uuid4())),
        )

    @app.exception_handler(MCPExecutionError)
    async def mcp_execution_handler(request: Request, _: MCPExecutionError) -> JSONResponse:
        return safe_error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "tool_execution_failed",
            "An error occurred while executing the tool.",
            getattr(request.state, "request_id", str(uuid.uuid4())),
        )

    @app.get("/health/live", response_model=HealthResponse, tags=["operations"])
    async def liveness(request: Request) -> HealthResponse:
        return HealthResponse(status="alive", request_id=request.state.request_id)

    @app.get("/health/ready", response_model=HealthResponse, tags=["operations"])
    async def readiness(request: Request):
        if not app.state.ready:
            return safe_error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "not_ready",
                "The service is not ready.",
                request.state.request_id,
            )
        return HealthResponse(status="ready", request_id=request.state.request_id)

    @app.get("/api/v1/auth/config", tags=["authentication"])
    async def auth_config_endpoint():
        is_dev = (settings.enable_development_auth and settings.app_env is not Environment.PRODUCTION)
        return {
            "app_env": settings.app_env.value,
            "enable_quick_signin": is_dev,
            "demo_accounts": settings.dev_demo_accounts if is_dev else [],
        }

    @app.post("/api/v1/auth/login", response_model=LoginResponse, tags=["authentication"])
    async def login_endpoint(request: Request, payload: LoginRequest):
        import jwt
        import secrets

        account_store: AccountStore = app.state.account_store
        account = await anyio.to_thread.run_sync(account_store.authenticate, payload.username, payload.password)
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

        if not account:
            app.state.audit_sink.record(
                new_event("login", "denied", request_id, actor=payload.username.strip().lower(), resource="/api/v1/auth/login")
            )
            return safe_error_response(
                status.HTTP_401_UNAUTHORIZED,
                "invalid_credentials",
                "Invalid username or password, or account is deactivated/locked.",
                request_id,
            )

        jti = str(uuid.uuid4())
        csrf_token = secrets.token_urlsafe(32)
        expires_seconds = settings.session_expiry_minutes * 60
        claims = {
            "sub": account.username,
            "roles": account.roles,
            "aud": settings.auth_audience,
            "jti": jti,
            "exp": int(time.time()) + expires_seconds,
            "token_version": getattr(account, "token_version", 1),
        }
        signing_key = settings.secret_key.get_secret_value()
        token = jwt.encode(claims, signing_key, algorithm="HS256")

        app.state.audit_sink.record(
            new_event("login", "allowed", request_id, actor=account.username, resource="/api/v1/auth/login")
        )

        is_browser = (payload.client_type.lower() == "browser")
        response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content=LoginResponse(
                access_token=None if is_browser else token,
                token_type=None if is_browser else "bearer",
                csrf_token=csrf_token,
                expires_in=expires_seconds,
                user=account.to_dict(),
            ).model_dump(),
        )
        response.set_cookie(
            key="assistant_session",
            value=token,
            max_age=expires_seconds,
            httponly=True,
            samesite="lax",
            path="/",
            secure=(settings.app_env is Environment.PRODUCTION),
        )
        response.set_cookie(
            key="assistant_csrf",
            value=csrf_token,
            max_age=expires_seconds,
            httponly=False,
            samesite="lax",
            path="/",
            secure=(settings.app_env is Environment.PRODUCTION),
        )
        return response

    @app.post("/api/v1/auth/token", response_model=LoginResponse, tags=["authentication"])
    async def api_token_endpoint(request: Request, payload: LoginRequest):
        """Dedicated token endpoint for headless programmatic API clients."""
        payload.client_type = "api"
        return await login_endpoint(request, payload)

    @app.post("/api/v1/auth/logout", response_model=LogoutResponse, tags=["authentication"])
    async def logout_endpoint(request: Request, identity: Identity = Depends(current_identity)):
        import jwt
        token = bearer_token(request)
        try:
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
            jti = unverified_claims.get("jti")
            exp = float(unverified_claims.get("exp", 0.0))
            if jti:
                app.state.revocation_store.revoke(jti, subject=identity.subject, expires_at=exp)
        except Exception:
            pass

        app.state.audit_sink.record(
            new_event("logout", "allowed", request.state.request_id, actor=identity.subject, resource="/api/v1/auth/logout")
        )
        response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content=LogoutResponse(status="logged_out", message="Session successfully terminated").model_dump(),
        )
        response.delete_cookie(key="assistant_session", path="/")
        response.delete_cookie(key="assistant_csrf", path="/")
        return response

    @app.get("/api/v1/session", response_model=SessionResponse, tags=["session"])
    @app.get("/api/v1/auth/me", response_model=SessionResponse, tags=["session"])
    async def session(identity: Identity = Depends(require_permission("chat:use"))) -> SessionResponse:
        return SessionResponse(
            subject=identity.subject,
            roles=sorted(identity.roles),
            permissions=sorted(identity.permissions),
        )

    if settings.enable_development_auth and settings.app_env is not Environment.PRODUCTION and settings.dev_auth_signing_key is not None:
        @app.get("/api/v1/auth/dev-token", tags=["development"])
        async def dev_token_endpoint(user: str | None = None, role: str | None = None):
            import jwt
            account_store: AccountStore = app.state.account_store
            account = None
            if user:
                account = account_store.get_user(user)
            elif role:
                for u in account_store.list_users():
                    if role in u["roles"]:
                        account = account_store.get_user(u["username"])
                        break
            if not account:
                account = account_store.get_user("bob.smith")

            payload = {
                "sub": account.username,
                "roles": account.roles,
                "aud": settings.auth_audience,
                "exp": int(time.time()) + (settings.session_expiry_minutes * 60),
                "jti": str(uuid.uuid4()),
                "token_version": getattr(account, "token_version", 1),
            }
            token = jwt.encode(
                payload,
                settings.dev_auth_signing_key.get_secret_value(),
                algorithm="HS256",
            )
            return {"token": token, "subject": payload["sub"], "roles": payload["roles"]}

    @app.get("/api/v1/admin/users", response_model=UserListResponse, tags=["administration"])
    async def list_users_endpoint(identity: Identity = Depends(require_permission("users:read"))):
        users = app.state.account_store.list_users()
        return UserListResponse(users=[UserResponse(**u) for u in users])

    @app.post("/api/v1/admin/users", response_model=UserResponse, tags=["administration"])
    async def create_user_endpoint(
        request: Request,
        payload: UserProvisionRequest,
        identity: Identity = Depends(require_permission("users:write")),
    ):
        if "admin" in payload.roles and "admin" not in identity.roles:
            app.state.audit_sink.record(
                new_event("user_provision", "denied", request.state.request_id, actor=identity.subject, resource=payload.username)
            )
            app.state.account_store.record_admin_audit(
                actor=identity.subject,
                action="user_created",
                target=payload.username.strip().lower(),
                details={"roles": payload.roles, "error": "Cannot grant admin role without possessing admin privileges"},
                outcome="denied",
            )
            return safe_error_response(
                status.HTTP_403_FORBIDDEN,
                "forbidden",
                "Cannot grant admin role without possessing admin privileges.",
                request.state.request_id,
            )
        try:
            account = app.state.account_store.create_user(
                username=payload.username,
                password=payload.password,
                full_name=payload.full_name,
                roles=payload.roles,
                actor=identity.subject,
            )
            app.state.audit_sink.record(
                new_event("user_provision", "allowed", request.state.request_id, actor=identity.subject, resource=payload.username)
            )
            return UserResponse(**account.to_dict())
        except ValueError as e:
            app.state.audit_sink.record(
                new_event("user_provision", "failed", request.state.request_id, actor=identity.subject, resource=payload.username)
            )
            return safe_error_response(status.HTTP_400_BAD_REQUEST, "invalid_user_data", str(e), request.state.request_id)

    @app.patch("/api/v1/admin/users/{username}", response_model=UserResponse, tags=["administration"])
    async def update_user_endpoint(
        username: str,
        request: Request,
        payload: UserUpdateRequest,
        identity: Identity = Depends(require_permission("users:write")),
    ):
        target_user = username.strip().lower()
        account = app.state.account_store.get_user(target_user)
        if not account:
            return safe_error_response(
                status.HTTP_404_NOT_FOUND,
                "user_not_found",
                f"User '{username}' does not exist",
                request.state.request_id,
            )

        if payload.roles is not None:
            if identity.subject == target_user:
                return safe_error_response(
                    status.HTTP_403_FORBIDDEN,
                    "forbidden",
                    "Self-assignment of roles is strictly prohibited.",
                    request.state.request_id,
                )
            if "admin" in payload.roles and "admin" not in identity.roles:
                return safe_error_response(
                    status.HTTP_403_FORBIDDEN,
                    "forbidden",
                    "Cannot grant admin role without possessing admin privileges.",
                    request.state.request_id,
                )
            app.state.account_store.update_roles(target_user, payload.roles, actor=identity.subject)

        if payload.is_active is not None:
            if identity.subject == target_user and not payload.is_active:
                return safe_error_response(
                    status.HTTP_403_FORBIDDEN,
                    "forbidden",
                    "Cannot deactivate your own administrative account.",
                    request.state.request_id,
                )
            app.state.account_store.set_active_status(target_user, payload.is_active, actor=identity.subject)

        app.state.audit_sink.record(
            new_event("user_update", "allowed", request.state.request_id, actor=identity.subject, resource=target_user)
        )
        updated = app.state.account_store.get_user(target_user)
        return UserResponse(**updated.to_dict())

    @app.post("/api/v1/admin/users/{username}/reset-password", tags=["administration"])
    async def reset_password_endpoint(
        username: str,
        request: Request,
        payload: PasswordResetRequest,
        identity: Identity = Depends(require_permission("users:write")),
    ):
        target_user = username.strip().lower()
        account = app.state.account_store.get_user(target_user)
        if not account:
            return safe_error_response(
                status.HTTP_404_NOT_FOUND,
                "user_not_found",
                f"User '{username}' does not exist",
                request.state.request_id,
            )
        try:
            app.state.account_store.reset_password(target_user, payload.new_password, actor=identity.subject)
            app.state.audit_sink.record(
                new_event("password_reset", "allowed", request.state.request_id, actor=identity.subject, resource=target_user)
            )
            return {"status": "password_reset", "username": target_user}
        except ValueError as e:
            return safe_error_response(status.HTTP_400_BAD_REQUEST, "invalid_password", str(e), request.state.request_id)

    @app.get("/api/v1/admin/audit-status", tags=["administration"])
    async def audit_status(identity: Identity = Depends(require_permission("audit:read"))) -> dict[str, str]:
        return {"status": "available", "actor": identity.subject}

    @app.get("/api/v1/admin/audit-events", response_model=AdminAuditListResponse, tags=["administration"])
    async def audit_events_endpoint(
        limit: int = 50,
        identity: Identity = Depends(require_permission("audit:read")),
    ) -> AdminAuditListResponse:
        events = app.state.account_store.list_admin_audit_events(limit=limit)
        return AdminAuditListResponse(events=events)

    @app.get("/api/v1/admin/metrics", tags=["administration"])
    async def metrics_endpoint(
        identity: Identity = Depends(require_permission("admin:diagnostics")),
    ) -> dict[str, Any]:
        llm_client: LocalLLMClient | None = app.state.llm_client
        if llm_client is not None:
            snapshot = llm_client.metrics()
            avg_latency = (
                round(snapshot.total_latency_seconds / snapshot.completed, 3)
                if snapshot.completed > 0
                else 0.0
            )
            return {
                "in_flight": snapshot.in_flight,
                "queue_depth": snapshot.queue_depth,
                "max_in_flight": snapshot.max_in_flight,
                "max_queue_depth": snapshot.max_queue_depth,
                "accepted": snapshot.accepted,
                "rejected": snapshot.rejected,
                "failed": snapshot.failed,
                "completed": snapshot.completed,
                "total_latency_seconds": round(snapshot.total_latency_seconds, 2),
                "avg_latency_seconds": avg_latency,
            }
        return {"status": "llm_client_not_configured"}

    @app.post("/api/v1/chat", response_model=ChatResponse, tags=["chat"])
    async def chat_endpoint(
        request: Request,
        payload: ChatRequest,
        identity: Identity = Depends(require_permission("chat:use")),
    ) -> ChatResponse:
        assistant: IntranetAssistantService | None = app.state.assistant_service
        if assistant is None:
            return safe_error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "service_unavailable",
                "The assistant inference service is not configured or available.",
                request.state.request_id,
            )
        if hasattr(assistant, "aask"):
            result = await assistant.aask(payload.message, identity, request.state.request_id)
        else:
            result = await anyio.to_thread.run_sync(
                assistant.ask, payload.message, identity, request.state.request_id
            )
        return ChatResponse(
            response=result.response,
            citations=[
                SourceCitationResponse(
                    document_id=c.document_id,
                    filename=c.filename,
                    page=c.page,
                )
                for c in result.citations
            ],
            tool_trace=result.tool_trace,
            request_id=request.state.request_id,
        )

    @app.get("/api/v1/mcp/tools", response_model=MCPToolsListResponse, tags=["mcp"])
    async def list_mcp_tools(
        identity: Identity = Depends(require_permission("chat:use")),
        filter_permissions: bool = False,
    ) -> MCPToolsListResponse:
        descriptors = (
            app.state.tool_registry.list_descriptors_for_identity(identity)
            if filter_permissions
            else app.state.tool_registry.list_descriptors()
        )
        return MCPToolsListResponse(
            tools=[
                MCPToolDescriptor(
                    name=d["name"],
                    description=d["description"],
                    parameters=d["parameters"],
                    required_permission=d["required_permission"],
                )
                for d in descriptors
            ]
        )

    @app.post("/api/v1/mcp/tools/{tool_name}", response_model=MCPCallResponse, tags=["mcp"])
    async def call_mcp_tool(
        request: Request,
        tool_name: str,
        payload: MCPCallRequest,
        identity: Identity = Depends(current_identity),
    ) -> MCPCallResponse:
        result = await anyio.to_thread.run_sync(
            app.state.tool_registry.execute,
            tool_name,
            payload.parameters,
            identity,
            request.state.request_id,
        )
        return MCPCallResponse(
            tool=tool_name,
            content=result.content,
            citations=[
                SourceCitationResponse(
                    document_id=c.document_id,
                    filename=c.filename,
                    page=c.page,
                )
                for c in result.citations
            ],
            request_id=request.state.request_id,
            truncated=result.truncated,
        )

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            index_path = static_dir / "index.html"
            if index_path.is_file():
                return FileResponse(index_path)
            return JSONResponse({"status": "ready", "service": settings.app_name})

    return app

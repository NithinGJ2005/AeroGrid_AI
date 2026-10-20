"""OpenAI-compatible client for a locally hosted model service only."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
import httpx
from pydantic import BaseModel, Field

from app.config import Settings


class InferenceError(Exception):
    """Safe inference error; raw upstream details are intentionally discarded."""


class InferenceOverloaded(InferenceError):
    pass


class InferenceUnavailable(InferenceError):
    pass


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=20000)


@dataclass(frozen=True)
class GenerationResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class InferenceMetrics:
    in_flight: int
    queue_depth: int
    accepted: int
    rejected: int
    failed: int
    completed: int
    total_latency_seconds: float
    max_in_flight: int = 0
    max_queue_depth: int = 0


class HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class BoundedAdmission:
    """Thread-safe and async-safe process-local capacity control with bounded queueing.

    Enforces concurrency limits and finite queue depths without blocking the asyncio event loop.
    Deploy a shared inference gateway or broker to enforce capacity across multiple application
    workers; this class deliberately manages process-local hardware capacity.
    """

    def __init__(self, max_in_flight: int, max_queue_depth: int, max_wait_seconds: int) -> None:
        self._max_in_flight = max_in_flight
        self._max_queue_depth = max_queue_depth
        self._max_wait_seconds = max_wait_seconds
        self._condition = threading.Condition()
        self._async_waiters: list[tuple[asyncio.Event, float, asyncio.AbstractEventLoop]] = []
        self._in_flight = 0
        self._queued = 0
        self._accepted = 0
        self._rejected = 0
        self._failed = 0
        self._completed = 0
        self._total_latency_seconds = 0.0

    def _handle_unclaimed_token(self) -> None:
        """Forward or return an active capacity token granted to a waiter that cancelled or timed out."""
        while self._async_waiters:
            next_event, next_deadline, next_loop = self._async_waiters.pop(0)
            self._queued -= 1
            if time.monotonic() <= next_deadline:
                self._accepted += 1
                try:
                    next_loop.call_soon_threadsafe(next_event.set)
                except RuntimeError:
                    next_event.set()
                return
            else:
                self._rejected += 1
        self._in_flight -= 1
        self._condition.notify()

    def acquire(self) -> None:
        deadline = time.monotonic() + self._max_wait_seconds
        with self._condition:
            if self._in_flight >= self._max_in_flight or self._async_waiters:
                if self._queued >= self._max_queue_depth:
                    self._rejected += 1
                    raise InferenceOverloaded("Inference queue is full")
                self._queued += 1
                try:
                    while self._in_flight >= self._max_in_flight or self._async_waiters:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not self._condition.wait(remaining):
                            self._rejected += 1
                            raise InferenceOverloaded("Inference queue wait limit exceeded")
                finally:
                    self._queued -= 1
            self._in_flight += 1
            self._accepted += 1

    async def acquire_async(self) -> None:
        deadline = time.monotonic() + self._max_wait_seconds
        event = asyncio.Event()
        loop = asyncio.get_running_loop()
        entry = (event, deadline, loop)
        with self._condition:
            if self._in_flight < self._max_in_flight and not self._async_waiters:
                self._in_flight += 1
                self._accepted += 1
                return
            if self._queued >= self._max_queue_depth:
                self._rejected += 1
                raise InferenceOverloaded("Inference queue is full")
            self._queued += 1
            self._async_waiters.append(entry)

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._condition:
                    if entry in self._async_waiters:
                        self._async_waiters.remove(entry)
                        self._queued -= 1
                        self._rejected += 1
                    elif event.is_set():
                        self._handle_unclaimed_token()
                raise InferenceOverloaded("Inference queue wait limit exceeded")

            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                with self._condition:
                    if entry in self._async_waiters:
                        self._async_waiters.remove(entry)
                        self._queued -= 1
                        self._rejected += 1
                    elif event.is_set():
                        self._handle_unclaimed_token()
                raise InferenceOverloaded("Inference queue wait limit exceeded")
        except asyncio.CancelledError:
            with self._condition:
                if entry in self._async_waiters:
                    self._async_waiters.remove(entry)
                    self._queued -= 1
                elif event.is_set():
                    self._handle_unclaimed_token()
            raise

    def release(self, succeeded: bool, latency_seconds: float) -> None:
        with self._condition:
            self._in_flight -= 1
            self._total_latency_seconds += latency_seconds
            if succeeded:
                self._completed += 1
            else:
                self._failed += 1

            # Check if any async waiters are waiting and unexpired
            while self._async_waiters:
                waiter_event, deadline, waiter_loop = self._async_waiters.pop(0)
                self._queued -= 1
                if time.monotonic() <= deadline:
                    self._in_flight += 1
                    self._accepted += 1
                    try:
                        waiter_loop.call_soon_threadsafe(waiter_event.set)
                    except RuntimeError:
                        waiter_event.set()
                    return
                else:
                    self._rejected += 1

            self._condition.notify()

    def snapshot(self) -> InferenceMetrics:
        with self._condition:
            return InferenceMetrics(
                self._in_flight,
                self._queued,
                self._accepted,
                self._rejected,
                self._failed,
                self._completed,
                self._total_latency_seconds,
                self._max_in_flight,
                self._max_queue_depth,
            )


class LocalLLMClient:
    def __init__(
        self,
        settings: Settings,
        client: HttpClient | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.llm_enabled or not settings.llm_base_url:
            raise ValueError("Local LLM inference is not configured")
        self._base_url = settings.llm_base_url.rstrip("/")
        self._model = settings.llm_model
        self._max_output_tokens = settings.llm_max_output_tokens
        self._timeout = settings.llm_request_timeout_seconds

        if client is not None and async_client is None:
            self._client = client
            self._async_client = None
        else:
            self._client = client or httpx.Client(timeout=self._timeout)
            self._async_client = async_client or httpx.AsyncClient(timeout=self._timeout)

        worker_concurrency = getattr(settings, "web_concurrency", 1) or 1
        if worker_concurrency > settings.llm_max_concurrent_generations:
            raise ValueError(
                f"Unsupported concurrency configuration: worker concurrency ({worker_concurrency}) "
                f"exceeds LLM_MAX_CONCURRENT_GENERATIONS ({settings.llm_max_concurrent_generations}). "
                f"Under process-isolated admission control, each worker process requires at least 1 "
                f"active slot, which would multiply aggregate active generations to {worker_concurrency}, "
                f"silently exceeding the global hardware budget of {settings.llm_max_concurrent_generations}."
            )
        worker_max_concurrent = settings.llm_max_concurrent_generations // worker_concurrency
        worker_queue_depth = max(1, settings.llm_max_queue_depth // worker_concurrency)

        self._admission = BoundedAdmission(
            worker_max_concurrent,
            worker_queue_depth,
            settings.llm_max_queue_wait_seconds,
        )

    def generate(self, messages: list[ChatMessage]) -> GenerationResult:
        self._admission.acquire()
        started = time.monotonic()
        succeeded = False
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                json={
                    "model": self._model,
                    "messages": [message.model_dump() for message in messages],
                    "max_tokens": self._max_output_tokens,
                    "stream": False,
                },
                timeout=self._timeout,
            )
            if response.status_code in {429, 503}:
                raise InferenceOverloaded("Internal inference service is busy")
            response.raise_for_status()
            payload = response.json()
            choice = payload["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content:
                raise ValueError("Empty model content")
            usage = payload.get("usage", {})
            succeeded = True
            return GenerationResult(
                content=content,
                model=str(payload.get("model", self._model)),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except InferenceOverloaded:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise InferenceUnavailable("Internal inference service is unavailable") from error
        finally:
            self._admission.release(succeeded, time.monotonic() - started)

    async def agenerate(self, messages: list[ChatMessage]) -> GenerationResult:
        # If subclass overrides generate() or lacks full client setup, delegate safely to generate()
        if type(self).generate is not LocalLLMClient.generate or not hasattr(self, "_admission") or not hasattr(self, "_base_url"):
            return await anyio.to_thread.run_sync(self.generate, messages)

        await self._admission.acquire_async()
        started = time.monotonic()
        succeeded = False
        try:
            payload_data = {
                "model": self._model,
                "messages": [message.model_dump() for message in messages],
                "max_tokens": self._max_output_tokens,
                "stream": False,
            }
            if self._async_client is not None:
                response = await self._async_client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload_data,
                    timeout=self._timeout,
                )
            else:
                response = await anyio.to_thread.run_sync(
                    lambda: self._client.post(
                        f"{self._base_url}/chat/completions",
                        json=payload_data,
                        timeout=self._timeout,
                    )
                )

            if response.status_code in {429, 503}:
                raise InferenceOverloaded("Internal inference service is busy")
            response.raise_for_status()
            payload = response.json()
            choice = payload["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content:
                raise ValueError("Empty model content")
            usage = payload.get("usage", {})
            succeeded = True
            return GenerationResult(
                content=content,
                model=str(payload.get("model", self._model)),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except InferenceOverloaded:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise InferenceUnavailable("Internal inference service is unavailable") from error
        finally:
            self._admission.release(succeeded, time.monotonic() - started)

    def metrics(self) -> InferenceMetrics:
        return self._admission.snapshot()

    def close(self) -> None:
        if hasattr(self._client, "close"):
            try:
                self._client.close()
            except Exception:
                pass

    async def aclose(self) -> None:
        self.close()
        if self._async_client is not None:
            try:
                await self._async_client.aclose()
            except Exception:
                pass

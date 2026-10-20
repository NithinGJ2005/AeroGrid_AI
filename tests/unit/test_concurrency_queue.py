"""Unit tests for async bounded admission, queue saturation, timeout handling, and recovery."""

import asyncio
import time
import pytest

from app.config import Settings
from app.llm.service import (
    BoundedAdmission,
    ChatMessage,
    GenerationResult,
    InferenceOverloaded,
    LocalLLMClient,
)
from app.main import create_app
from starlette.testclient import TestClient


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "secret_key": "x" * 32,
        "dev_auth_signing_key": "y" * 32,
        "llm_enabled": True,
        "llm_base_url": "http://llm.internal:8000/v1",
        "llm_allowed_hosts": ["llm.internal"],
        "llm_model": "qwen2.5:1.5b",
        "llm_max_concurrent_generations": 2,
        "llm_max_queue_depth": 2,
        "llm_max_queue_wait_seconds": 1,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.anyio
async def test_async_bounded_admission_concurrency_limit():
    """Verify that concurrent acquires up to max_in_flight succeed immediately."""
    admission = BoundedAdmission(max_in_flight=2, max_queue_depth=2, max_wait_seconds=1)

    # Acquire two in-flight slots
    await admission.acquire_async()
    await admission.acquire_async()

    snap = admission.snapshot()
    assert snap.in_flight == 2
    assert snap.queue_depth == 0

    # Release one slot
    admission.release(succeeded=True, latency_seconds=0.05)
    snap2 = admission.snapshot()
    assert snap2.in_flight == 1
    assert snap2.completed == 1


@pytest.mark.anyio
async def test_async_bounded_admission_queue_saturation_rejects_with_overload():
    """Verify that exceeding max_queue_depth immediately raises InferenceOverloaded."""
    admission = BoundedAdmission(max_in_flight=1, max_queue_depth=1, max_wait_seconds=5)

    # 1. Fill active slot
    await admission.acquire_async()

    # 2. Start a background waiter (fills the 1 queue slot)
    async def waiter():
        await admission.acquire_async()
        admission.release(succeeded=True, latency_seconds=0.01)

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)  # Let waiter enter the queue

    snap = admission.snapshot()
    assert snap.in_flight == 1
    assert snap.queue_depth == 1

    # 3. Third acquire must be rejected immediately with InferenceOverloaded (queue full)
    with pytest.raises(InferenceOverloaded):
        await admission.acquire_async()

    assert admission.snapshot().rejected == 1

    # 4. Release active slot -> waiter gets slot and completes
    admission.release(succeeded=True, latency_seconds=0.1)
    await waiter_task

    final_snap = admission.snapshot()
    assert final_snap.in_flight == 0
    assert final_snap.queue_depth == 0
    assert final_snap.completed == 2


@pytest.mark.anyio
async def test_async_bounded_admission_timeout():
    """Verify that requests waiting longer than max_wait_seconds time out cleanly."""
    admission = BoundedAdmission(max_in_flight=1, max_queue_depth=5, max_wait_seconds=0.05)

    # Occupy active slot
    await admission.acquire_async()

    # Next acquire will queue, then time out after 0.05s
    started = time.monotonic()
    with pytest.raises(InferenceOverloaded):
        await admission.acquire_async()
    elapsed = time.monotonic() - started

    assert elapsed >= 0.04
    assert admission.snapshot().rejected == 1

    # Cleanup
    admission.release(succeeded=True, latency_seconds=0.1)
    assert admission.snapshot().in_flight == 0


@pytest.mark.anyio
async def test_async_bounded_admission_capacity_released_on_failure():
    """Verify capacity is released and metrics record failure when an error occurs."""
    admission = BoundedAdmission(max_in_flight=1, max_queue_depth=1, max_wait_seconds=1)

    await admission.acquire_async()
    assert admission.snapshot().in_flight == 1

    # Simulated task failure
    admission.release(succeeded=False, latency_seconds=0.02)
    snap = admission.snapshot()
    assert snap.in_flight == 0
    assert snap.failed == 1
    assert snap.completed == 0


@pytest.mark.anyio
async def test_async_bounded_admission_cancellation_cleans_up_without_leaks():
    """Verify that cancelling a waiting coroutine cleans up queue depth and does not leak slots."""
    admission = BoundedAdmission(max_in_flight=1, max_queue_depth=5, max_wait_seconds=10)

    # Occupy active slot
    await admission.acquire_async()
    assert admission.snapshot().in_flight == 1

    # Start a background waiter that will queue
    waiter_task = asyncio.create_task(admission.acquire_async())
    await asyncio.sleep(0.01)

    assert admission.snapshot().queue_depth == 1

    # Cancel waiter
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    snap = admission.snapshot()
    assert snap.queue_depth == 0
    assert snap.in_flight == 1

    # Normal release
    admission.release(succeeded=True, latency_seconds=0.05)
    assert admission.snapshot().in_flight == 0


@pytest.mark.anyio
async def test_multi_worker_capacity_partitioning_baseline_2_generations():
    """Verify concurrency guarantees with standard baseline: LLM_MAX_CONCURRENT_GENERATIONS = 2, QUEUE = 10."""
    # Worker count = 1: Supported, gets full capacity (2 active, 10 queued)
    cfg1 = make_settings(llm_max_concurrent_generations=2, llm_max_queue_depth=10, web_concurrency=1)
    client1 = LocalLLMClient(cfg1)
    assert client1._admission._max_in_flight == 2
    assert client1._admission._max_queue_depth == 10
    client1.close()

    # Worker count = 2: Supported, partitioned evenly (1 active, 5 queued) -> aggregate 2 active, 10 queue
    cfg2 = make_settings(llm_max_concurrent_generations=2, llm_max_queue_depth=10, web_concurrency=2)
    client2 = LocalLLMClient(cfg2)
    assert client2._admission._max_in_flight == 1
    assert client2._admission._max_queue_depth == 5
    client2.close()

    # Worker count = 3: Unsupported (3 > 2). Must raise ValueError in Settings validation
    with pytest.raises(ValueError, match="exceeds LLM_MAX_CONCURRENT_GENERATIONS"):
        make_settings(llm_max_concurrent_generations=2, llm_max_queue_depth=10, web_concurrency=3)

    # Worker count = 4: Unsupported (4 > 2). Must raise ValueError in Settings validation
    with pytest.raises(ValueError, match="exceeds LLM_MAX_CONCURRENT_GENERATIONS"):
        make_settings(llm_max_concurrent_generations=2, llm_max_queue_depth=10, web_concurrency=4)


@pytest.mark.anyio
async def test_multi_worker_capacity_partitioning_scaled_4_generations():
    """Verify concurrency guarantees when scaled to 4 generations: LLM_MAX_CONCURRENT_GENERATIONS = 4, QUEUE = 16."""
    # Worker count = 1: gets 4 active, 16 queued
    cfg1 = make_settings(llm_max_concurrent_generations=4, llm_max_queue_depth=16, web_concurrency=1)
    client1 = LocalLLMClient(cfg1)
    assert client1._admission._max_in_flight == 4
    assert client1._admission._max_queue_depth == 16
    client1.close()

    # Worker count = 2: gets 2 active, 8 queued -> aggregate 4 active, 16 queued
    cfg2 = make_settings(llm_max_concurrent_generations=4, llm_max_queue_depth=16, web_concurrency=2)
    client2 = LocalLLMClient(cfg2)
    assert client2._admission._max_in_flight == 2
    assert client2._admission._max_queue_depth == 8
    client2.close()

    # Worker count = 3: gets 1 active, 5 queued -> aggregate 3 active (<= 4 budget), 15 queued (<= 16)
    cfg3 = make_settings(llm_max_concurrent_generations=4, llm_max_queue_depth=16, web_concurrency=3)
    client3 = LocalLLMClient(cfg3)
    assert client3._admission._max_in_flight == 1
    assert client3._admission._max_queue_depth == 5
    client3.close()

    # Worker count = 4: gets 1 active, 4 queued -> aggregate 4 active, 16 queued
    cfg4 = make_settings(llm_max_concurrent_generations=4, llm_max_queue_depth=16, web_concurrency=4)
    client4 = LocalLLMClient(cfg4)
    assert client4._admission._max_in_flight == 1
    assert client4._admission._max_queue_depth == 4
    client4.close()

    # Worker count = 5 with 4 budget: Rejected
    with pytest.raises(ValueError, match="exceeds LLM_MAX_CONCURRENT_GENERATIONS"):
        make_settings(llm_max_concurrent_generations=4, llm_max_queue_depth=16, web_concurrency=5)


@pytest.mark.anyio
async def test_unclaimed_token_recovery_when_waiter_cancelled_at_grant():
    """Verify slot is not leaked if release() grants a slot to a waiter just as it cancels."""
    admission = BoundedAdmission(max_in_flight=1, max_queue_depth=2, max_wait_seconds=5)

    await admission.acquire_async()

    # Waiter 1 will be cancelled right after release
    waiter1_task = asyncio.create_task(admission.acquire_async())
    # Waiter 2 queued behind waiter 1
    waiter2_task = asyncio.create_task(admission.acquire_async())
    await asyncio.sleep(0.01)

    assert admission.snapshot().queue_depth == 2

    # Release active slot, which pops waiter1 and sets its event
    admission.release(succeeded=True, latency_seconds=0.1)

    # Simultaneously cancel waiter1
    waiter1_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter1_task

    # Waiter 2 should receive the forwarded slot and complete
    await asyncio.wait_for(waiter2_task, timeout=1.0)
    assert admission.snapshot().in_flight == 1

    admission.release(succeeded=True, latency_seconds=0.1)
    assert admission.snapshot().in_flight == 0


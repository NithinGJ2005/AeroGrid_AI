"""Pytest configuration ensuring anyio runs with asyncio backend."""

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"

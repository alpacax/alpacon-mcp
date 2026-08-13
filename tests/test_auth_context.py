"""Unit tests for the ContextVar-backed token store."""

import asyncio

import pytest

from utils.auth_context import current_token, set_token


def test_current_token_defaults_to_none() -> None:
    assert current_token() is None


@pytest.mark.asyncio
async def test_set_then_get_returns_the_token() -> None:
    set_token('tok-a')
    assert current_token() == 'tok-a'


@pytest.mark.asyncio
async def test_token_is_isolated_between_tasks() -> None:
    async def child(value: str) -> str | None:
        set_token(value)
        await asyncio.sleep(0)
        return current_token()

    results = await asyncio.gather(child('tok-1'), child('tok-2'))
    assert results == ['tok-1', 'tok-2']
    # The children ran in their own task contexts; nothing leaked out.
    assert current_token() is None

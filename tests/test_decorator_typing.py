"""Typing probe: mypy fails here if the decorator chain erases signatures.

assert_type is a no-op at runtime; the real assertion happens in
`uv run mypy .`. The call is awaited only so the coroutine is consumed.

The `-> None` below is load-bearing: inside an unannotated function mypy types
everything as Any, and assert_type then demands Any too.
"""

from collections.abc import Awaitable
from typing import Any, assert_type

import pytest

from utils.decorators import with_error_handling, with_logging, with_token_validation


async def _sample_tool(
    workspace: str, region: str = '', **kwargs: Any
) -> dict[str, Any]:
    return {'status': 'success'}


@pytest.mark.asyncio
async def test_decorator_chain_preserves_signature() -> None:
    wrapped = with_logging(with_token_validation(with_error_handling(_sample_tool)))
    call = wrapped('testws')
    assert_type(call, Awaitable[dict[str, Any]])
    assert isinstance(await call, dict)

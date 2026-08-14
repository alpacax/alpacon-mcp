"""with_token_validation must write the token to auth_context AND kwargs."""

from unittest.mock import AsyncMock, patch

import pytest

from utils.auth_context import current_token
from utils.decorators import with_token_validation


def _make_probe(seen: dict[str, str | None]):
    async def probe(workspace: str, region: str = '', **kwargs) -> dict[str, str]:
        seen['context'] = current_token()
        seen['kwargs'] = kwargs.get('token')
        return {'status': 'success'}

    return probe


@pytest.mark.asyncio
async def test_stdio_mode_dual_writes_token() -> None:
    seen: dict[str, str | None] = {}
    wrapped = with_token_validation(_make_probe(seen))
    with (
        patch('utils.decorators.is_auth_enabled', return_value=False),
        patch('utils.decorators.validate_token', return_value='stdio-tok'),
    ):
        result = await wrapped(workspace='testws', region='ap1')

    assert result == {'status': 'success'}
    assert seen == {'context': 'stdio-tok', 'kwargs': 'stdio-tok'}


@pytest.mark.asyncio
async def test_jwt_mode_dual_writes_token() -> None:
    seen: dict[str, str | None] = {}
    wrapped = with_token_validation(_make_probe(seen))
    with (
        patch('utils.decorators.is_auth_enabled', return_value=True),
        patch('utils.decorators._get_jwt_token', return_value='jwt-tok'),
        patch('utils.decorators._validate_jwt_workspace', return_value=True),
        patch('utils.decorators._check_mfa_requirement', new=AsyncMock()),
    ):
        result = await wrapped(workspace='testws', region='ap1')

    assert result == {'status': 'success'}
    assert seen == {'context': 'jwt-tok', 'kwargs': 'jwt-tok'}

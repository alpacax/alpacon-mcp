"""show_mfa's link placement per client surface, get_mfa_completion, and the MFA app resource."""

import json
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp import Client
from mcp.client.extension import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import CallToolResult, ClientCapabilities, TextContent

from server import mcp
from tests.conftest import APPS_CAPS, HTTP_ERROR_ENVELOPE, in_tool_call_round
from tools import mfa_tools
from utils import request_signal
from utils.http_client import AlpaconHTTPClient, http_client

JWT = 'header.payload.signature'
CLAIMS = [{'schema_name': 'acme', 'region': 'ap1'}]
MFA_URL = 'https://auth.example/authorize?step_up_ticket=t'
MODERN = '2026-07-28'


@pytest.fixture
def remote_jwt(monkeypatch):
    """JWT mode; the shared client's get answers both MFA endpoints."""
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')
    get = AsyncMock(return_value={'mfa_url': MFA_URL})
    with (
        patch('utils.decorators._get_jwt_token', return_value=JWT),
        patch('utils.decorators.get_token_workspaces', return_value=CLAIMS),
        patch.object(http_client, 'get', get),
    ):
        yield get


async def _show(
    capabilities: ClientCapabilities | None, protocol_version: str
) -> CallToolResult:
    result = await in_tool_call_round(
        capabilities, lambda: mfa_tools.show_mfa(workspace='acme'), protocol_version
    )
    assert isinstance(result, CallToolResult)
    return result


def _text(result: CallToolResult) -> str:
    [block] = result.content
    assert isinstance(block, TextContent)
    return block.text


def _visible_text(result: CallToolResult) -> str:
    return _text(result) + json.dumps(result.structured_content)


@pytest.mark.asyncio
async def test_show_mfa_on_an_apps_client_puts_the_link_in_meta_alone(remote_jwt):
    result = await _show(APPS_CAPS, MODERN)

    assert result.meta == {'alpacon/mfa': {'mfa_url': MFA_URL}}
    assert MFA_URL not in _visible_text(result)
    assert result.structured_content is not None
    assert result.structured_content['status'] == 'mfa_link_shown'
    assert (
        result.structured_content['workspace'],
        result.structured_content['region'],
    ) == ('acme', 'ap1')
    assert json.loads(_text(result)) == result.structured_content


@pytest.mark.asyncio
async def test_show_mfa_on_an_apps_client_defers_the_retry_and_offers_the_panel_copy(
    remote_jwt,
):
    result = await _show(APPS_CAPS, MODERN)

    assert result.structured_content is not None
    message = result.structured_content['message']
    assert "refused call's own mfa_required" in message
    assert 'same arguments' not in message
    assert 'copy the link the panel shows' in message
    assert 'do not call show_mfa again' in message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'capabilities',
    [
        ClientCapabilities(),
        ClientCapabilities.model_validate(
            {'extensions': {EXTENSION_ID: {'mimeTypes': ['text/html']}}}
        ),
    ],
    ids=['declared-absent', 'apps-without-our-type'],
)
async def test_show_mfa_on_a_client_without_mcp_apps_answers_with_the_link_alone(
    remote_jwt, capabilities
):
    result = await _show(capabilities, MODERN)

    assert result.meta is None
    assert result.structured_content is not None
    assert result.structured_content['status'] == 'mfa_required'
    assert result.structured_content['mfa_url'] == MFA_URL
    assert MFA_URL in _text(result)
    assert 'show_mfa' not in result.structured_content['message']


@pytest.mark.asyncio
async def test_show_mfa_on_a_client_of_unknown_support_hands_the_link_to_text_and_panel(
    remote_jwt,
):
    result = await _show(None, '2025-11-25')

    assert result.meta == {'alpacon/mfa': {'mfa_url': MFA_URL}}
    assert MFA_URL in _text(result)
    assert result.structured_content is not None
    assert result.structured_content['status'] == 'mfa_required'
    assert result.structured_content['mfa_url'] == MFA_URL


@pytest.mark.asyncio
async def test_show_mfa_when_mfa_is_already_fresh_reports_completed(remote_jwt):
    remote_jwt.return_value = {'detail': 'MFA is already done.'}

    result = await _show(APPS_CAPS, MODERN)

    assert result.meta is None
    assert result.structured_content is not None
    assert result.structured_content['status'] == 'success'
    assert result.structured_content['completed'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('answer', 'status_code'),
    [
        ({'error': 'HTTP Error', 'status_code': HTTPStatus.FORBIDDEN}, 403),
        ({'unexpected': True}, None),
        (RuntimeError('boom'), None),
    ],
    ids=['upstream-refusal', 'no-link', 'raised'],
)
async def test_show_mfa_without_a_link_is_the_error_envelope(
    remote_jwt, answer, status_code
):
    if isinstance(answer, Exception):
        remote_jwt.side_effect = answer
    else:
        remote_jwt.return_value = answer

    result = await _show(APPS_CAPS, MODERN)

    assert result.meta is None
    assert result.structured_content is not None
    assert result.structured_content['status'] == 'error'
    assert result.structured_content.get('status_code') == status_code
    if status_code is not None:  # hints are keyed by status code
        assert 'recovery_hints' in result.structured_content


@pytest.mark.asyncio
async def test_show_mfa_when_alpacon_answers_without_a_link_says_so(remote_jwt):
    remote_jwt.return_value = {'unexpected': True}

    result = await _show(APPS_CAPS, MODERN)

    assert result.structured_content is not None
    assert 'answered without an MFA link' in result.structured_content['message']


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('extensions', 'meta'),
    [
        ([advertise(EXTENSION_ID, {'mimeTypes': [APP_MIME_TYPE]})], True),
        (None, False),
    ],
    ids=['apps', 'no-apps'],
)
async def test_show_mfa_link_meta_survives_the_sdk_tools_call(
    remote_jwt, extensions, meta
):
    request_signal.begin_request()
    try:
        async with Client(mcp, mode=MODERN, extensions=extensions) as client:
            result = await client.call_tool('show_mfa', {'workspace': 'acme'})
    finally:
        request_signal.end_request()

    assert ((result.meta or {}).get('alpacon/mfa') == {'mfa_url': MFA_URL}) is meta
    assert result.structured_content is not None
    assert result.structured_content['status'] == (
        'mfa_link_shown' if meta else 'mfa_required'
    )


@pytest.mark.asyncio
async def test_show_mfa_when_the_link_fetch_raises_says_it_failed(remote_jwt):
    remote_jwt.side_effect = RuntimeError('connect timeout')

    result = await _show(APPS_CAPS, MODERN)

    assert result.structured_content is not None
    assert result.structured_content['status'] == 'error'
    assert result.structured_content['message'] == 'Failed to get the MFA link'


@pytest.mark.asyncio
async def test_show_mfa_refused_for_mfa_itself_asks_for_a_whole_retry_without_a_link(
    remote_jwt,
):
    refusal = MagicMock(status_code=HTTPStatus.UNAUTHORIZED)
    refusal.json.return_value = {'code': 'auth_mfa_required', 'source': 'auth'}
    error = httpx.HTTPStatusError('401', request=MagicMock(), response=refusal)
    remote_jwt.side_effect = lambda *args, **kwargs: (
        AlpaconHTTPClient._handle_upstream_401(error, token=JWT)
    )
    request_signal.begin_request()
    try:
        result = await in_tool_call_round(
            APPS_CAPS, lambda: mfa_tools.show_mfa(workspace='acme')
        )
    finally:
        request_signal.end_request()

    assert isinstance(result, dict)
    assert result['status'] == 'mfa_required'
    assert result['mfa_url'] is None
    assert 'partial_result' not in result
    assert 'retry the same call once' in result['message']


@pytest.mark.asyncio
@pytest.mark.parametrize('completed', [True, False])
async def test_get_mfa_completion_reports_the_server_answer(remote_jwt, completed):
    remote_jwt.return_value = {'completed': completed}

    result = await in_tool_call_round(
        APPS_CAPS, lambda: mfa_tools.get_mfa_completion(workspace='acme')
    )

    assert result['status'] == 'success'
    assert result['data'] == {'completed': completed}
    assert remote_jwt.await_args is not None
    assert remote_jwt.await_args.kwargs == {
        'region': 'ap1',
        'workspace': 'acme',
        'endpoint': '/api/auth0/mfa/completion/',
        'token': JWT,
    }


@pytest.mark.asyncio
async def test_get_mfa_completion_on_a_server_without_it_is_an_error(remote_jwt):
    remote_jwt.return_value = HTTP_ERROR_ENVELOPE

    result = await in_tool_call_round(
        APPS_CAPS, lambda: mfa_tools.get_mfa_completion(workspace='acme')
    )

    assert result['status'] == 'error'
    assert result['status_code'] == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_mfa_tools_are_bound_to_the_mfa_app():
    tools = {t.name: t for t in await mcp.list_tools()}

    assert (tools['show_mfa'].meta or {})['ui'] == {'resourceUri': 'ui://alpacon/mfa'}
    assert (tools['get_mfa_completion'].meta or {})['ui'] == {
        'resourceUri': 'ui://alpacon/mfa',
        'visibility': ['app'],
    }


@pytest.mark.asyncio
async def test_mfa_app_resource_reads_back_as_app_html():
    [contents] = await mcp.read_resource('ui://alpacon/mfa')

    assert isinstance(contents, ReadResourceContents)
    assert contents.mime_type == APP_MIME_TYPE
    assert isinstance(contents.content, str)
    assert 'ui/open-link' in contents.content
    assert 'get_mfa_completion' in contents.content
    assert f"_meta['{mfa_tools.MFA_LINK_META_KEY}']" in contents.content


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['show_mfa', 'get_mfa_completion'])
async def test_mfa_tools_refuse_a_static_api_token_before_any_request(remote_jwt, tool):
    with patch('utils.decorators._get_jwt_token', return_value='static-api-token'):
        result = await in_tool_call_round(
            APPS_CAPS, lambda: getattr(mfa_tools, tool)(workspace='acme')
        )

    assert isinstance(result, dict)
    assert result['status'] == 'error'
    assert 'requires JWT' in result['message']
    remote_jwt.assert_not_called()

"""Unit tests for the command pre-approval ledger's device authorization."""

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from utils import ledger_auth
from utils.ledger_auth import (
    AUTHORIZATION_REQUIRED,
    DEFAULT_LEDGER_AUDIENCE,
    LedgerAuthorizer,
    LedgerTarget,
    ledger_audience,
    ledger_base_url,
)

TARGET = LedgerTarget(
    domain='auth.example.com',
    client_id='cli-client',
    org_name='acme',
    workspace_id='11111111-2222-3333-4444-555555555555',
)

DEVICE_CODE_BODY = {
    'device_code': 'dev-code',
    'user_code': 'ABCD-EFGH',
    'verification_uri': 'https://auth.example.com/activate',
    'verification_uri_complete': 'https://auth.example.com/activate?user_code=ABCD-EFGH',
    'expires_in': 900,
    'interval': 5,
}


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def clock():
    c = Clock()
    with patch.object(ledger_auth, '_now', c):
        yield c


@pytest.fixture
def auth0():
    with patch.object(ledger_auth, '_post_form', new_callable=AsyncMock) as post:
        yield post


@pytest.fixture
def authorizer():
    return LedgerAuthorizer()


class TestSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv(ledger_auth.LEDGER_URL_ENV, raising=False)
        monkeypatch.delenv(ledger_auth.LEDGER_AUDIENCE_ENV, raising=False)
        assert ledger_base_url() == 'https://alpacon.ai'
        assert ledger_audience() == 'https://alpacon.ai/'

    def test_overrides_strip_the_url_but_keep_the_audience_verbatim(self, monkeypatch):
        monkeypatch.setenv(ledger_auth.LEDGER_URL_ENV, 'https://ledger.test/')
        monkeypatch.setenv(ledger_auth.LEDGER_AUDIENCE_ENV, 'https://ledger.test/')
        assert ledger_base_url() == 'https://ledger.test'
        assert ledger_audience() == 'https://ledger.test/'


class TestDeviceAuthorization:
    @pytest.mark.asyncio
    async def test_first_call_starts_the_flow_for_the_ledger_audience(
        self, authorizer, auth0, clock
    ):
        auth0.return_value = (HTTPStatus.OK, DEVICE_CODE_BODY)

        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == AUTHORIZATION_REQUIRED
        assert result['verification_uri_complete'].endswith('user_code=ABCD-EFGH')
        assert result['user_code'] == 'ABCD-EFGH'
        assert result['expires_in'] == 900
        url, form = auth0.call_args.args
        assert url == 'https://auth.example.com/oauth/device/code'
        assert form['client_id'] == 'cli-client'
        assert form['audience'] == DEFAULT_LEDGER_AUDIENCE
        assert 'org:acme' in form['scope'].split()
        assert 'offline_access' not in form['scope'].split()

    @pytest.mark.asyncio
    async def test_a_call_before_the_interval_does_not_poll(
        self, authorizer, auth0, clock
    ):
        auth0.return_value = (HTTPStatus.OK, DEVICE_CODE_BODY)
        await authorizer.token_for(TARGET)
        clock.value += 2

        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == AUTHORIZATION_REQUIRED
        assert auth0.await_count == 1

    @pytest.mark.asyncio
    async def test_poll_pending_then_approved_caches_the_token(
        self, authorizer, auth0, clock
    ):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.FORBIDDEN, {'error': 'authorization_pending'}),
            (HTTPStatus.OK, {'access_token': 'ledger-jwt', 'expires_in': 86400}),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5

        pending = await authorizer.token_for(TARGET)
        assert isinstance(pending, dict)
        assert pending['status'] == AUTHORIZATION_REQUIRED

        clock.value += 5
        assert await authorizer.token_for(TARGET) == 'ledger-jwt'
        url, form = auth0.call_args.args
        assert url == 'https://auth.example.com/oauth/token'
        assert form['grant_type'] == 'urn:ietf:params:oauth:grant-type:device_code'
        assert form['device_code'] == 'dev-code'

        # Cached: no further Auth0 call.
        clock.value += 3600
        assert await authorizer.token_for(TARGET) == 'ledger-jwt'
        assert auth0.await_count == 3

    @pytest.mark.asyncio
    async def test_slow_down_widens_the_interval(self, authorizer, auth0, clock):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.TOO_MANY_REQUESTS, {'error': 'slow_down'}),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5
        await authorizer.token_for(TARGET)

        # The interval is now 10s, so 5s later is still too early to poll.
        clock.value += 5
        await authorizer.token_for(TARGET)
        assert auth0.await_count == 2

    @pytest.mark.asyncio
    async def test_a_declined_authorization_is_an_error_and_the_next_call_restarts(
        self, authorizer, auth0, clock
    ):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.FORBIDDEN, {'error': 'access_denied'}),
            (HTTPStatus.OK, DEVICE_CODE_BODY),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5

        declined = await authorizer.token_for(TARGET)
        assert isinstance(declined, dict)
        assert declined['status'] == 'error'
        assert declined['error_code'] == 'access_denied'

        restarted = await authorizer.token_for(TARGET)
        assert isinstance(restarted, dict)
        assert restarted['status'] == AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_an_expired_device_code_starts_a_new_one(
        self, authorizer, auth0, clock
    ):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.FORBIDDEN, {'error': 'expired_token'}),
            (HTTPStatus.OK, {**DEVICE_CODE_BODY, 'device_code': 'dev-code-2'}),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5

        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == AUTHORIZATION_REQUIRED
        assert auth0.call_args.args[0].endswith('/oauth/device/code')

    @pytest.mark.asyncio
    async def test_a_lapsed_pending_authorization_is_replaced(
        self, authorizer, auth0, clock
    ):
        auth0.return_value = (HTTPStatus.OK, DEVICE_CODE_BODY)
        await authorizer.token_for(TARGET)
        clock.value += 901

        await authorizer.token_for(TARGET)

        assert auth0.await_count == 2
        assert auth0.call_args.args[0].endswith('/oauth/device/code')

    @pytest.mark.asyncio
    async def test_an_expired_token_asks_again(self, authorizer, auth0, clock):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.OK, {'access_token': 'ledger-jwt', 'expires_in': 120}),
            (HTTPStatus.OK, DEVICE_CODE_BODY),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5
        assert await authorizer.token_for(TARGET) == 'ledger-jwt'

        clock.value += 61  # past expires_in minus the skew
        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_has_token_reports_only_an_unexpired_cached_token(
        self, authorizer, auth0, clock
    ):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.OK, {'access_token': 'ledger-jwt', 'expires_in': 120}),
        ]
        assert not authorizer.has_token(TARGET)
        await authorizer.token_for(TARGET)
        assert not authorizer.has_token(TARGET)
        clock.value += 5
        await authorizer.token_for(TARGET)
        assert authorizer.has_token(TARGET)

        clock.value += 61
        assert not authorizer.has_token(TARGET)

    @pytest.mark.asyncio
    async def test_forget_drops_the_cached_token(self, authorizer, auth0, clock):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.OK, {'access_token': 'ledger-jwt', 'expires_in': 86400}),
            (HTTPStatus.OK, DEVICE_CODE_BODY),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5
        await authorizer.token_for(TARGET)

        authorizer.forget(TARGET)
        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_targets_do_not_share_tokens(self, authorizer, auth0, clock):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.OK, {'access_token': 'ledger-jwt', 'expires_in': 86400}),
            (HTTPStatus.OK, DEVICE_CODE_BODY),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5
        await authorizer.token_for(TARGET)

        other = LedgerTarget(
            domain=TARGET.domain,
            client_id=TARGET.client_id,
            org_name='other',
            workspace_id='99999999-2222-3333-4444-555555555555',
        )
        result = await authorizer.token_for(other)

        assert isinstance(result, dict)
        assert 'org:other' in auth0.call_args.args[1]['scope'].split()

    @pytest.mark.asyncio
    async def test_lifetime_falls_back_to_the_exp_claim(self, authorizer, auth0, clock):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.OK, {'access_token': 'ledger-jwt'}),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5
        with (
            patch.object(
                ledger_auth, 'decode_claims_unverified', return_value={'exp': 4000}
            ),
            patch('utils.ledger_auth.time.time', return_value=1000.0),
        ):
            assert await authorizer.token_for(TARGET) == 'ledger-jwt'

        clock.value += 2000
        assert await authorizer.token_for(TARGET) == 'ledger-jwt'
        assert auth0.await_count == 2

    @pytest.mark.asyncio
    async def test_a_boolean_device_interval_and_lifetime_read_as_the_defaults(
        self, authorizer, auth0, clock
    ):
        auth0.return_value = (
            HTTPStatus.OK,
            {**DEVICE_CODE_BODY, 'interval': True, 'expires_in': True},
        )
        started = await authorizer.token_for(TARGET)
        clock.value += 2

        result = await authorizer.token_for(TARGET)

        assert started['expires_in'] == 900
        assert result['status'] == AUTHORIZATION_REQUIRED
        assert auth0.await_count == 1

    @pytest.mark.asyncio
    async def test_a_boolean_expires_in_falls_back_to_the_exp_claim(
        self, authorizer, auth0, clock
    ):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.OK, {'access_token': 'ledger-jwt', 'expires_in': True}),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5
        with (
            patch.object(
                ledger_auth, 'decode_claims_unverified', return_value={'exp': 4000}
            ),
            patch('utils.ledger_auth.time.time', return_value=1000.0),
        ):
            await authorizer.token_for(TARGET)

        assert authorizer.has_token(TARGET) is True

    @pytest.mark.asyncio
    async def test_a_token_without_a_lifetime_is_used_once(
        self, authorizer, auth0, clock
    ):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            (HTTPStatus.OK, {'access_token': 'not-a-jwt'}),
            (HTTPStatus.OK, DEVICE_CODE_BODY),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5
        assert await authorizer.token_for(TARGET) == 'not-a-jwt'

        result = await authorizer.token_for(TARGET)
        assert isinstance(result, dict)
        assert result['status'] == AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_a_refused_start_is_an_error(self, authorizer, auth0, clock):
        auth0.return_value = (
            HTTPStatus.FORBIDDEN,
            {'error': 'unauthorized_client', 'error_description': 'no device grant'},
        )

        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == 'error'
        assert result['error_code'] == 'unauthorized_client'
        assert result['detail'] == 'no device grant'

    @pytest.mark.asyncio
    async def test_an_unreachable_auth0_is_an_error(self, authorizer, auth0, clock):
        auth0.side_effect = httpx.ConnectError('down')

        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_a_poll_network_error_keeps_waiting(self, authorizer, auth0, clock):
        auth0.side_effect = [
            (HTTPStatus.OK, DEVICE_CODE_BODY),
            httpx.ConnectError('down'),
        ]
        await authorizer.token_for(TARGET)
        clock.value += 5

        result = await authorizer.token_for(TARGET)

        assert isinstance(result, dict)
        assert result['status'] == AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_clear_drops_everything(self, authorizer, auth0, clock):
        auth0.return_value = (HTTPStatus.OK, DEVICE_CODE_BODY)
        await authorizer.token_for(TARGET)

        authorizer.clear()
        clock.value += 5
        await authorizer.token_for(TARGET)

        assert auth0.call_args.args[0].endswith('/oauth/device/code')


class TestPostForm:
    @pytest.mark.asyncio
    async def test_returns_status_and_object_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers['content-type'] == (
                'application/x-www-form-urlencoded'
            )
            assert b'client_id=cli-client' in request.content
            return httpx.Response(HTTPStatus.OK, json={'device_code': 'x'})

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            'utils.ledger_auth.httpx.AsyncClient',
            lambda **kw: real_client(transport=transport, **kw),
        ):
            status, body = await ledger_auth._post_form(
                'https://auth.example.com/oauth/device/code',
                {'client_id': 'cli-client'},
            )

        assert status == HTTPStatus.OK
        assert body == {'device_code': 'x'}

    @pytest.mark.asyncio
    async def test_a_non_json_body_reads_as_empty(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(HTTPStatus.BAD_GATEWAY, text='oops')
        )
        real_client = httpx.AsyncClient
        with patch(
            'utils.ledger_auth.httpx.AsyncClient',
            lambda **kw: real_client(transport=transport, **kw),
        ):
            status, body = await ledger_auth._post_form('https://x/oauth/token', {})

        assert status == HTTPStatus.BAD_GATEWAY
        assert body == {}

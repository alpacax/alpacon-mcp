"""Start each transport entry point as a real process and observe it boot.
Deselected by default; run with ``pytest -m smoke``.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict

import httpx
import pytest

pytestmark = pytest.mark.smoke


class _ServerInfo(TypedDict):
    name: str


class _InitializeResult(TypedDict):
    serverInfo: _ServerInfo  # noqa: N815 - the JSON-RPC field name


class _JsonRpcReply(TypedDict):  # the parts of the initialize reply the tests read
    id: int
    result: _InitializeResult


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOT_TIMEOUT = 60
PUBLIC_HOST = 'mcp.dev.alpacon.io'
HTTP_MISDIRECTED = 421
INITIALIZE = {
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'initialize',
    'params': {
        'protocolVersion': '2025-06-18',
        'capabilities': {},
        'clientInfo': {'name': 'smoke', 'version': '0'},
    },
}


# Real main_http.py with only the token check stubbed: the JWKS URL is always
# https://<AUTH0_ALPACON_DOMAIN>, so nothing could pass authentication on loopback.
STUBBED_AUTH_LAUNCH = """
import runpy
from mcp.server.auth.provider import AccessToken
from utils.auth import Auth0TokenVerifier

async def _accept(self, token):
    return AccessToken(
        token=token, client_id='smoke-client-id', scopes=['openid'],
        expires_at=None, subject='auth0|smoke', claims={'sub': 'auth0|smoke'},
    )

setattr(Auth0TokenVerifier, 'verify_token', _accept)
runpy.run_path('main_http.py', run_name='__main__')
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port: int = s.getsockname()[1]
    return port


@pytest.fixture
def entry_env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / 'token.json'
    config.write_text(json.dumps({'ap1': {'smoke-workspace': 'dummy-token'}}))
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(('ALPACON_', 'AUTH0_'))
    }
    env.update(
        HOME=str(tmp_path),
        PYTHONPATH=REPO_ROOT,
        SMOKE_CONFIG_FILE=str(config),
        AUTH0_ALPACON_DOMAIN='example.us.auth0.com',
        AUTH0_ALPACON_LOGIN_CLIENT_ID='smoke-client-id',
        ALPACON_MCP_RESOURCE_URL='https://mcp.example.com',
    )
    return env


def _stop(process: subprocess.Popen[str]) -> None:
    # SIGINT, not SIGTERM: server.py turns SIGTERM into KeyboardInterrupt from
    # inside the loop, which uvicorn logs as a crash.
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@contextmanager
def _serve_http(
    argv: list[str], env: dict[str, str], output: dict[str, str] | None = None
) -> Generator[str]:
    """Run an HTTP entry point on a free port; yield its base URL once /health answers."""
    port = _free_port()
    entry = ' '.join(argv)
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, *argv],
        cwd=REPO_ROOT,
        env={**env, 'ALPACON_MCP_PORT': str(port)},
        stdout=subprocess.PIPE if output is not None else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f'http://127.0.0.1:{port}'
    deadline = time.monotonic() + BOOT_TIMEOUT
    try:
        while True:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ''
                raise RuntimeError(f'{entry} exited {process.returncode}: {stderr}')
            try:
                if (
                    httpx.get(f'{url}/health', timeout=1, trust_env=False).status_code
                    == 200
                ):
                    break
            except httpx.TransportError:
                pass  # not listening yet
            if time.monotonic() > deadline:
                raise RuntimeError(f'{entry} did not become ready')
            time.sleep(0.1)
        yield url
    finally:
        _stop(process)
        if output is not None:
            stdout, stderr = process.communicate()
            output.update(stdout=stdout, stderr=stderr)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def _post_initialize_as_public_host(url: str) -> httpx.Response:
    return httpx.post(
        f'{url}/mcp',
        headers={
            'Host': PUBLIC_HOST,
            'Authorization': 'Bearer smoke-jwt',
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
        },
        json=INITIALIZE,
        trust_env=False,
    )


def _initialize_over_stdio(
    argv: list[str], env: dict[str, str], cwd: str
) -> _JsonRpcReply:
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, *argv],
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    watchdog = threading.Timer(
        BOOT_TIMEOUT, process.kill
    )  # unblocks readline on a silent server
    watchdog.start()
    try:
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps(INITIALIZE) + '\n')
        process.stdin.flush()
        line = process.stdout.readline()
        assert line, f'main.py sent no initialize reply within {BOOT_TIMEOUT}s'
        reply: _JsonRpcReply = json.loads(line)
    finally:
        watchdog.cancel()
        if process.stdin:
            process.stdin.close()
        _stop(process)
        if process.stdout:
            process.stdout.close()
    return reply


def test_main_answers_initialize_over_stdio_even_with_log_format_json(entry_env):
    env = {**entry_env, 'LOG_FORMAT': 'json'}
    argv = ['main.py', '--config-file', entry_env['SMOKE_CONFIG_FILE']]
    reply = _initialize_over_stdio(argv, env, REPO_ROOT)

    assert reply['id'] == INITIALIZE['id']
    assert reply['result']['serverInfo']['name'] == 'alpacon'


def test_main_answers_initialize_with_an_env_var_token_only(entry_env, tmp_path):
    """No token file anywhere: the setup wizard must not take over stdout."""
    env = {**entry_env, 'ALPACON_MCP_AP1_SMOKE_TOKEN': 'dummy-token'}
    reply = _initialize_over_stdio(
        [str(Path(REPO_ROOT) / 'main.py')], env, str(tmp_path)
    )

    assert reply['id'] == INITIALIZE['id']
    assert reply['result']['serverInfo']['name'] == 'alpacon'


def test_main_sse_serves_health_on_the_port_it_binds(entry_env):
    env = {**entry_env, 'ALPACON_MCP_HOST': '127.0.0.1'}
    argv = ['main_sse.py', '--config-file', entry_env['SMOKE_CONFIG_FILE']]
    with _serve_http(argv, env) as url:
        response = httpx.get(f'{url}/health', trust_env=False)

    assert response.status_code == 200, response.text
    assert response.json()['transport'] == 'sse'


def test_main_http_serves_health_on_the_port_it_binds(entry_env):
    with _serve_http(['main_http.py'], entry_env) as url:
        response = httpx.get(f'{url}/health', trust_env=False)

    assert response.status_code == 200, response.text
    assert response.json()['transport'] == 'streamable-http'


def test_main_http_writes_json_logs_to_stdout(entry_env):
    env = {**entry_env, 'LOG_FORMAT': 'json'}
    output: dict[str, str] = {}
    launch = """
import runpy

try:
    runpy.run_path('main_http.py', run_name='__main__')
except KeyboardInterrupt:
    pass
"""

    with _serve_http(['-c', launch], env, output) as url:
        response = httpx.get(f'{url}/health', trust_env=False)

    assert response.status_code == 200, response.text
    assert response.json()['transport'] == 'streamable-http'
    lines = [line for line in output['stdout'].splitlines() if line.strip()]
    assert lines
    assert all('level' in json.loads(line) for line in lines)
    assert output['stderr'] == ''


def _run_main_http_without_auth0(
    env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in env.items() if not k.startswith('AUTH0_')}
    return subprocess.run(  # noqa: S603
        [sys.executable, str(Path(REPO_ROOT) / 'main_http.py')],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=BOOT_TIMEOUT,
        check=False,
    )


def test_main_http_reports_missing_auth0_vars_as_one_json_error_record(
    entry_env, tmp_path
):
    env = {**entry_env, 'LOG_FORMAT': 'json'}

    result = _run_main_http_without_auth0(env, tmp_path)

    assert result.returncode == 1
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(records) == 1
    assert records[0]['level'] == 'ERROR'
    assert records[0]['name'] == 'alpacon_mcp.main_http'
    assert (
        'AUTH0_ALPACON_DOMAIN, AUTH0_ALPACON_LOGIN_CLIENT_ID' in records[0]['message']
    )
    assert result.stderr == ''


def test_main_http_reports_missing_auth0_vars_on_stderr_in_text_mode(
    entry_env, tmp_path
):
    result = _run_main_http_without_auth0(entry_env, tmp_path)

    assert result.returncode == 1
    assert result.stdout == ''
    assert ' - ERROR - ' in result.stderr
    assert 'AUTH0_ALPACON_DOMAIN, AUTH0_ALPACON_LOGIN_CLIENT_ID' in result.stderr


@pytest.mark.parametrize('use_legacy', [False, True])
def test_main_http_does_not_reject_a_public_host_header(entry_env, use_legacy):
    """main_http.py binds 0.0.0.0 when ALPACON_MCP_HOST is unset; the token check is stubbed."""
    if use_legacy:
        entry_env['AUTH0_DOMAIN'] = entry_env.pop('AUTH0_ALPACON_DOMAIN')
        entry_env['AUTH0_CLIENT_ID'] = entry_env.pop('AUTH0_ALPACON_LOGIN_CLIENT_ID')
    with _serve_http(['-c', STUBBED_AUTH_LAUNCH], entry_env) as url:
        response = _post_initialize_as_public_host(url)

    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply['id'] == INITIALIZE['id']
    assert reply['result']['serverInfo']['name'] == 'alpacon'


def test_main_http_rejects_a_public_host_header_when_bound_to_loopback(entry_env):
    """The SDK turns DNS rebinding protection on for loopback binds only."""
    env = {**entry_env, 'ALPACON_MCP_HOST': '127.0.0.1'}
    with _serve_http(['-c', STUBBED_AUTH_LAUNCH], env) as url:
        response = _post_initialize_as_public_host(url)

    assert response.status_code == HTTP_MISDIRECTED
    assert 'Invalid Host header' in response.text

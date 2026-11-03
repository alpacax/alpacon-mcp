"""The MFA panel's own behavior, run in Node against a fake MCP Apps host."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / 'tools' / 'mfa_app.html'
HARNESS = ROOT / 'tests' / 'js' / 'mfa_app_harness.mjs'
LINK = 'https://auth.example/authorize?step_up_ticket=t'
NODE = shutil.which('node')


def _run(scenario: str) -> dict[str, object]:
    if NODE is None:
        if os.getenv('CI'):
            pytest.fail('node is missing; GitHub ubuntu runners ship it')
        pytest.skip('node is not installed')
    done = subprocess.run(  # noqa: S603  # fixed argv, no shell
        [NODE, str(HARNESS), str(PANEL), scenario],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    observed: dict[str, object] = json.loads(done.stdout)
    return observed


def test_a_host_that_cannot_open_links_gets_the_link_to_copy():
    observed = _run('no_open_links')

    assert observed['tone'] == 'warning'
    assert observed['link'] == LINK
    assert observed['buttonDisabled'] is True


def test_a_declined_open_link_starts_no_poll_and_offers_the_link():
    observed = _run('open_link_declined')

    assert observed['tone'] == 'danger'
    assert observed['link'] == LINK
    assert observed['buttonDisabled'] is False
    assert observed['toolCalls'] == 0


def test_a_completed_poll_reports_success():
    observed = _run('poll_completes')

    assert observed['tone'] == 'success'
    assert observed['toolCalls'] == 1


@pytest.mark.parametrize(
    ('scenario', 'why'),
    [('poll_error_envelope', 'nope'), ('poll_is_error_text', 'boom')],
)
def test_an_error_poll_result_stops_polling_at_once(scenario, why):
    observed = _run(scenario)

    assert observed['tone'] == 'danger'
    assert why in str(observed['status'])
    assert observed['toolCalls'] == 1


def test_a_host_that_never_answers_the_poll_stops_after_three_timeouts():
    observed = _run('poll_hangs')

    assert observed['tone'] == 'danger'
    assert 'timed out' in str(observed['status'])
    assert observed['toolCalls'] == 3


def test_host_requests_get_an_answer():
    observed = _run('host_requests')

    assert observed['responses'] == [
        {'jsonrpc': '2.0', 'id': 'p1', 'result': {}},
        {
            'jsonrpc': '2.0',
            'id': 'p2',
            'error': {'code': -32601, 'message': 'Method not found'},
        },
    ]


def test_a_link_that_is_not_https_is_never_offered():
    observed = _run('http_link')

    assert observed['buttonDisabled'] is True
    assert observed['link'] is None


def test_the_documented_poll_cadence_matches_the_panel():
    html = PANEL.read_text(encoding='utf-8')
    doc = (ROOT / 'docs' / 'mfa-reauth-flow.md').read_text(encoding='utf-8')

    assert re.search(r'const POLL_MS = 3000;', html)
    assert re.search(r'const POLL_LIMIT_MS = 5 \* 60 \* 1000;', html)
    assert 'every 3 seconds for up to 5 minutes' in doc

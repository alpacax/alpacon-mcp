"""Sanity tests for the shared response-envelope types."""

from utils.api_types import is_api_error
from utils.common import error_response, success_response


def test_is_api_error_narrows_error_envelope():
    assert is_api_error({'error': 'HTTP Error', 'message': 'boom'})
    assert not is_api_error({'status': 'success'})
    assert not is_api_error(['a', 'b'])


def test_response_envelopes_unchanged_at_runtime():
    ok = success_response(data={'x': 1}, region='ap1', workspace='w')
    assert ok == {
        'status': 'success',
        'data': {'x': 1},
        'region': 'ap1',
        'workspace': 'w',
    }
    err = error_response('nope', workspace='w')
    assert err == {'status': 'error', 'message': 'nope', 'workspace': 'w'}

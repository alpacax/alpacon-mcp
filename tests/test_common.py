"""Unit tests for utils.common helpers."""

from utils.common import filter_non_none


def test_filter_non_none_omits_none_values():
    assert filter_non_none(a=1, b=None, c='x') == {'a': 1, 'c': 'x'}


def test_filter_non_none_keeps_falsy_non_none():
    # False, 0, '', [] are non-None and must be kept
    assert filter_non_none(a=False, b=0, c='', d=[]) == {
        'a': False,
        'b': 0,
        'c': '',
        'd': [],
    }


def test_filter_non_none_empty():
    assert filter_non_none() == {}


def test_filter_non_none_all_none():
    assert filter_non_none(a=None, b=None) == {}


def test_filter_non_none_preserves_order():
    result = filter_non_none(a=1, b=None, c=2, d=None, e=3)
    assert list(result.keys()) == ['a', 'c', 'e']

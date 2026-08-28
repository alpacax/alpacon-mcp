"""Basic tests for alpacon-mcp package.

The imports below stay local to each test: the import succeeding is the
assertion under test, so hoisting them would turn an import failure into a
collection-time crash for the whole file instead of one failing test.
"""

import pytest


def test_import_server():
    """Test that main modules can be imported."""
    try:
        import server

        assert hasattr(server, 'mcp')
    except ImportError as e:
        pytest.fail(f'Failed to import server module: {e}')


def test_import_main():
    """Test that main module can be imported."""
    try:
        import main

        assert hasattr(main, 'main')
    except ImportError as e:
        pytest.fail(f'Failed to import main module: {e}')


def test_import_utils():
    """Test that utils modules can be imported."""
    try:
        from utils import http_client, token_manager

        assert http_client is not None
        assert token_manager is not None
    except ImportError as e:
        pytest.fail(f'Failed to import utils modules: {e}')


def test_basic_functionality():
    """Test basic package functionality."""
    # This is a placeholder test - replace with actual functionality tests
    assert 1 + 1 == 2


if __name__ == '__main__':
    pytest.main([__file__])

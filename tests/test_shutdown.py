"""
Unit tests for graceful shutdown functionality.

Tests http_client.close() idempotency and the app_lifespan teardown sequence.
"""

import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHTTPClientClose:
    """Test HTTP client close() method."""

    @pytest.mark.asyncio
    async def test_close_with_active_client(self):
        """Test close() properly shuts down active client and clears caches."""
        from utils.http_client import AlpaconHTTPClient

        client = AlpaconHTTPClient()

        # Simulate an active httpx client
        mock_httpx = AsyncMock()
        mock_httpx.is_closed = False
        mock_httpx.aclose = AsyncMock()
        client._client = mock_httpx

        # Add some cache entries
        client._cache['key1'] = {'data': 'cached'}
        client._cache_ttl['key1'] = 99999999

        await client.close()

        mock_httpx.aclose.assert_awaited_once()
        assert len(client._cache) == 0
        assert len(client._cache_ttl) == 0

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Test that close() can be called multiple times safely."""
        from utils.http_client import AlpaconHTTPClient

        client = AlpaconHTTPClient()

        # First close with no client initialized
        await client.close()

        # Simulate a closed client
        mock_httpx = AsyncMock()
        mock_httpx.is_closed = True
        client._client = mock_httpx

        # Second close - should not call aclose on already-closed client
        await client.close()
        mock_httpx.aclose.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_client_backward_compat(self):
        """Test that _close_client() still works as alias for close()."""
        from utils.http_client import AlpaconHTTPClient

        client = AlpaconHTTPClient()

        mock_httpx = AsyncMock()
        mock_httpx.is_closed = False
        mock_httpx.aclose = AsyncMock()
        client._client = mock_httpx

        await client._close_client()

        mock_httpx.aclose.assert_awaited_once()


class TestAppLifespan:
    """Test the app_lifespan context manager in server.py."""

    @pytest.mark.asyncio
    async def test_lifespan_teardown_calls_cleanup(self):
        """Test that lifespan teardown calls cleanup functions."""
        from server import app_lifespan

        mock_app = MagicMock()

        with patch('utils.http_client.http_client') as mock_http:
            mock_http.close = AsyncMock()

            async with app_lifespan(mock_app):
                pass  # Simulate normal server operation

            # Verify HTTP client cleanup was called during teardown
            mock_http.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_teardown_on_exception(self):
        """Test that lifespan teardown runs even after an exception."""
        from server import app_lifespan

        mock_app = MagicMock()

        with patch('utils.http_client.http_client') as mock_http:
            mock_http.close = AsyncMock()

            with pytest.raises(RuntimeError, match='test error'):
                async with app_lifespan(mock_app):
                    raise RuntimeError('test error')

            # Cleanup should still run
            mock_http.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sigterm_handler_installed_on_unix(self):
        """Test that SIGTERM handler is installed on non-Windows platforms."""
        import sys

        from server import _sigterm_handler, app_lifespan

        mock_app = MagicMock()

        if sys.platform == 'win32':
            pytest.skip('SIGTERM handler test only runs on Unix')

        with patch('utils.http_client.http_client') as mock_http:
            mock_http.close = AsyncMock()

            async with app_lifespan(mock_app):
                # Verify our handler is installed for SIGTERM
                current_handler = signal.getsignal(signal.SIGTERM)
                assert current_handler is _sigterm_handler

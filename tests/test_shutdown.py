"""
Unit tests for graceful shutdown functionality.

Tests the cleanup_all_connections helper, http_client.close() idempotency,
and the app_lifespan teardown sequence.
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_pools():
    """Reset global pools before each test to prevent cross-test contamination."""
    from tools.websh_tools import session_pool, websocket_pool

    websocket_pool.clear()
    session_pool.clear()
    yield
    websocket_pool.clear()
    session_pool.clear()


class TestCleanupAllConnections:
    """Test WebSocket connection cleanup during shutdown."""

    @pytest.mark.asyncio
    async def test_cleanup_empty_pools(self):
        """Test cleanup with no active connections."""
        from tools.websh_tools import (
            cleanup_all_connections,
            session_pool,
            websocket_pool,
        )

        # Ensure pools are empty
        websocket_pool.clear()
        session_pool.clear()

        # Should complete without error
        await cleanup_all_connections()

        assert len(websocket_pool) == 0
        assert len(session_pool) == 0

    @pytest.mark.asyncio
    async def test_cleanup_closes_websockets(self):
        """Test that cleanup closes all WebSocket connections."""
        from tools.websh_tools import (
            cleanup_all_connections,
            session_pool,
            websocket_pool,
        )

        # Set up mock websockets in the pool
        mock_ws1 = AsyncMock()
        mock_ws1.close = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws2.close = AsyncMock()

        websocket_pool['channel-1'] = {
            'websocket': mock_ws1,
            'url': 'ws://test/1',
            'session_id': 'session-1',
        }
        websocket_pool['channel-2'] = {
            'websocket': mock_ws2,
            'url': 'ws://test/2',
            'session_id': 'session-2',
        }
        session_pool['ap1:workspace:server1'] = {'id': 'session-1'}

        await cleanup_all_connections()

        # Both websockets should have been closed
        mock_ws1.close.assert_awaited_once()
        mock_ws2.close.assert_awaited_once()

        # Pools should be cleared
        assert len(websocket_pool) == 0
        assert len(session_pool) == 0

    @pytest.mark.asyncio
    async def test_cleanup_handles_close_errors(self):
        """Test that cleanup continues even if individual close() calls fail."""
        from tools.websh_tools import (
            cleanup_all_connections,
            session_pool,
            websocket_pool,
        )

        # Set up one failing and one succeeding websocket
        mock_ws_fail = AsyncMock()
        mock_ws_fail.close = AsyncMock(
            side_effect=Exception('Connection already closed')
        )
        mock_ws_ok = AsyncMock()
        mock_ws_ok.close = AsyncMock()

        websocket_pool['channel-fail'] = {
            'websocket': mock_ws_fail,
            'url': 'ws://test/fail',
            'session_id': 'session-fail',
        }
        websocket_pool['channel-ok'] = {
            'websocket': mock_ws_ok,
            'url': 'ws://test/ok',
            'session_id': 'session-ok',
        }

        # Should not raise even though one close() fails
        await cleanup_all_connections()

        # Both should have been attempted
        mock_ws_fail.close.assert_awaited_once()
        mock_ws_ok.close.assert_awaited_once()

        # Pools should still be cleared
        assert len(websocket_pool) == 0
        assert len(session_pool) == 0

    @pytest.mark.asyncio
    async def test_cleanup_respects_timeout(self):
        """Test that cleanup does not hang if websocket.close() is slow."""
        from tools.websh_tools import (
            cleanup_all_connections,
            websocket_pool,
        )

        # Create a websocket that hangs on close
        async def slow_close():
            await asyncio.sleep(60)

        mock_ws = AsyncMock()
        mock_ws.close = slow_close

        websocket_pool['channel-slow'] = {
            'websocket': mock_ws,
            'url': 'ws://test/slow',
            'session_id': 'session-slow',
        }

        # Should complete within the 5-second timeout, not hang for 60 seconds
        await asyncio.wait_for(cleanup_all_connections(), timeout=10)

        assert len(websocket_pool) == 0


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

        with (
            patch(
                'tools.websh_tools.cleanup_all_connections', new_callable=AsyncMock
            ) as mock_ws_cleanup,
            patch('utils.http_client.http_client') as mock_http,
        ):
            mock_http.close = AsyncMock()

            async with app_lifespan(mock_app):
                pass  # Simulate normal server operation

            # Verify both cleanup functions were called during teardown
            mock_ws_cleanup.assert_awaited_once()
            mock_http.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_teardown_on_exception(self):
        """Test that lifespan teardown runs even after an exception."""
        from server import app_lifespan

        mock_app = MagicMock()

        with (
            patch(
                'tools.websh_tools.cleanup_all_connections', new_callable=AsyncMock
            ) as mock_ws_cleanup,
            patch('utils.http_client.http_client') as mock_http,
        ):
            mock_http.close = AsyncMock()

            with pytest.raises(RuntimeError, match='test error'):
                async with app_lifespan(mock_app):
                    raise RuntimeError('test error')

            # Cleanup should still run
            mock_ws_cleanup.assert_awaited_once()
            mock_http.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sigterm_handler_installed_on_unix(self):
        """Test that SIGTERM handler is installed on non-Windows platforms."""
        import sys

        from server import _sigterm_handler, app_lifespan

        mock_app = MagicMock()

        if sys.platform == 'win32':
            pytest.skip('SIGTERM handler test only runs on Unix')

        with (
            patch('tools.websh_tools.cleanup_all_connections', new_callable=AsyncMock),
            patch('utils.http_client.http_client') as mock_http,
        ):
            mock_http.close = AsyncMock()

            async with app_lifespan(mock_app):
                # Verify our handler is installed for SIGTERM
                current_handler = signal.getsignal(signal.SIGTERM)
                assert current_handler is _sigterm_handler

    @pytest.mark.asyncio
    async def test_teardown_continues_after_ws_cleanup_error(self):
        """Test that HTTP client cleanup runs even if WebSocket cleanup fails."""
        from server import app_lifespan

        mock_app = MagicMock()

        with (
            patch(
                'tools.websh_tools.cleanup_all_connections',
                new_callable=AsyncMock,
                side_effect=RuntimeError('ws cleanup failed'),
            ),
            patch('utils.http_client.http_client') as mock_http,
        ):
            mock_http.close = AsyncMock()

            async with app_lifespan(mock_app):
                pass

            # HTTP client close should still be called despite WS cleanup failure
            mock_http.close.assert_awaited_once()

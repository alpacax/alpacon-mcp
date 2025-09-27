"""HTTP client for Alpacon API interactions."""

import asyncio
import json
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
import httpx
import time
from utils.logger import get_logger

logger = get_logger("http_client")


class AlpaconHTTPClient:
    """Async HTTP client for Alpacon API with connection pooling and caching."""

    def __init__(self):
        """Initialize HTTP client."""
        self.base_timeout = httpx.Timeout(10.0, connect=5.0)
        self.max_retries = 3
        self.retry_delay = 1.0
        self.max_retry_delay = 30.0

        # Connection pooling
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

        # Simple TTL cache
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl: Dict[str, float] = {}
        self.default_cache_ttl = 300  # 5 minutes

        logger.info(f"AlpaconHTTPClient initialized - timeout: {self.base_timeout.read}s, max_retries: {self.max_retries}, caching enabled")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create shared async client for connection pooling."""
        # For testing compatibility, check if client pooling is disabled
        if hasattr(self, '_disable_pooling') and self._disable_pooling:
            return httpx.AsyncClient(timeout=self.base_timeout)

        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=self.base_timeout,
                    limits=httpx.Limits(
                        max_keepalive_connections=20,
                        max_connections=100,
                        keepalive_expiry=30.0
                    )
                )
                logger.debug("Created new HTTP client with connection pooling")
            return self._client

    async def _close_client(self):
        """Close the shared client."""
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
                logger.debug("Closed HTTP client")

    def _get_cache_key(self, method: str, url: str, params: Optional[Dict] = None) -> str:
        """Generate cache key for request."""
        key_parts = [method, url]
        if params:
            sorted_params = sorted(params.items())
            key_parts.append(str(sorted_params))
        return "|".join(key_parts)

    def _is_cacheable(self, method: str, endpoint: str) -> bool:
        """Check if request should be cached."""
        if method != "GET":
            return False

        # Cache server lists, system info, but not real-time metrics
        cacheable_endpoints = [
            "/api/servers/servers/",
            "/api/system/info/",
            "/api/system/users/",
            "/api/system/packages/",
            "/api/iam/users/",
            "/api/iam/groups/",
            "/api/iam/roles/"
        ]

        return any(endpoint.startswith(cacheable) for cacheable in cacheable_endpoints)

    def _get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached response if still valid."""
        if cache_key not in self._cache:
            return None

        if time.time() > self._cache_ttl.get(cache_key, 0):
            # Cache expired
            self._cache.pop(cache_key, None)
            self._cache_ttl.pop(cache_key, None)
            return None

        logger.debug(f"Cache hit for key: {cache_key}")
        return self._cache[cache_key]

    def _set_cached_response(self, cache_key: str, response: Dict[str, Any], ttl: Optional[float] = None):
        """Cache response with TTL."""
        self._cache[cache_key] = response
        self._cache_ttl[cache_key] = time.time() + (ttl or self.default_cache_ttl)
        logger.debug(f"Cached response for key: {cache_key}")

    def get_base_url(self, region: str, workspace: str) -> str:
        """Get base URL for API calls.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name

        Returns:
            Base URL for API calls
        """
        base_url = f"https://{workspace}.{region}.alpacon.io"
        logger.debug(f"Generated base URL: {base_url}")
        return base_url

    async def request(
        self,
        method: str,
        url: str,
        token: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Execute HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Full URL for the request
            token: API token for authentication
            headers: Additional headers
            json_data: JSON data for request body
            params: Query parameters
            timeout: Request timeout in seconds

        Returns:
            Response data as dictionary

        Raises:
            httpx.HTTPError: If request fails after retries
        """
        # Prepare headers
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "alpacon-mcp/1.0"
        }

        if token:
            request_headers["Authorization"] = f"token={token}"

        if headers:
            request_headers.update(headers)

        # Set timeout
        request_timeout = httpx.Timeout(timeout or 10.0, connect=5.0)

        # Retry logic
        retry_count = 0
        retry_delay = self.retry_delay

        # Log request details (without sensitive data)
        logger.info(f"HTTP {method} request to {url}")
        logger.debug(f"Request headers: {dict((k, v if k != 'Authorization' else '[REDACTED]') for k, v in request_headers.items())}")
        if params:
            logger.debug(f"Request params: {params}")
        if json_data:
            logger.debug(f"Request body: {json_data}")

        # Check cache for GET requests
        cache_key = self._get_cache_key(method, url, params)
        if self._is_cacheable(method, url):
            cached_response = self._get_cached_response(cache_key)
            if cached_response:
                logger.info(f"Returning cached response for {method} {url}")
                return cached_response

        while retry_count < self.max_retries:
            try:
                client = await self._get_client()
                response = await client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=json_data,
                    params=params,
                    timeout=request_timeout
                )

                # Check for success
                response.raise_for_status()

                # Log successful response
                logger.info(f"HTTP {method} success - Status: {response.status_code}, Content-Length: {len(response.content)}")
                logger.debug(f"Response headers: {dict(response.headers)}")

                # Return JSON response
                if response.text:
                    result = response.json()
                    logger.debug(f"Response body: {result}")

                    # Cache successful GET responses
                    if self._is_cacheable(method, url):
                        self._set_cached_response(cache_key, result)

                    return result
                else:
                    result = {"status": "success", "status_code": response.status_code}
                    logger.debug(f"Empty response, returning: {result}")

                    # Cache successful empty responses too
                    if self._is_cacheable(method, url):
                        self._set_cached_response(cache_key, result)

                    return result

            except httpx.HTTPStatusError as e:
                # Handle HTTP errors (4xx, 5xx)
                logger.error(f"HTTP {method} error - Status: {e.response.status_code}, URL: {url}")
                logger.error(f"Response body: {e.response.text}")

                if e.response.status_code >= 500:
                    # Server error - retry
                    retry_count += 1
                    logger.warning(f"Server error, retrying ({retry_count}/{self.max_retries}) in {retry_delay}s")
                    if retry_count < self.max_retries:
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, self.max_retry_delay)
                        continue
                else:
                    # Client error - don't retry
                    error_response = {
                        "error": "HTTP Error",
                        "status_code": e.response.status_code,
                        "message": str(e),
                        "response": e.response.text
                    }
                    logger.error(f"Client error, not retrying: {error_response}")
                    return error_response

            except httpx.TimeoutException as e:
                # Timeout - retry
                retry_count += 1
                logger.warning(f"Request timeout, retrying ({retry_count}/{self.max_retries}) in {retry_delay}s")
                if retry_count < self.max_retries:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                    continue
                else:
                    error_response = {
                        "error": "Timeout",
                        "message": f"Request timed out after {self.max_retries} retries"
                    }
                    logger.error(f"Request timeout after all retries: {error_response}")
                    return error_response

            except httpx.RequestError as e:
                # Network error - retry
                retry_count += 1
                logger.warning(f"Network error: {e}, retrying ({retry_count}/{self.max_retries}) in {retry_delay}s")
                if retry_count < self.max_retries:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                    continue
                else:
                    error_response = {
                        "error": "Request Error",
                        "message": str(e)
                    }
                    logger.error(f"Network error after all retries: {error_response}")
                    return error_response

            except Exception as e:
                # Unexpected error - don't retry
                error_response = {
                    "error": "Unexpected Error",
                    "message": str(e)
                }
                logger.error(f"Unexpected error: {error_response}", exc_info=True)
                return error_response

        # Should not reach here, but just in case
        error_response = {
            "error": "Max retries exceeded",
            "message": f"Failed after {self.max_retries} attempts"
        }
        logger.error(f"Unexpected fallback - max retries exceeded: {error_response}")
        return error_response

    async def batch_request(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute multiple requests in parallel.

        Args:
            requests: List of request dictionaries with keys:
                - method: HTTP method
                - region: Region
                - workspace: Workspace
                - endpoint: API endpoint
                - token: API token
                - params: Optional query parameters
                - data: Optional request body data

        Returns:
            List of response dictionaries in the same order as requests
        """
        if not requests:
            return []

        logger.info(f"Executing {len(requests)} requests in parallel")

        # Create tasks for parallel execution
        tasks = []
        for req in requests:
            if req["method"].upper() == "GET":
                task = self.get(
                    region=req["region"],
                    workspace=req["workspace"],
                    endpoint=req["endpoint"],
                    token=req["token"],
                    params=req.get("params")
                )
            elif req["method"].upper() == "POST":
                task = self.post(
                    region=req["region"],
                    workspace=req["workspace"],
                    endpoint=req["endpoint"],
                    token=req["token"],
                    data=req.get("data")
                )
            else:
                # For other methods, use the generic request method
                base_url = self.get_base_url(req["region"], req["workspace"])
                full_url = urljoin(base_url, req["endpoint"])
                task = self.request(
                    method=req["method"],
                    url=full_url,
                    token=req["token"],
                    json_data=req.get("data"),
                    params=req.get("params")
                )
            tasks.append(task)

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error dictionaries
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "error": "Request Exception",
                    "message": str(result),
                    "request_index": i
                })
            else:
                processed_results.append(result)

        logger.info(f"Completed {len(requests)} parallel requests")
        return processed_results

    async def get(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str,
        params: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Execute GET request.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            params: Query parameters

        Returns:
            Response data
        """
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method="GET",
            url=full_url,
            token=token,
            params=params
        )

    async def post(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute POST request.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            data: Request body data

        Returns:
            Response data
        """
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method="POST",
            url=full_url,
            token=token,
            json_data=data
        )

    async def put(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute PUT request.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            data: Request body data

        Returns:
            Response data
        """
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method="PUT",
            url=full_url,
            token=token,
            json_data=data
        )

    async def patch(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute PATCH request.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            data: Request body data

        Returns:
            Response data
        """
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method="PATCH",
            url=full_url,
            token=token,
            json_data=data
        )

    async def delete(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str
    ) -> Dict[str, Any]:
        """Execute DELETE request.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token

        Returns:
            Response data
        """
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method="DELETE",
            url=full_url,
            token=token
        )

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close client."""
        await self._close_client()

    def __del__(self):
        """Cleanup on deletion."""
        if hasattr(self, '_client') and self._client and not self._client.is_closed:
            # Note: This is not ideal as __del__ cannot be async
            # Better to use async context manager or explicit cleanup
            import warnings
            warnings.warn(
                "AlpaconHTTPClient not properly closed. Use async context manager or call _close_client()",
                ResourceWarning
            )


# Singleton instance
http_client = AlpaconHTTPClient()
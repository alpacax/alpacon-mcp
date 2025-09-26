"""HTTP client for Alpacon API interactions."""

import asyncio
import json
from typing import Dict, Any, Optional, Union
from urllib.parse import urljoin
import httpx
import time
from utils.logger import get_logger

logger = get_logger("http_client")


class AlpaconHTTPClient:
    """Async HTTP client for Alpacon API."""

    def __init__(self):
        """Initialize HTTP client."""
        self.base_timeout = httpx.Timeout(10.0, connect=5.0)
        self.max_retries = 3
        self.retry_delay = 1.0
        self.max_retry_delay = 30.0
        logger.info(f"AlpaconHTTPClient initialized - timeout: {self.base_timeout.read}s, max_retries: {self.max_retries}")

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

        while retry_count < self.max_retries:
            try:
                async with httpx.AsyncClient(timeout=request_timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=request_headers,
                        json=json_data,
                        params=params
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
                        return result
                    else:
                        result = {"status": "success", "status_code": response.status_code}
                        logger.debug(f"Empty response, returning: {result}")
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


# Singleton instance
http_client = AlpaconHTTPClient()
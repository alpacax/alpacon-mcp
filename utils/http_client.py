"""HTTP client for Alpacon API interactions."""

import asyncio
import json
from typing import Dict, Any, Optional, Union
from urllib.parse import urljoin
import httpx
import time


class AlpaconHTTPClient:
    """Async HTTP client for Alpacon API."""

    def __init__(self):
        """Initialize HTTP client."""
        self.base_timeout = httpx.Timeout(10.0, connect=5.0)
        self.max_retries = 3
        self.retry_delay = 1.0
        self.max_retry_delay = 30.0

    def get_base_url(self, region: str, workspace: str) -> str:
        """Get base URL for API calls.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name

        Returns:
            Base URL for API calls
        """
        return f"https://{workspace}.{region}.alpacon.io"

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

                    # Return JSON response
                    if response.text:
                        return response.json()
                    else:
                        return {"status": "success", "status_code": response.status_code}

            except httpx.HTTPStatusError as e:
                # Handle HTTP errors (4xx, 5xx)
                if e.response.status_code >= 500:
                    # Server error - retry
                    retry_count += 1
                    if retry_count < self.max_retries:
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, self.max_retry_delay)
                        continue
                else:
                    # Client error - don't retry
                    return {
                        "error": "HTTP Error",
                        "status_code": e.response.status_code,
                        "message": str(e),
                        "response": e.response.text
                    }

            except httpx.TimeoutException as e:
                # Timeout - retry
                retry_count += 1
                if retry_count < self.max_retries:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                    continue
                else:
                    return {
                        "error": "Timeout",
                        "message": f"Request timed out after {self.max_retries} retries"
                    }

            except httpx.RequestError as e:
                # Network error - retry
                retry_count += 1
                if retry_count < self.max_retries:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                    continue
                else:
                    return {
                        "error": "Request Error",
                        "message": str(e)
                    }

            except Exception as e:
                # Unexpected error - don't retry
                return {
                    "error": "Unexpected Error",
                    "message": str(e)
                }

        # Should not reach here, but just in case
        return {
            "error": "Max retries exceeded",
            "message": f"Failed after {self.max_retries} attempts"
        }

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
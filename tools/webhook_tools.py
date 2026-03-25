"""Webhook and event subscription tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client

# ===============================
# EVENT SUBSCRIPTION TOOLS
# ===============================


@mcp_tool_handler(
    description='List event subscriptions that define which events trigger notifications or webhook calls.'
)
async def list_event_subscriptions(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List event subscriptions.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Event subscriptions list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/events/subscriptions/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create an event subscription to receive notifications when specific event types occur. Event types: command_fin, servers_commit, sudo.'
)
async def create_event_subscription(
    workspace: str,
    channel: str,
    event_type: str,
    target_id: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create an event subscription.

    Args:
        workspace: Workspace name. Required parameter
        channel: Notification channel ID to deliver events to
        event_type: Type of event to subscribe to (command_fin, servers_commit, sudo)
        target_id: Target resource ID to filter events for (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Event subscription creation response
    """
    token = kwargs.get('token')

    subscription_data: dict[str, Any] = {
        'channel': channel,
        'event_type': event_type,
    }

    if target_id is not None:
        subscription_data['target_id'] = target_id

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/events/subscriptions/',
        token=token,
        data=subscription_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Delete an event subscription to stop receiving notifications for that event type.'
)
async def delete_event_subscription(
    subscription_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete an event subscription.

    Args:
        subscription_id: Event subscription ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Event subscription deletion response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/events/subscriptions/{subscription_id}/',
        token=token,
    )

    return success_response(
        data=result,
        subscription_id=subscription_id,
        region=region,
        workspace=workspace,
    )


# ===============================
# WEBHOOK TOOLS
# ===============================


@mcp_tool_handler(
    description='List configured webhooks that receive event notifications via HTTP callbacks.'
)
async def list_webhooks(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List webhooks.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Webhooks list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/notifications/webhooks/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a webhook endpoint to receive HTTP callbacks when subscribed events occur.'
)
async def create_webhook(
    workspace: str,
    name: str,
    url: str,
    ssl_verify: bool = True,
    enabled: bool = True,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a webhook.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the webhook
        url: URL to receive webhook callbacks
        ssl_verify: Whether to verify SSL certificates (default: True)
        enabled: Whether the webhook is enabled (default: True)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Webhook creation response
    """
    token = kwargs.get('token')

    webhook_data: dict[str, Any] = {
        'name': name,
        'url': url,
        'ssl_verify': ssl_verify,
        'enabled': enabled,
    }

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/notifications/webhooks/',
        token=token,
        data=webhook_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing webhook configuration such as URL, name, or enabled status.'
)
async def update_webhook(
    webhook_id: str,
    workspace: str,
    name: str | None = None,
    url: str | None = None,
    ssl_verify: bool | None = None,
    enabled: bool | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing webhook.

    Args:
        webhook_id: Webhook ID to update
        workspace: Workspace name. Required parameter
        name: Name of the webhook (optional)
        url: URL to receive webhook callbacks (optional)
        ssl_verify: Whether to verify SSL certificates (optional)
        enabled: Whether the webhook is enabled (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Webhook update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if name is not None:
        update_data['name'] = name
    if url is not None:
        update_data['url'] = url
    if ssl_verify is not None:
        update_data['ssl_verify'] = ssl_verify
    if enabled is not None:
        update_data['enabled'] = enabled

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/notifications/webhooks/{webhook_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, webhook_id=webhook_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Delete a webhook endpoint and stop receiving HTTP callbacks.'
)
async def delete_webhook(
    webhook_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a webhook.

    Args:
        webhook_id: Webhook ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Webhook deletion response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/notifications/webhooks/{webhook_id}/',
        token=token,
    )

    return success_response(
        data=result, webhook_id=webhook_id, region=region, workspace=workspace
    )

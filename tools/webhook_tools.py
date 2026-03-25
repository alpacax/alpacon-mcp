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
    description='Create an event subscription to receive notifications when specific event types occur.'
)
async def create_event_subscription(
    workspace: str,
    event_type: str,
    webhook_id: str | None = None,
    servers: list[str] | None = None,
    enabled: bool = True,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create an event subscription.

    Args:
        workspace: Workspace name. Required parameter
        event_type: Type of event to subscribe to
        webhook_id: Webhook ID to deliver events to (optional)
        servers: List of server IDs to filter events from (optional)
        enabled: Whether the subscription is enabled (default: True)
        description: Description of the subscription (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Event subscription creation response
    """
    token = kwargs.get('token')

    subscription_data: dict[str, Any] = {
        'event_type': event_type,
        'enabled': enabled,
    }

    if webhook_id is not None:
        subscription_data['webhook'] = webhook_id
    if servers is not None:
        subscription_data['servers'] = servers
    if description is not None:
        subscription_data['description'] = description

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
        endpoint='/api/webhooks/',
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
    secret: str | None = None,
    enabled: bool = True,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a webhook.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the webhook
        url: URL to receive webhook callbacks
        secret: Secret for webhook signature verification (optional)
        enabled: Whether the webhook is enabled (default: True)
        description: Description of the webhook (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Webhook creation response
    """
    token = kwargs.get('token')

    webhook_data: dict[str, Any] = {
        'name': name,
        'url': url,
        'enabled': enabled,
    }

    if secret is not None:
        webhook_data['secret'] = secret
    if description is not None:
        webhook_data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/webhooks/',
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
    secret: str | None = None,
    enabled: bool | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing webhook.

    Args:
        webhook_id: Webhook ID to update
        workspace: Workspace name. Required parameter
        name: Name of the webhook (optional)
        url: URL to receive webhook callbacks (optional)
        secret: Secret for webhook signature verification (optional)
        enabled: Whether the webhook is enabled (optional)
        description: Description of the webhook (optional)
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
    if secret is not None:
        update_data['secret'] = secret
    if enabled is not None:
        update_data['enabled'] = enabled
    if description is not None:
        update_data['description'] = description

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/webhooks/{webhook_id}/',
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
        endpoint=f'/api/webhooks/{webhook_id}/',
        token=token,
    )

    return success_response(
        data=result, webhook_id=webhook_id, region=region, workspace=workspace
    )

"""Webhook and event subscription tools for Alpacon MCP server."""

from typing import Annotated

from pydantic import Field

from utils.api_call import http_call_response
from utils.common import build_list_params, exclude_none
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error, validate_uuid_format
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY
from utils.types import ToolResponse

# Mirrors Webhook.Provider; omitting provider lets the server infer it from the URL.
WEBHOOK_PROVIDERS = ('slack', 'discord', 'teams', 'telegram', 'custom')

_PROVIDERS_LIST = ', '.join(WEBHOOK_PROVIDERS)
_PROVIDERS_SENTENCE = (
    f'provider must be one of: {_PROVIDERS_LIST}, '
    'or omitted to let the server detect it from the URL.'
)
_PROVIDERS_FILTER_SENTENCE = f'provider must be one of: {_PROVIDERS_LIST}.'
_OWNER_SENTENCE = "owner must be a user's UUID; a username is rejected."

_OWNER_DESCRIPTION = "A user's UUID; a username is rejected."
_PROVIDER_FILTER_DESCRIPTION = f'Filter by provider: {_PROVIDERS_LIST}.'
_PROVIDER_DESCRIPTION = (
    f'One of {_PROVIDERS_LIST}, or omitted to let the server detect it from the URL.'
)
_EVENT_TYPE_DESCRIPTION = (
    'One of command_fin, servers_commit, sudo, metric_threshold_crossed, '
    'metric_threshold_resolved.'
)

# ===============================
# EVENT SUBSCRIPTION TOOLS
# ===============================


@mcp_tool_handler(
    description='List event subscriptions in a workspace. Returns subscription ID, channel, event type, and target ID. Subscriptions define which events (command_fin, servers_commit, sudo, metric_threshold_crossed, metric_threshold_resolved) trigger notifications to a channel. Related: create_event_subscription, list_webhooks (webhook endpoints).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'event subscription notification channel'},
)
async def list_event_subscriptions(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: str,
) -> ToolResponse:
    """List event subscriptions.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Event subscriptions list response
    """
    token = kwargs.get('token')

    params = build_list_params(page=page, page_size=page_size)

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/events/subscriptions/',
        token=token,
        default_message='Failed to list event subscriptions',
        params=params,
    )


@mcp_tool_handler(
    description='Create an event subscription to receive notifications when specific events occur. Requires a notification channel ID and event type. Optionally filter by target resource ID. Users can only manage their own subscriptions. Related: list_webhooks (find channel IDs), delete_event_subscription.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'event subscription create notification'},
)
async def create_event_subscription(
    workspace: str,
    channel: str,
    event_type: Annotated[str, Field(description=_EVENT_TYPE_DESCRIPTION)],
    target_id: str | None = None,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """metric_threshold_crossed and metric_threshold_resolved need the metrics
    extension and take a server `target_id`; omitting it needs an admin."""
    token = kwargs.get('token')

    subscription_data: dict[str, object] = {
        'channel': channel,
        'event_type': event_type,
        **exclude_none(target_id=target_id),
    }

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint='/api/events/subscriptions/',
        token=token,
        default_message='Failed to create event subscription',
        data=subscription_data,
    )


@mcp_tool_handler(
    description='Delete an event subscription by its ID to stop receiving notifications for that event type. Users can only delete their own subscriptions.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'event subscription delete remove'},
)
async def delete_event_subscription(
    subscription_id: str, workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    token = kwargs.get('token')

    return await http_call_response(
        http_client.delete,
        region=region,
        workspace=workspace,
        endpoint=f'/api/events/subscriptions/{subscription_id}/',
        token=token,
        default_message='Failed to delete event subscription',
        subscription_id=subscription_id,
    )


# ===============================
# WEBHOOK TOOLS
# ===============================


@mcp_tool_handler(
    description=(
        'List configured webhooks in a workspace, optionally filtered by '
        'provider. Returns webhook ID, name, URL, '
        'provider, SSL verification setting, and enabled status. Needs an '
        'admin account. Related: create_webhook, list_event_subscriptions.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'webhooks list endpoints callbacks'},
)
async def list_webhooks(
    workspace: str,
    provider: Annotated[
        str | None, Field(description=_PROVIDER_FILTER_DESCRIPTION)
    ] = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: str,
) -> ToolResponse:
    """List webhooks.

    Args:
        workspace: Workspace name. Required parameter
        provider: Filter by provider; one of slack, discord, teams, telegram,
            custom (optional)
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Webhooks list response
    """
    if provider is not None and provider not in WEBHOOK_PROVIDERS:
        return format_validation_error('provider', provider, _PROVIDERS_FILTER_SENTENCE)

    token = kwargs.get('token')

    params = build_list_params(
        page=page,
        page_size=page_size,
        provider=provider,
    )

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/notifications/webhooks/',
        token=token,
        default_message='Failed to list webhooks',
        params=params,
    )


@mcp_tool_handler(
    description=(
        'Get detailed information about a specific webhook by its ID. '
        'Returns webhook ID, name, URL, SSL verification setting, and enabled status. '
        'Use this when you need full details about one webhook rather than the summary list. '
        'Related: list_webhooks (find webhook ID first), update_webhook, delete_webhook.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'webhook detail describe single get'},
)
async def get_webhook(
    webhook_id: str, workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Get a single webhook by ID.

    Args:
        webhook_id: Webhook ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Webhook detail response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'/api/notifications/webhooks/{webhook_id}/',
        token=token,
        default_message='Failed to get webhook details',
        webhook_id=webhook_id,
    )


@mcp_tool_handler(
    description=(
        'Create a webhook endpoint to receive HTTP callbacks when subscribed '
        'events occur. Requires a name, a URL, and an owner. Needs an admin '
        'account, and creating or updating a webhook needs a paid plan.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'webhook create endpoint callback'},
)
async def create_webhook(
    workspace: str,
    name: str,
    url: str,
    owner: Annotated[str, Field(description=_OWNER_DESCRIPTION)],
    provider: Annotated[str | None, Field(description=_PROVIDER_DESCRIPTION)] = None,
    ssl_verify: bool = True,
    enabled: bool = True,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """`owner` must be a user UUID; `provider` is checked against WEBHOOK_PROVIDERS and
    detected from the URL when omitted."""
    if not validate_uuid_format(owner):
        return format_validation_error('owner', owner, _OWNER_SENTENCE)

    if provider is not None and provider not in WEBHOOK_PROVIDERS:
        return format_validation_error('provider', provider, _PROVIDERS_SENTENCE)

    token = kwargs.get('token')

    webhook_data: dict[str, object] = {
        'name': name,
        'url': url,
        'owner': owner,
        'ssl_verify': ssl_verify,
        'enabled': enabled,
        **exclude_none(provider=provider),
    }

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint='/api/notifications/webhooks/',
        token=token,
        default_message='Failed to create webhook',
        data=webhook_data,
    )


@mcp_tool_handler(
    description='Update an existing webhook configuration by its ID. Can change name, URL, SSL verification, or enabled status. Only the fields you provide will be updated (partial update). Needs an admin account and a paid plan.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'webhook update modify'},
)
async def update_webhook(
    webhook_id: str,
    workspace: str,
    name: str | None = None,
    url: str | None = None,
    ssl_verify: bool | None = None,
    enabled: bool | None = None,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Partial update; at least one of name, url, ssl_verify or enabled is required."""
    token = kwargs.get('token')

    update_data: dict[str, object] = exclude_none(
        name=name, url=url, ssl_verify=ssl_verify, enabled=enabled
    )

    if not update_data:
        return format_validation_error(
            'payload',
            None,
            'At least one of name, url, ssl_verify or enabled must be provided.',
        )

    return await http_call_response(
        http_client.patch,
        region=region,
        workspace=workspace,
        endpoint=f'/api/notifications/webhooks/{webhook_id}/',
        token=token,
        default_message='Failed to update webhook',
        data=update_data,
        webhook_id=webhook_id,
    )


@mcp_tool_handler(
    description='Permanently delete a webhook endpoint by its ID. This stops all HTTP callbacks for subscriptions using this webhook. Requires admin permission.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'webhook delete remove'},
)
async def delete_webhook(
    webhook_id: str, workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Delete a webhook, stopping callbacks for its subscriptions."""
    token = kwargs.get('token')

    return await http_call_response(
        http_client.delete,
        region=region,
        workspace=workspace,
        endpoint=f'/api/notifications/webhooks/{webhook_id}/',
        token=token,
        default_message='Failed to delete webhook',
        webhook_id=webhook_id,
    )

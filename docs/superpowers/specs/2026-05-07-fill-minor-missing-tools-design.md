# Fill Minor Missing MCP Tools — Design Spec

**Issue**: [#84](https://github.com/alpacax/alpacon-mcp/issues/84)
**Branch**: `84-feat-minor-tools`
**Date**: 2026-05-07
**Author**: Jisung Chae

## Goal

Add five small missing MCP tools and fix one mode-inconsistency in tool registration, all in a single PR.

## Scope

In scope:

- `get_current_user` — equivalent of `alpacon whoami`
- `get_webhook` — webhook detail (paired with existing list/create/update/delete)
- `get_server_note`, `update_server_note`, `delete_server_note` — complete the server-note CRUD
- Register `health_check` MCP tool in remote (streamable-http) mode in addition to stdio mode
- Unit tests for each new tool
- Documentation updates (`CLAUDE.md` tool catalog)

Out of scope:

- Group/membership listing for `whoami` (CLI calls `/api/iam/memberships/?user=…` separately; we keep the tool single-call for simplicity)
- New IAM tools beyond `get_current_user`
- Refactoring existing tools

## Endpoint Verification

The issue lists target API paths, but inspection of `01-alpacon-cli` and `03-alpacon-server` revealed mismatches. We follow the verified CLI/server paths:

| Tool | Issue says | Verified (CLI + server) | Reasoning |
|------|-----------|-------------------------|-----------|
| `get_current_user` | `/api/auth0/users/me/` | `/api/iam/users/-/` | CLI's `iam.GetCurrentUser` calls `userURL + "-/"`. Server `iam/api/urls.py` registers `users` router; `-` is the DRF current-user sentinel. |
| `get_webhook` | `/api/webhooks/webhooks/{id}/` | `/api/notifications/webhooks/{id}/` | Both CLI's `webhookURL` and existing MCP webhook tools use `notifications/webhooks/`. Server URL is registered under `notifications` app. |
| `get_server_note` | `/api/servers/notes/{id}/` | ✅ same | Server `servers/api/urls.py` registers `notes` router under `servers/`. |
| `update_server_note` | (unspecified) | `PATCH /api/servers/notes/{id}/` | CLI's `note.UpdateNote` uses `SendPatchRequest`. PATCH allows partial update, matching MCP convention (`update_webhook`). |
| `delete_server_note` | `/api/servers/notes/{id}/` | ✅ same | CLI's `note.DeleteNote` uses `SendDeleteRequest`. |

## Architecture

### File-level layout

```
tools/
  workspace_tools.py     # + get_current_user
  webhook_tools.py       # + get_webhook
  server_tools.py        # + get_server_note, update_server_note, delete_server_note
server.py                # remove `if not remote_mode:` guard around health_tools import
tests/
  test_workspace_tools.py  # + get_current_user tests
  test_webhook_tools.py    # + get_webhook tests
  test_server_tools.py     # + 3 note CRUD tests
CLAUDE.md                  # update tool catalog
```

### Decorator + annotation choices

All five new tools use `@mcp_tool_handler` (from `utils/decorators.py`) and require `workspace` (positional). This means:

- Region auto-detection (JWT or token.json) works.
- Workspace format is validated.
- Token is injected via `kwargs['token']`.
- JWT workspace authorization is enforced in remote mode.

| Tool | Annotation preset | Why |
|------|-------------------|-----|
| `get_current_user` | `READ_ONLY` | Pure read |
| `get_webhook` | `READ_ONLY` | Pure read |
| `get_server_note` | `READ_ONLY` | Pure read |
| `update_server_note` | `IDEMPOTENT_WRITE` | Same as `update_webhook` — PATCH partial update |
| `delete_server_note` | `DESTRUCTIVE` | Same as `delete_webhook` |

### `get_current_user` mode behavior

Both modes call `GET /api/iam/users/-/` with the resolved token; the upstream API returns the user owning that token (stdio: API token owner; remote: JWT subject). Description documents this so users understand the principal can differ between modes.

### `update_server_note` parameters

Mirroring `update_webhook`'s pattern: each updatable field is `Optional[T] = None`; only non-None fields are sent in the PATCH body. If no fields are provided, return `error_response('No update data provided')`.

Initial supported fields: `title`, `content`. (Other potential fields like `is_pinned` can be added later when needed — YAGNI.)

### `health_check` in remote mode

Remove the `if not remote_mode:` guard in `server.py`:

```python
# before (server.py:270-274)
if not remote_mode:
    import tools.health_tools  # noqa: F401
    logger.info('Local mode: health_check MCP tool registered')

# after
import tools.health_tools  # noqa: F401
logger.info('health_check MCP tool registered (all transports)')
```

The HTTP `/health` endpoint registered by `_register_http_health_endpoint()` stays for k8s liveness probes; the MCP tool serves natural-language calls from clients (e.g., "is the MCP server healthy?").

`health_check` itself takes no parameters and uses `@mcp.tool` directly (not `mcp_tool_handler`), so it's not subject to JWT workspace validation — making it safe to register in remote mode.

### Error handling

All new tools rely on the existing `with_error_handling` wrapper inside `mcp_tool_handler`. They do not need additional try/except. HTTP errors from `http_client` propagate as exceptions caught by the decorator and converted into `error_response` payloads.

For tools that take an ID parameter (`get_webhook`, `get_server_note`, `update_server_note`, `delete_server_note`): the ID is opaque (UUID-like) and validated upstream. We do **not** add MCP-side UUID validation since neither the existing webhook nor existing note tools do.

### Testing

Tests follow existing patterns in `tests/test_*_tools.py`:

- Use `pytest-asyncio` (`@pytest.mark.asyncio`).
- Mock `http_client.{get,patch,delete}` with `AsyncMock` returning fixture dicts.
- Mock `validate_token` / token resolution helpers as already done in test files.
- Assert: response shape (`status: success`, `data: …`), correct endpoint and method called, correct request body for PATCH.
- Edge cases: missing workspace, no update data for `update_server_note`.

For `test_health.py`: add a test verifying `health_check` is callable and returns `status: success` regardless of `ALPACON_MCP_AUTH_ENABLED`.

## Data Flow

```
MCP client
  │ tool call (e.g., get_current_user, workspace="prod", region="ap1")
  ▼
mcp_tool_handler
  │ ── validate workspace, resolve region, inject token
  ▼
tool function
  │ http_client.get(region, workspace, '/api/iam/users/-/', token)
  ▼
Alpacon API   →   response dict
  │ ── success_response(data=..., region=..., workspace=...)
  ▼
MCP client
```

## Acceptance Criteria

- [ ] `get_current_user` implemented and registered; calls `/api/iam/users/-/`
- [ ] `get_webhook` implemented and registered; calls `/api/notifications/webhooks/{id}/`
- [ ] `get_server_note`, `update_server_note`, `delete_server_note` implemented and registered with correct HTTP methods (GET/PATCH/DELETE)
- [ ] `health_check` MCP tool registered in remote mode (in addition to stdio)
- [ ] Unit tests pass for all five new tools and the relaxed health_check registration
- [ ] `CLAUDE.md` tool catalog reflects the new tools
- [ ] Existing tests continue to pass

## Open Questions / Risks

1. **`get_current_user` requires `workspace`** even though the underlying token is workspace-scoped — this means the parameter is technically redundant for stdio, but keeping it consistent with `mcp_tool_handler` simplifies the codebase. Acceptable trade-off.
2. **`health_check` in remote mode**: clients may already use the HTTP `/health` endpoint; offering both is intentional (one for infra probes, one for natural-language client calls). No conflict.
3. **`update_server_note` field set**: starting with `title` and `content` only. If users need more fields (e.g., privacy settings the CLI supports), add them in a follow-up PR.

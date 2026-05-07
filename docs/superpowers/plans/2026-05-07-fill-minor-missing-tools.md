# Fill Minor Missing MCP Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 missing MCP tools (`get_current_user`, `get_webhook`, `get_server_note`, `update_server_note`, `delete_server_note`) and register `health_check` in remote mode, all in one PR for issue #84.

**Architecture:** Each tool follows the existing `@mcp_tool_handler` pattern (token injection, validation, error handling, logging). Endpoints are verified against alpacon-cli (`/api/iam/users/-/`, `/api/notifications/webhooks/{id}/`, `/api/servers/notes/{id}/`). For `health_check`, remove the `if not remote_mode:` guard in `server.py` so the MCP tool registers in all transports.

**Tech Stack:** Python 3.13+, FastMCP, httpx, pytest + pytest-asyncio, AsyncMock.

**Spec:** `docs/superpowers/specs/2026-05-07-fill-minor-missing-tools-design.md`

---

## File Map

| File | Change |
|------|--------|
| `tools/workspace_tools.py` | Add `get_current_user` |
| `tools/webhook_tools.py` | Add `get_webhook` |
| `tools/server_tools.py` | Add `get_server_note`, `update_server_note`, `delete_server_note` |
| `server.py` | Remove `if not remote_mode:` guard around `health_tools` import |
| `tests/test_workspace_tools.py` | Add tests for `get_current_user` |
| `tests/test_webhook_tools.py` | Add tests for `get_webhook` |
| `tests/test_server_tools.py` | Add tests for new note tools |
| `tests/test_health.py` | Add test verifying `health_check` works in remote mode |
| `CLAUDE.md` | Update tool catalog |

---

## Task 1: `get_current_user`

**Files:**
- Modify: `tools/workspace_tools.py` (add new function at bottom, before the trailing comment block)
- Modify: `tests/test_workspace_tools.py` (add new test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workspace_tools.py`:

```python
class TestGetCurrentUser:
    """Test get_current_user function."""

    @pytest.fixture
    def mock_http_client(self):
        from unittest.mock import AsyncMock, patch as patch_

        with patch_('tools.workspace_tools.http_client', create=True) as mock_client:
            mock_client.get = AsyncMock()
            yield mock_client

    @pytest.fixture
    def mock_token(self):
        from unittest.mock import patch as patch_

        with patch_('utils.common.token_manager') as mock_manager:
            mock_manager.get_token.return_value = 'test-token'
            yield mock_manager

    @pytest.mark.asyncio
    async def test_get_current_user_success(self, mock_http_client, mock_token):
        """Returns current user info from /api/iam/users/-/."""
        from tools.workspace_tools import get_current_user

        mock_http_client.get.return_value = {
            'id': 'user-1',
            'username': 'alice',
            'email': 'alice@example.com',
            'role': 'staff',
        }

        result = await get_current_user(workspace='production', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['username'] == 'alice'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='production',
            endpoint='/api/iam/users/-/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_current_user_missing_workspace(self):
        """Missing workspace returns validation error."""
        from tools.workspace_tools import get_current_user

        result = await get_current_user(workspace='', region='ap1')

        assert result['status'] == 'error'
        assert 'workspace' in result['message'].lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/chaejiseong/Desktop/AlpacaX-Projects/22-alpacon-mcp/84-feat-minor-tools
.venv/bin/pytest tests/test_workspace_tools.py::TestGetCurrentUser -v
```

Expected: FAIL with `ImportError: cannot import name 'get_current_user'`.

- [ ] **Step 3: Implement `get_current_user`**

Edit `tools/workspace_tools.py`. First, add imports near the top (replace existing import block after the docstring):

```python
"""Workspace management tools for Alpacon MCP server."""

from typing import Any

from mcp.types import ToolAnnotations

from server import mcp
from utils.common import success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import READ_ONLY
```

Then, append the new function **before** the trailing `# ===` comment block at the bottom of the file:

```python
@mcp_tool_handler(
    description=(
        'Get the current authenticated user info (username, email, role, UID, shell, home directory). '
        'In stdio mode returns the API token owner; in streamable-http mode returns the JWT subject. '
        'Use this to verify identity before performing privileged actions. '
        'Related: list_workspaces (find configured workspaces).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'whoami current user identity me authenticated principal',
    },
)
async def get_current_user(
    workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the currently authenticated user.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Current user info response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/users/-/',
        token=token,
    )

    return success_response(data=result, region=region, workspace=workspace)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_workspace_tools.py::TestGetCurrentUser -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Run the full test file to ensure no regressions**

```bash
.venv/bin/pytest tests/test_workspace_tools.py -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/workspace_tools.py tests/test_workspace_tools.py
git commit -m "feat(workspace): add get_current_user tool

Calls GET /api/iam/users/-/ to return the authenticated principal.
In stdio mode the principal is the API token owner; in streamable-http
mode it is the JWT subject. Issue #84."
```

---

## Task 2: `get_webhook`

**Files:**
- Modify: `tools/webhook_tools.py` (add `get_webhook` after `list_webhooks`)
- Modify: `tests/test_webhook_tools.py` (add test in `TestWebhooks` class or new class)

- [ ] **Step 1: Write the failing test**

Append at end of `tests/test_webhook_tools.py` (before any `if __name__` block, or as a new class):

```python
class TestGetWebhook:
    """Test get_webhook function."""

    @pytest.mark.asyncio
    async def test_get_webhook_success(self, mock_http_client, mock_token_manager):
        """Returns single webhook detail by ID."""
        from tools.webhook_tools import get_webhook

        mock_http_client.get.return_value = {
            'id': 'wh-1',
            'name': 'deploy-hook',
            'url': 'https://example.com/hook',
            'enabled': True,
        }

        result = await get_webhook(
            webhook_id='wh-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'wh-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notifications/webhooks/wh-1/',
            token='test-token',
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_webhook_tools.py::TestGetWebhook -v
```

Expected: FAIL with `ImportError: cannot import name 'get_webhook'`.

- [ ] **Step 3: Implement `get_webhook`**

In `tools/webhook_tools.py`, add the following function **immediately after** `list_webhooks` (around line 183):

```python
@mcp_tool_handler(
    description=(
        'Get detailed information about a specific webhook by its ID. '
        'Returns webhook ID, name, URL, SSL verification setting, enabled status, and owner. '
        'Use this when you need full details about one webhook rather than the summary list. '
        'Related: list_webhooks (find webhook ID first), update_webhook, delete_webhook.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'webhook detail describe single get'},
)
async def get_webhook(
    webhook_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get a single webhook by ID.

    Args:
        webhook_id: Webhook ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Webhook detail response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/notifications/webhooks/{webhook_id}/',
        token=token,
    )

    return success_response(
        data=result, webhook_id=webhook_id, region=region, workspace=workspace
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_webhook_tools.py::TestGetWebhook -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test file to ensure no regressions**

```bash
.venv/bin/pytest tests/test_webhook_tools.py -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/webhook_tools.py tests/test_webhook_tools.py
git commit -m "feat(webhook): add get_webhook tool

Calls GET /api/notifications/webhooks/{id}/ to return single webhook
detail. Mirrors the existing list/create/update/delete pattern.
Issue #84."
```

---

## Task 3: `get_server_note`

**Files:**
- Modify: `tools/server_tools.py` (add after `create_server_note`, around line 213)
- Modify: `tests/test_server_tools.py` (import + new tests)

- [ ] **Step 1: Write the failing test**

Append at end of `tests/test_server_tools.py`:

```python
class TestServerNoteCRUD:
    """Tests for get_server_note, update_server_note, delete_server_note."""

    @pytest.mark.asyncio
    async def test_get_server_note_success(
        self, mock_http_client, mock_token_manager
    ):
        """Returns single note detail by ID."""
        from tools.server_tools import get_server_note

        mock_http_client.get.return_value = {
            'id': 'note-1',
            'title': 'Maintenance',
            'content': 'Sundays 2 AM UTC',
        }

        result = await get_server_note(
            note_id='note-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'note-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/note-1/',
            token='test-token',
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::TestServerNoteCRUD::test_get_server_note_success -v
```

Expected: FAIL with `ImportError: cannot import name 'get_server_note'`.

- [ ] **Step 3: Implement `get_server_note`**

In `tools/server_tools.py`, append after the existing `create_server_note` function (around line 213, before the `# === AGENT ACTION TOOLS ===` block):

```python
@mcp_tool_handler(
    description=(
        'Get detailed information about a specific server note by its ID. '
        'Returns the note title, content, server, author, timestamps, and privacy settings. '
        'Use this when you need full details about one note rather than the summary list. '
        'Related: list_server_notes (find note ID first), update_server_note, delete_server_note.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'server note detail describe single get'},
)
async def get_server_note(
    note_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get a single server note by ID.

    Args:
        note_id: Note ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server note detail response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/notes/{note_id}/',
        token=token,
    )

    return success_response(
        data=result, note_id=note_id, region=region, workspace=workspace
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_server_tools.py::TestServerNoteCRUD::test_get_server_note_success -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/server_tools.py tests/test_server_tools.py
git commit -m "feat(server): add get_server_note tool

Calls GET /api/servers/notes/{id}/ to return single note detail.
Issue #84."
```

---

## Task 4: `update_server_note`

**Files:**
- Modify: `tools/server_tools.py` (add `update_server_note` immediately after `get_server_note`)
- Modify: `tests/test_server_tools.py` (add test in `TestServerNoteCRUD`)

- [ ] **Step 1: Write the failing tests**

Append two tests inside the `TestServerNoteCRUD` class:

```python
    @pytest.mark.asyncio
    async def test_update_server_note_success(
        self, mock_http_client, mock_token_manager
    ):
        """Updates fields and returns updated note."""
        from tools.server_tools import update_server_note

        mock_http_client.patch.return_value = {
            'id': 'note-1',
            'title': 'New title',
            'content': 'New content',
        }

        result = await update_server_note(
            note_id='note-1',
            workspace='testworkspace',
            region='ap1',
            title='New title',
            content='New content',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/note-1/',
            token='test-token',
            data={'title': 'New title', 'content': 'New content'},
        )

    @pytest.mark.asyncio
    async def test_update_server_note_no_fields_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """No update fields returns validation error and no API call."""
        from tools.server_tools import update_server_note

        result = await update_server_note(
            note_id='note-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert 'no update data' in result['message'].lower()
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_server_note_partial(
        self, mock_http_client, mock_token_manager
    ):
        """Only non-None fields are sent in PATCH body."""
        from tools.server_tools import update_server_note

        mock_http_client.patch.return_value = {'id': 'note-1', 'title': 'Only title'}

        await update_server_note(
            note_id='note-1',
            workspace='testworkspace',
            region='ap1',
            title='Only title',
        )

        _, kwargs = mock_http_client.patch.call_args
        assert kwargs['data'] == {'title': 'Only title'}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_server_tools.py::TestServerNoteCRUD -v
```

Expected: FAIL with `ImportError: cannot import name 'update_server_note'`.

- [ ] **Step 3: Implement `update_server_note`**

In `tools/server_tools.py`, also need to add `IDEMPOTENT_WRITE` to the imports (if not present). Replace the import line:

```python
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, READ_ONLY
```

with:

```python
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY
```

Then append immediately after `get_server_note`:

```python
@mcp_tool_handler(
    description=(
        'Update an existing server note by its ID. Can change title or content. '
        'Only the fields you provide will be updated (partial update). '
        'Related: get_server_note (view existing note), delete_server_note.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server note update edit modify'},
)
async def update_server_note(
    note_id: str,
    workspace: str,
    title: str | None = None,
    content: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing server note.

    Args:
        note_id: Note ID
        workspace: Workspace name. Required parameter
        title: New title (optional)
        content: New content (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server note update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if title is not None:
        update_data['title'] = title
    if content is not None:
        update_data['content'] = content

    if not update_data:
        return error_response(
            'No update data provided',
            note_id=note_id,
            region=region,
            workspace=workspace,
        )

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/notes/{note_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, note_id=note_id, region=region, workspace=workspace
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_server_tools.py::TestServerNoteCRUD -v
```

Expected: PASS (4 tests so far: get + 3 update).

- [ ] **Step 5: Commit**

```bash
git add tools/server_tools.py tests/test_server_tools.py
git commit -m "feat(server): add update_server_note tool

Calls PATCH /api/servers/notes/{id}/ for partial update of title and
content. Returns error_response when no fields are provided.
Issue #84."
```

---

## Task 5: `delete_server_note`

**Files:**
- Modify: `tools/server_tools.py` (add after `update_server_note`)
- Modify: `tests/test_server_tools.py` (add test in `TestServerNoteCRUD`)

- [ ] **Step 1: Write the failing test**

Append inside `TestServerNoteCRUD`:

```python
    @pytest.mark.asyncio
    async def test_delete_server_note_success(
        self, mock_http_client, mock_token_manager
    ):
        """Deletes note by ID."""
        from tools.server_tools import delete_server_note

        mock_http_client.delete.return_value = {}

        result = await delete_server_note(
            note_id='note-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/note-1/',
            token='test-token',
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::TestServerNoteCRUD::test_delete_server_note_success -v
```

Expected: FAIL with `ImportError: cannot import name 'delete_server_note'`.

- [ ] **Step 3: Implement `delete_server_note`**

Append in `tools/server_tools.py` after `update_server_note`:

```python
@mcp_tool_handler(
    description=(
        'Permanently delete a server note by its ID. This action cannot be undone. '
        'Use with caution. Related: get_server_note (verify note before deleting), update_server_note.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server note delete remove'},
)
async def delete_server_note(
    note_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a server note.

    Args:
        note_id: Note ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server note delete response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/notes/{note_id}/',
        token=token,
    )

    return success_response(
        data=result, note_id=note_id, region=region, workspace=workspace
    )
```

- [ ] **Step 4: Run all server tests**

```bash
.venv/bin/pytest tests/test_server_tools.py -v
```

Expected: ALL PASS (existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add tools/server_tools.py tests/test_server_tools.py
git commit -m "feat(server): add delete_server_note tool

Calls DELETE /api/servers/notes/{id}/. Issue #84."
```

---

## Task 6: Register `health_check` in remote mode

**Files:**
- Modify: `server.py:270-274` (remove `if not remote_mode:` guard)
- Modify: `tests/test_health.py` (add remote-mode test)

- [ ] **Step 1: Write the failing test**

Append a new test class in `tests/test_health.py` (after `TestHealthCheckTool`):

```python
class TestHealthCheckRemoteMode:
    """Tests verifying health_check tool works in remote (streamable-http) mode."""

    @pytest.mark.asyncio
    async def test_health_check_callable_in_remote_mode(self, patched_health_remote):
        """health_check tool must work even when ALPACON_MCP_AUTH_ENABLED=true."""
        from tools.health_tools import health_check

        result = await health_check()

        assert result['status'] == 'success'
        assert result['data']['status'] == 'ok'
        assert result['data']['auth']['mode'] == 'jwt'

    def test_server_module_imports_health_tools_unconditionally(self):
        """server.run() must import tools.health_tools regardless of remote_mode.

        Verifies the guard `if not remote_mode: import tools.health_tools` has been
        removed so the MCP tool is registered in all transports.
        """
        import inspect

        import server

        source = inspect.getsource(server.run)
        # The unconditional import line should exist
        assert 'import tools.health_tools' in source
        # The previous guarded form should NOT exist
        assert 'if not remote_mode:\n        import tools.health_tools' not in source
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_health.py::TestHealthCheckRemoteMode -v
```

Expected: `test_server_module_imports_health_tools_unconditionally` FAILS (the guarded import still exists).

- [ ] **Step 3: Edit `server.py` to remove the guard**

Replace lines 270-274:

```python
    if not remote_mode:
        # Local (stdio/SSE) mode: register health_check MCP tool
        import tools.health_tools  # noqa: F401

        logger.info('Local mode: health_check MCP tool registered')
```

with:

```python
    # Register health_check MCP tool in all transports (stdio, SSE, streamable-http)
    import tools.health_tools  # noqa: F401

    logger.info('health_check MCP tool registered')
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_health.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_health.py
git commit -m "feat(health): register health_check MCP tool in remote mode

Removes the `if not remote_mode:` guard around health_tools import so
the health_check tool is callable from all MCP transports. The HTTP
/health endpoint remains unchanged (used for k8s liveness probes);
the MCP tool serves natural-language client calls.
Issue #84."
```

---

## Task 7: Update `CLAUDE.md` tool catalog

**Files:**
- Modify: `CLAUDE.md` (sections: Server management, File management/Webhook list, Authentication & workspace)

- [ ] **Step 1: Add `get_server_note`, `update_server_note`, `delete_server_note` under "🖥️ Server management"**

In `CLAUDE.md`, find the "🖥️ Server management" section. After the line:
```
- `create_server_note`: Create server notes
```
Insert:
```
- `get_server_note`: Get detailed information about a specific server note by ID
- `update_server_note`: Update an existing server note (partial update of title/content)
- `delete_server_note`: Permanently delete a server note by ID
```

- [ ] **Step 2: Add `get_webhook` under "🔗 Webhooks & event subscriptions"**

Find "🔗 Webhooks & event subscriptions" section. After the line:
```
- `list_webhooks`: List configured webhooks
```
Insert:
```
- `get_webhook`: Get detailed information about a specific webhook by ID
```

- [ ] **Step 3: Add `get_current_user` under "⚙️ Authentication & workspace"**

Find "⚙️ Authentication & workspace" section. After the line:
```
- `list_workspaces`: List available workspaces
```
Insert:
```
- `get_current_user`: Get currently authenticated user info (username, email, role, UID, shell, home directory)
```

- [ ] **Step 4: Note `health_check` registration change**

Locate the "Note: User settings and profile endpoints..." block under "⚙️ Authentication & workspace" (it explains removed tools). Below it, add a small note about health_check:

```
**Health check** (`health_check` tool) is now registered in all transports (stdio, SSE, streamable-http). Previously it was only registered in stdio mode.
```

- [ ] **Step 5: Verify the doc renders correctly**

```bash
grep -n "get_current_user\|get_webhook\|get_server_note\|update_server_note\|delete_server_note\|Health check" CLAUDE.md
```

Expected: 6 lines printed (5 tool names + Health check note).

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update tool catalog for issue #84

Adds get_current_user, get_webhook, get_server_note, update_server_note,
delete_server_note, and notes that health_check now registers in all
transports."
```

---

## Task 8: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: ALL PASS, no regressions.

- [ ] **Step 2: Verify imports compile**

```bash
.venv/bin/python -c "from server import mcp; import tools.workspace_tools, tools.webhook_tools, tools.server_tools, tools.health_tools; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Verify ruff/format passes (project uses ruff)**

```bash
.venv/bin/ruff check tools/workspace_tools.py tools/webhook_tools.py tools/server_tools.py server.py tests/test_workspace_tools.py tests/test_webhook_tools.py tests/test_server_tools.py tests/test_health.py
.venv/bin/ruff format --check tools/workspace_tools.py tools/webhook_tools.py tools/server_tools.py server.py tests/test_workspace_tools.py tests/test_webhook_tools.py tests/test_server_tools.py tests/test_health.py
```

Expected: no errors. If `ruff format --check` fails, run `.venv/bin/ruff format <files>` and add a `style:` commit.

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin 84-feat-minor-tools
gh pr create --title "feat: fill minor missing tools (#84)" --body "$(cat <<'EOF'
## Summary

Closes #84.

Adds 5 missing MCP tools and registers `health_check` in remote mode:

- `get_current_user` — `GET /api/iam/users/-/`
- `get_webhook` — `GET /api/notifications/webhooks/{id}/`
- `get_server_note` — `GET /api/servers/notes/{id}/`
- `update_server_note` — `PATCH /api/servers/notes/{id}/`
- `delete_server_note` — `DELETE /api/servers/notes/{id}/`
- Removes `if not remote_mode:` guard around `health_tools` import in `server.py`

Endpoint paths verified against `alpacon-cli` (`api/iam`, `api/webhook`, `api/note`) and `alpacon-server` (`iam/api/urls.py`, `notifications/api/urls.py`, `servers/api/urls.py`). The issue's suggested paths (`/api/auth0/users/me/`, `/api/webhooks/webhooks/`) were corrected to the verified paths.

## Test plan

- [ ] `pytest tests/test_workspace_tools.py -v` (new `TestGetCurrentUser`)
- [ ] `pytest tests/test_webhook_tools.py -v` (new `TestGetWebhook`)
- [ ] `pytest tests/test_server_tools.py -v` (new `TestServerNoteCRUD`)
- [ ] `pytest tests/test_health.py -v` (new `TestHealthCheckRemoteMode`)
- [ ] Full suite green: `pytest -v`
- [ ] Manual smoke: launch server in stdio + remote mode, call `health_check` and `get_current_user`
EOF
)"
```

Expected: PR URL printed.

---

## Self-Review Checklist

Spec coverage:
- ✅ `get_current_user` → Task 1
- ✅ `get_webhook` → Task 2
- ✅ `get_server_note` → Task 3
- ✅ `update_server_note` → Task 4
- ✅ `delete_server_note` → Task 5
- ✅ `health_check` remote registration → Task 6
- ✅ Unit tests → embedded in Tasks 1-6
- ✅ Documentation update → Task 7
- ✅ Final verification → Task 8

Placeholder check: no TBDs, all tests have full code, all commit messages explicit.

Type/name consistency:
- `get_current_user(workspace, region)` — used identically in test and impl
- `get_webhook(webhook_id, workspace, region)` — consistent
- `get_server_note(note_id, workspace, region)` — consistent
- `update_server_note(note_id, workspace, title=None, content=None, region='')` — consistent
- `delete_server_note(note_id, workspace, region)` — consistent
- All endpoints match spec table verbatim

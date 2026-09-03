---
language: en
stack: python
---

# CLAUDE.md

Alpacon MCP Server: a FastMCP server that bridges Alpacon's zero-trust
infrastructure access to AI assistants over plain HTTP. No alpacon CLI, no
subprocess, no external binaries in the runtime path.

## Red lines

- **Reach Alpacon only through `mcp__alpacon__*` tools.** Never the `alpacon`
  CLI, never `ssh`, never a shell fallback when an MCP call fails. On failure:
  report the exact error, propose another MCP route, ask for the missing
  auth/config. This constrains how you talk to Alpacon—it does not restrict
  ordinary local work in this repo (`pytest`, `git`, `uv`).
- **`server_id` is always a UUID, never a server name.** `list_servers` maps a
  name to its UUID. A name fails at the input validator, before the API call.
- **Approve/reject is human-only (ADR 0015).** No `approve_request` tool exists
  and the server answers agent/token channels with 403. When a tool returns
  `status="pending_approval"`, surface it to a human who decides out-of-band in
  the web console or Slack, then retry.

## Development commands

```bash
uv venv && source .venv/bin/activate
uv sync --extra dev         # runtime + dev dependencies

python main.py              # stdio transport (default MCP mode)
python main_sse.py          # SSE transport
python main_http.py         # streamable-http; needs AUTH0_* configured

pytest                      # test suite
python -c "from server import mcp; print('ok')"   # import smoke check
```

## Non-obvious invariants

Things the code will not tell you at a glance:

- **Regions are `ap1` and `us1` only** (the internal `dev` is not a served
  region). An omitted `region` is resolved from the JWT in remote mode and from
  `token.json` in local mode, then validated; resolution fails when the
  workspace is unknown or its token spans several regions.
- **Toolset selection crosses module boundaries.** `--toolsets` /
  `ALPACON_MCP_TOOLSETS` gates imports, and registration is an import-time side
  effect. `alpacon://servers/.../overview` is backed by `system_info_tools`, so
  `--toolsets servers` alone silently drops it. Remote mode is gated on
  `ALPACON_MCP_AUTH_ENABLED=true`, not on the transport name, and ignores the
  setting entirely.
- **`@mcp_tool_handler` owns validation, token injection, error shape, and
  logging.** Never write a try/except around an HTTP call in a tool. `region`,
  `workspace`, `server_id`, `server_ids`, `servers`, `session_id`, `limit`, and
  `page_size` are validated before the token lookup; file paths are not—call
  `validate_file_path()` inline in any tool taking a path.
  `requires_workspace=False` is for a tool that answers before a workspace is
  known: it drops the workspace checks, the workspace-keyed region resolution,
  the JWT workspace authorization, the MFA pre-check, and the stdio token
  injection. `list_workspaces` is the only tool using it. The decorator also
  rewrites the published signature, dropping the `**kwargs` it injects the token
  into: FastMCP reads that catch-all as an ordinary required field and would
  publish it to clients (#211). Two rules follow: a tool must declare `**kwargs`
  or decoration raises, and no tool may forward its own `**kwargs` on to another
  tool, because `with_logging` binds the published signature strictly and the
  injected token is no longer a parameter it accepts. `health_check` sits
  outside the decorator entirely because it must answer before any JWT exists,
  and borrows `@with_error_handling` alone for the error shape.
- **`AlpaconHTTPClient` never caches a response, deliberately.** Every read worth
  caching—the server list, process info, IAM users and groups—comes back filtered
  by the calling token's permissions, and nothing in this process sees a grant
  revoked in the web console, in Slack, or by another MCP process. Do not
  reintroduce a response cache in the shared client: a hit would answer with
  access the caller has lost. The auth-path caches stay: the JWKS keys in
  `utils/auth.py` and the workspace security settings in
  `utils/security_settings.py` are not permission-filtered tool data.
- **The WorkSession gate applies to OAuth/browser callers only.** Static API and
  service tokens bypass it, so a flow that works in stdio mode can be blocked in
  remote mode. `ALPACON_WORK_SESSION` supplies a default session id; an explicit
  `work_session_id` argument wins.
- **The API token tools 403 in stdio mode.** `APITokenObjectPermission` rejects
  `source='api'` tokens, so list/get/create/update/delete/duplicate need
  JWT/OAuth, a browser session, or a `source='login'` token. The scopes and
  presets catalogs are exempt.
- **MFA re-authentication exists only in remote/streamable-http mode**, with a
  60-second cooldown against re-auth loops.
- **The code and refresh token a remote client holds are sealed by this
  server**, carrying the device id minted for that grant. Rotating
  `ALPACON_MCP_GRANT_SECRET` (or `AUTH0_CLIENT_SECRET`, which it is derived
  from by default) logs every remote session out.

## Language and writing style

- English only: code, comments, docstrings, documentation, commit messages, PR
  titles and bodies, every identifier, and the user-facing CLI/console output
  the setup wizard and the entry points print.
- Sentence case for all headings and titles: "## Available MCP tools", not
  "## Available MCP Tools".
- Em-dashes take no surrounding spaces: "remote mode—not stdio".
- A bullet separates its item from the description with a colon:
  `` - `list_servers`: List all servers in workspace ``.
- Spell it "WebFTP", "Websh", and "MCP".

## Changelog

A change to the tool surface a client can see—a tool added or removed, a newly
accepted parameter value, a renamed argument, a changed response field—carries
its `CHANGELOG.md` entry under `[Unreleased]` in the same diff. Two or three
sentences: what changed, the issue number, and whether a client parsing the
response has to handle anything new. Refactors, test-only changes, and CI edits
get no entry.

## GitHub Actions conventions

Keep `permissions: contents: read` at the workflow level; add extra scopes on
the job that needs them, never at the workflow level.

## Where the detail lives

- `docs/api-reference.md`: every tool, its parameters, and its response shape.
  Read it before calling an unfamiliar tool or adding one—it is the catalog this
  file deliberately does not duplicate.
- `CONTRIBUTING.md` (`## 🔧 Adding new features`): the full recipe for a new
  tool—module skeleton, `TOOLSET_REGISTRY` entry, `tools/resources.py` row,
  test, docs. Follow it whenever you add a tool.
- `CONTRIBUTING.md` (`### Code style`): the import rule—function/method-local
  imports need a stated reason, not habit.
- `docs/configuration.md`: token discovery order, transports, `--toolsets`,
  client config. Read it when authentication or startup misbehaves.
- `README.md` (`Pinning a workspace API host`): the object form of a token entry
  and why a derived host can resolve to the wrong workspace (ADR 0027).
- `docs/mfa-reauth-flow.md`: the two-stage Auth0 re-auth sequence. Read it only
  when touching `auth_error_middleware.py` or the OAuth routes.
- `docs/troubleshooting.md`: symptom-first fixes, including which env var names
  actually resolve.
- `docs/examples.md`: worked call sequences for common operations.

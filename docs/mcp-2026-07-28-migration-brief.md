# MCP 2026-07-28 migration decision brief

Status: Agreed migration brief

Date: 2026-09-15

## Purpose

Upgrade the Alpacon MCP server to MCP protocol revision `2026-07-28` and the official Python `mcp` SDK 2.x line without changing the upstream Alpacon API contract.

The migration must also correct the remote authorization boundary. An access token accepted by the MCP resource must not be forwarded to the Alpacon API. Remote production release therefore depends on both the SDK migration and a proven two-token authorization path.

Terminology used in this brief is defined in [`CONTEXT.md`](../CONTEXT.md).

## Repository starting point

- Dependency: `mcp>=1.28.1,<2`, locked to `1.28.1` at the start of discovery.
- Transports: stdio, SSE, and stateless Streamable HTTP.
- Remote authorization: An embedded OAuth proxy maps MCP clients to one configured Auth0 application and obtains an Alpacon-audience access token.
- MFA: Workspace-sensitive checks use a two-stage Auth0 flow and a grant-specific sealed device ID.
- Tracking: GitHub issue #248 is the migration umbrella, and #144 is the agent-ready SDK and protocol foundation. No matching PR or remote branch existed when discovery began. The local working branch is `mcp-v2-upgrade`.

## Scope

- Protocol and SDK: Adopt protocol revision `2026-07-28` and Python SDK `2.2.x`, with a dependency range of `mcp>=2.2,<3` and an exact lockfile resolution.
- Server API: Migrate from `FastMCP` to the SDK 2.x `MCPServer` API and its snake_case protocol types.
- HTTP runtime: Build an explicit ASGI application for Streamable HTTP and preserve stateless request handling.
- Authorization: Separate the MCP resource token from the Alpacon API token.
- MFA: Preserve workspace-sensitive step-up behavior and make it work across access-token refresh.
- Compatibility: Provide official support for protocol revision `2026-07-28` and best-effort behavior for clients that negotiate a 2025-era revision.
- New protocol capabilities: Add server discovery metadata, use MRTR for command purpose demands, add conservative cache hints, and establish a working subscription connection lifecycle.
- SSE: Retain it as deprecated during the migration window.

## Non-goals

- Changing the Alpacon API contract.
- Adding an agent-accessible approval or rejection operation.
- Treating a command purpose demand as human approval.
- Adding a server-side cache for permission-filtered Alpacon responses.
- Shipping Alpacon domain events over MCP subscriptions before an authoritative upstream event feed and multi-replica delivery design exist.
- Promising full support for every legacy MCP client.
- Switching all production clients to direct Auth0 authorization as part of the SDK foundation change.

## Protocol and compatibility decisions

- Protocol name: Use `MCP 2026-07-28` for the protocol revision. Use `SDK 2.x` only for the Python package line.
- Supported revision: Treat `2026-07-28` as the supported protocol contract.
- Legacy negotiation: Allow the SDK's automatic 2025-era negotiation, but classify it as best effort.
- SSE lifecycle: Keep SSE for at least one deprecated release. Remove it only after supported clients have moved, migration documentation exists, and a breaking-compatible release is available.
- Stateless HTTP: Preserve `stateless_http=True` explicitly. This behavior fixed session failures across redeploys and must not depend on an SDK default.
- Response mode: Preserve JSON response behavior required by the remote authentication challenge path.

## ASGI runtime decisions

- Composition: Create the Streamable HTTP app explicitly with the SDK application builder.
- Middleware: Wrap the MCP app with `UpstreamAuthErrorMiddleware` instead of monkeypatching an SDK runner.
- Server process: Run the composed app with uvicorn.
- Streaming: Redesign middleware response handling so it does not buffer an unbounded subscription stream.
- Route preservation: Keep the current OAuth discovery, authorization, token, registration, callback, and compatibility routes.
- Lifecycle: Start and stop the MCP session manager exactly once through ASGI lifespan handling.

## Authorization decisions

The client-facing and upstream credentials have different resource audiences:

1. The MCP client obtains Token A for the canonical Alpacon MCP resource.
2. The MCP server validates Token A and never forwards it.
3. The MCP server obtains Token B for the existing Alpacon API audience.
4. Only Token B is sent to the Alpacon API.

The preferred upstream token path is Auth0 On-Behalf-Of exchange. It keeps the exchange inside the confidential MCP service and preserves the user subject. It is acceptable only if the server can establish trustworthy workspace authorization, client-instance identity, and MFA assurance in Token B.

If native OBO cannot establish those claims, evaluate Auth0 Custom Token Exchange. If custom exchange cannot meet the same boundary safely, retain the OAuth proxy as a two-token backend-for-frontend. Client Credentials Flow is not a substitute because it loses the initiating user's authorization and MFA context.

The SDK foundation may merge independently, but remote production release remains blocked until the two-token path passes its release gates.

## Auth0 client registration decisions

- Preferred client identity: Use Auth0 CIMD for clients whose metadata document has been registered with the tenant.
- Compatibility registration: Keep native Auth0 DCR available for clients that cannot use the registered CIMD path during the transition.
- Tenant validation: Do not advertise CIMD until the tenant flag, manual import behavior, client grants, connections, and issuer metadata have been verified.
- Rollout: Keep the existing proxy for production while direct Auth0 authorization is tested with canary clients.
- Session migration: Require a fresh login when switching a client from the proxy issuer to direct Auth0 authorization.

## MFA decisions

Initial-login MFA and operation-specific step-up MFA are separate behaviors.

- Product behavior: Preserve workspace and action sensitivity instead of forcing tenant-wide MFA for every login.
- Modern challenge: For protocol revision `2026-07-28`, return `403 insufficient_scope` with the required operation scopes, `alpacon:mfa`, and protected-resource metadata.
- Legacy challenge: Preserve the current `401` reauthorization behavior for legacy clients where the negotiated protocol can be identified safely.
- Auth0 action: In direct authorization mode, an Auth0 post-login Action challenges MFA when `alpacon:mfa` is requested and records the completed method and timestamp in a namespaced access-token claim.
- Presence resolution: Alpacon owns one server-side resolver that selects ordinary `mfa_timeout` or sensitive `sensitive_mfa_timeout` from the declared action class. The MCP server consumes the resolved tier and window and does not recompute them from raw settings.
- Client-instance binding: The presence proof belongs to the requesting client instance. Token A and Token B must carry trustworthy `client_instance` and `client_instance_source` claims distinct from the OAuth `client_id`.
- Refresh isolation: MFA state must remain specific to one client instance and authorization grant. A refreshed token must not inherit user-global MFA state or silently retain a stale timestamp.
- Current proxy: Preserve the existing two-stage MFA flow and sealed grant-specific `device_id` during the SDK foundation change.
- Direct Auth0 gate: Require proof of grant-local refresh behavior. Auth0 Refresh Token Metadata may be piloted where the tenant has the required feature; otherwise retain the proxy, require secure re-prompting, or use a purpose-built grant-bound store.
- Failure handling: Reproduce the current nonfatal Stage 1 exchange failure in a focused follow-up before changing it. If reproduced, make the exchange fail closed.

The regression scenario is not only first authorization. A real browser session must complete MFA, refresh its token after the access token expires, retry the protected operation, and retain isolation from a second grant for the same user.

## New MCP capability decisions

- Server discovery: Publish the package version and safe server instructions through `server/discover`.
- MRTR: Replace the separate command-purpose round trip with a conditional Multi Round-Trip Request after Alpacon reports `awaiting_purpose`.
- Command identity: Resume the existing `command_id`; do not create a second command.
- Request state: Seal and bind MRTR state so it cannot be replayed for another user, workspace, server, or command.
- Approval boundary: MRTR may supply command purpose, but it must never approve or reject a request. Approval remains human-only and out of band.
- Cache hints: Add positive cache hints only to static MCP catalogs and discovery metadata.
- Permission-filtered data: Keep Alpacon-backed server, process, IAM, and resource reads private with `ttlMs: 0`.
- Subscription foundation: Prove authenticated `subscriptions/listen` connection, cancellation, and cleanup without hanging the server.
- Domain events: Track WorkSession, command, WebFTP, alert, analysis, and certificate events in a later cross-service design after an upstream event source exists.

## Release gates

### SDK and protocol

- The package imports and starts under every supported Python version.
- Contract snapshots cover tools, resources, prompts, schemas, annotations, and discovery metadata.
- In-process clients pass with protocol revision `2026-07-28`.
- Selected legacy negotiation tests pass without defining a formal legacy support promise.
- stdio and Streamable HTTP pass their transport suites.
- SSE remains functional and is marked deprecated.

### HTTP and streaming

- OAuth routes remain reachable under the explicit ASGI composition.
- ASGI lifespan starts and stops shared MCP state once.
- Finite JSON responses preserve the current authentication-error translation.
- A subscription can connect, stream or idle without response buffering, cancel, and release its resources.

### Authorization and MFA

- Token A has the canonical MCP resource audience and is rejected for any other resource.
- Token B has the existing Alpacon API audience and never reaches the MCP client.
- OBO or its selected fallback preserves the user, workspace authorization, allowed scopes, `client_instance`, `client_instance_source`, and current MFA assurance required by Alpacon.
- A modern SDK client responds to `403 insufficient_scope`, completes MFA, and retries once with the added scope.
- Every supported production host, including Claude clients, passes the same user-visible flow.
- Ordinary and sensitive actions use the presence freshness window selected by Alpacon's declared-action resolver.
- Refresh after access-token expiry preserves client-instance-bound state or causes a secure MFA re-prompt.
- Two client instances for the same user cannot share MFA completion state.
- Auth0 or exchange failures do not yield a privileged session.

### Auth0 rollout

- One registered CIMD public client and one DCR public client complete Authorization Code with PKCE.
- An unregistered CIMD URL fails explicitly instead of falling back silently.
- Tenant discovery metadata, API grants, connections, and issuer values match the server configuration.
- Direct Auth0 authorization remains a canary until audience separation, MFA refresh behavior, and client UX pass end to end.

## Evidence still required

The remaining items are validation work, not unresolved product decisions:

- Confirm the production Auth0 tenant entitlement and enablement for CIMD, OBO, CTE, and Refresh Token Metadata.
- Confirm whether an OBO post-login Action can recalculate every workspace, client-instance, and MFA claim required by the Alpacon API.
- Confirm the deployed Auth0 Action's behavior on authorization, MFA completion, and refresh.
- Confirm the exact Alpacon `auth_mfa_required` response shape.
- Confirm runtime scope step-up behavior in every supported client host.
- Identify an authoritative upstream event feed before designing domain subscriptions.

## Documentation decision

No new ADR is required at this stage. Protocol token separation is a compliance constraint, while OBO, CTE, and a two-token proxy remain conditional implementation choices. The implementation must comply with `alpacon-handbook` ADR 0051 for declared action classes and two presence freshness windows, and ADR 0054 for client-instance-bound presence. If production later commits to one cross-service authorization topology, record that decision in the `alpacon-handbook` ADR collection.

## Research inputs

- [`mcp-v2-research.md`](mcp-v2-research.md): Protocol and Python SDK migration research.
- [`mcp-v2-capabilities-research.md`](mcp-v2-capabilities-research.md): MRTR, cache hints, and subscription fit.
- [`auth0-cimd-research.md`](auth0-cimd-research.md): Auth0 CIMD and DCR integration research.
- [`auth0-mcp-mfa-research.md`](auth0-mcp-mfa-research.md): Initial and step-up MFA research.
- [`auth0-mcp-upstream-token-research.md`](auth0-mcp-upstream-token-research.md): MCP and Alpacon token audience separation research.

## Interview result

The product decision frontier is empty. The overall migration is not one agent-ready unit: the SDK foundation can proceed independently, while production authorization remains gated on tenant evidence and a proven OBO, CTE, or two-token proxy path. Split implementation into bounded issues and apply `ready-for-agent` only to work whose prerequisites are satisfied.

# MCP 2026-07-28 and Python SDK v2 research

Research date: 2026-09-15

## Conclusion

The recent release is a coordinated pair, not one artifact formally named "MCP v2":

- Protocol: MCP revision `2026-07-28`. MCP protocol versions remain date-based; this is the stable revision after `2025-11-25`.
- Python package: `mcp` v2. The stable `2.0.0` release implements `2026-07-28` and earlier protocol revisions.

The migration should therefore include both the Python SDK 1.x-to-2.x API port and explicit verification of the `2026-07-28` protocol behavior. A dependency-only upgrade would miss the architectural changes the new protocol is intended to deliver.

The official MCP project announced the protocol revision and updated Tier 1 SDKs together on July 28, 2026. The announcement describes `2026-07-28` as the next specification version and lists Python among the SDKs that supported it at launch. [Official release announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/)

## Release status and dates

- May 21, 2026: The MCP project published the `2026-07-28` release candidate and scheduled the final specification for July 28. [Official release candidate announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
- July 28, 2026: Protocol revision `2026-07-28` became stable. [Official specification release](https://github.com/modelcontextprotocol/modelcontextprotocol/releases/tag/2026-07-28)
- July 28, 2026: Python SDK `2.0.0` became stable. It supports `2026-07-28`, serves earlier revisions from the same server, and made unpinned `mcp` installs resolve to 2.x. [Python SDK v2.0.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0)
- September 7, 2026: Python SDK `2.2.0` was published and is the current stable release as of this research date. [Python SDK v2.2.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.2.0)
- Support policy: 2.x is the active line for features and fixes. The `v1.x` branch receives only critical bug fixes and security fixes. [Python SDK versioning policy](https://github.com/modelcontextprotocol/python-sdk/blob/main/VERSIONING.md)

## Protocol changes that define the target

The `2026-07-28` revision is an architectural protocol change, not just a schema refresh:

- Stateless requests: The protocol removes `initialize`/`notifications/initialized` and protocol-level sessions. The `Mcp-Session-Id` header is absent on the modern Streamable HTTP path.
- Self-contained metadata: Each request carries the protocol version and client capabilities in `_meta`; client identity is recommended. Servers identify themselves in result metadata.
- Discovery: Servers implement `server/discover`, which clients may use for version and capability discovery.
- Multi Round-Trip Requests: MRTR replaces server-initiated roots, sampling, and elicitation requests. A server returns `InputRequiredResult`, and the client retries the original request with answers.
- Subscription stream: `subscriptions/listen` replaces the old HTTP GET notification path and resource subscription methods.
- Routable HTTP requests: `Mcp-Method` and `Mcp-Name` headers allow gateways to route or authorize without parsing the JSON body.
- Cacheable catalogs: List and resource results include cache hints, and list order must be deterministic.
- Extensions: Optional features now use a formal extensions framework; Tasks moved out of the core protocol.
- Deprecations: Roots, Sampling, Logging, HTTP+SSE, and Dynamic Client Registration are deprecated. `ping`, `logging/setLevel`, and `notifications/roots/list_changed` are removed from the modern revision.

The normative change list is in the [official `2026-07-28` changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog), and the released specification is at [MCP specification `2026-07-28`](https://modelcontextprotocol.io/specification/2026-07-28).

## Python SDK v2 migration implications

The Python SDK combines protocol support with a breaking SDK redesign:

- High-level server: `mcp.server.fastmcp.FastMCP` becomes `mcp.server.MCPServer`; the old import path is removed. The ordinary `@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()` decorator surface remains largely unchanged.
- Protocol compatibility: One `MCPServer` serves `2026-07-28` and legacy 2025-era clients over Streamable HTTP and stdio. A separate legacy deployment is not required.
- Client negotiation: The new high-level `Client` defaults to automatic discovery, adopts `2026-07-28` when available, and falls back to the legacy initialization handshake for older servers.
- Context: `MCPServer.get_context()` is removed; handlers that need context declare a `Context` parameter.
- Transport configuration: Transport-specific settings move from the server constructor to `run()` or the ASGI app builders. `mount_path` is removed.
- Lifespan: Streamable HTTP lifespan runs once at manager startup and is shared across sessions and requests, instead of running per session or request.
- Execution behavior: Synchronous handlers run on a worker thread. Thread-affine code needs review.
- Types and validation: Wire types move to the lock-stepped `mcp-types` distribution, Python attributes use snake_case, and both server results and client responses receive stricter protocol validation.
- Errors: `McpError` becomes `MCPError`; tool and protocol error behavior changes, so callers and tests must assert the new result/error boundary.
- HTTP dependency: The SDK replaces `httpx` and `httpx-sse` with `httpx2`. Custom clients, auth classes, exception handlers, test fixtures, TLS trust configuration, and telemetry hooks need an explicit audit.
- Modern interaction model: Code that depends on server-initiated requests cannot use that path on `2026-07-28`. Prefer `Resolve(...)` or explicit MRTR results; use a legacy client mode only when the legacy push behavior is intentionally required.

The official overview is [What's new in v2](https://py.sdk.modelcontextprotocol.io/whats-new/). The exhaustive source of breaking changes and before-and-after examples is the [Python SDK v1-to-v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/).

## Recommended planning boundary

The plan should target the current stable 2.x line and treat protocol adoption as a first-class acceptance criterion:

1. Update dependency constraints and resolve the v2 dependency graph.
2. Port imports, type names, server construction, transport setup, context access, auth, and HTTP client integration.
3. Preserve the existing public tool and resource contract unless a documented protocol rule requires a change.
4. Verify the server using a modern `2026-07-28` client path and a legacy `2025-11-25` path.
5. Add protocol-focused checks for discovery, absent session state on the modern path, request metadata, headers, result validation, notifications, errors, and any MRTR-relevant behavior.
6. Review every use of deprecated Roots, Sampling, Logging, HTTP+SSE, and Dynamic Client Registration rather than treating warnings as incidental.
7. Run the full suite and audit behavior that can change without an import error, especially lifespan scope, worker-thread execution, stricter validation, HTTP exception types, and TLS trust.

This ordering follows the official migration guide: dependencies first, then mechanical renames, server and client surfaces, transports and auth, stricter validation tests, and deprecation warnings.

## Legacy HTTP+SSE in Python SDK 2.2

Python SDK 2.2 still supports the old server-side HTTP+SSE transport. `mcp.run(transport="sse")` accepts the legacy `sse_path` and `message_path` settings. The SDK documentation says this mode exists for clients that have not moved yet, but new deployments should use `streamable-http`. [Python SDK transport guide](https://py.sdk.modelcontextprotocol.io/run/)

The protocol status is stricter than the SDK runtime status:

- Deprecation: HTTP+SSE has been deprecated since protocol revision `2025-03-26`; its migration path is Streamable HTTP.
- Removal threshold: The earliest removal point is three months after SEP-2596 reached Final. SEP-2596 was merged on May 18, 2026, so the threshold was reached on August 18, 2026. This is an eligibility date, not an actual removal date; the Core Maintainers must still choose removal in a later Current revision. [Deprecated features registry](https://modelcontextprotocol.io/specification/2026-07-28/deprecated) [SEP-2596](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2596)
- SDK independence: Removing a feature from the specification does not force every SDK to remove it at the same time. Each SDK applies its own supported-revision policy. [Feature lifecycle policy](https://modelcontextprotocol.io/community/feature-lifecycle)

The separate [legacy-client compatibility mode](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/) should not be confused with HTTP+SSE. One Streamable HTTP application automatically serves both `2026-07-28` and 2025-era protocol clients, choosing behavior from `MCP-Protocol-Version`. Therefore, this project should make Streamable HTTP the primary deployment, retain HTTP+SSE only for clients that truly require that transport, and define evidence and a date for removing the compatibility endpoint.

## Automatic dual-era server compatibility

For the SDK-provided Streamable HTTP server, 2025-era compatibility is automatic and cannot be disabled by configuration. There is no `legacy=` option, supported-version allowlist, or era rejection switch on `streamable_http_app()`, `run()`, or the session manager; both eras are always active and requests are routed before application code runs. `stateless_http` is not an enable/disable switch: it changes only how the legacy leg stores sessions, while modern `2026-07-28` requests remain stateless either way. [Python SDK legacy-client guide](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/)

The remaining cost is concrete:

- Sessionful legacy mode: Each initialized client consumes an in-process session record, streams, and a background task. Because there is no distributed session store, multi-worker deployments require sticky routing. `session_idle_timeout` (default 1,800 seconds) and `max_sessions` (default 10,000) bound this per-process state.
- Stateless legacy mode: `stateless_http=True` removes the session and sticky-routing cost, but also removes both legacy server-to-client channels. Push elicitation, sampling, roots, and a legacy `Resolve` fail with `NoBackChannelError`; notifications are dropped.
- Handler maintenance: Ordinary tools, resources, prompts, structured output, progress, and errors remain era-neutral. Change notifications are the exception: `ctx.notify_*` reaches modern subscriptions, while `ctx.session.send_*` reaches legacy sessions, so code that must notify both eras calls both.
- Test maintenance: `Client(mcp)` always negotiates `2026-07-28` against an `MCPServer`, so it never exercises the fallback. Keep explicit `Client(mcp, mode="legacy")` coverage for the selected session model, any resolver or push behavior, and both notification paths; retain the default client path for modern behavior. [Python SDK protocol-version guide](https://py.sdk.modelcontextprotocol.io/protocol-versions/)

## OAuth registration under `2026-07-28`

Client ID Metadata Documents (CIMD) are now the preferred dynamic registration mechanism. A client uses a stable HTTPS metadata-document URL as its `client_id`; the authorization server fetches and validates the document. Clients should use registration mechanisms in this order: pre-registered information, CIMD when the authorization-server metadata advertises `client_id_metadata_document_supported: true`, Dynamic Client Registration (DCR) when a `registration_endpoint` is advertised, then a user prompt. [Client registration specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)

DCR is deprecated, but the protocol explicitly permits it for backward compatibility and specific requirements. Its earliest specification-removal revision is the first revision on or after July 28, 2027. Persisted DCR or pre-registered credentials must be bound to the exact authorization-server issuer, and OIDC DCR clients must send an appropriate `application_type`. [Authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) [Deprecated features registry](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)

Python SDK 2.2 implements both paths on the client side. `OAuthClientProvider(..., client_metadata_url=...)` uses CIMD when advertised and silently falls back to DCR otherwise; the SDK handles discovery, registration selection, PKCE, issuer checks, issuer-bound credential storage, and token refresh. [Python SDK OAuth client guide](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/) On the server side, the preferred production model is an MCP resource server configured with `auth=` and `token_verifier=`; the SDK publishes Protected Resource Metadata and validates bearer tokens, while login, consent, client registration, and token issuance remain authorization-server responsibilities. [Python SDK authorization guide](https://py.sdk.modelcontextprotocol.io/run/authorization/)

This project may retain its custom RFC 7591-style `/oauth/register` proxy during the v2 migration. DCR remains a permitted fallback, and `MCPServer.custom_route()` remains supported for OAuth-related endpoints. Such routes are unauthenticated by the SDK and must implement their own validation and security controls. [Python SDK `custom_route` API](https://py.sdk.modelcontextprotocol.io/api/mcp/server/mcpserver/server/) [Python SDK ASGI guide](https://py.sdk.modelcontextprotocol.io/run/asgi/)

Retention should be treated as a compatibility decision, not the target architecture:

- Keep advertising `registration_endpoint` while old clients need the proxy.
- Do not advertise `client_id_metadata_document_supported: true` until the proxy authorization server can fetch and validate a client's HTTPS metadata document and accept the document URL as the `client_id`. Adding the metadata flag alone would not make the existing shared-client-ID proxy a CIMD implementation.
- Accept and correctly handle `application_type`, bind any stored registration to the exact issuer, and avoid describing a shared preconfigured client-ID adapter as a general-purpose RFC 7591 server.
- Plan CIMD and/or explicit pre-registration separately, then remove the DCR route only after compatibility evidence supports it.

## SDK-managed and application-managed protocol behavior

Python SDK 2.2 supplies the protocol machinery, but it cannot choose the application's caching, interaction, authorization, or event semantics.

| Feature | SDK-managed behavior | Application or deployment responsibility |
|---|---|---|
| `server/discover` | `MCPServer` serves discovery on every transport. The high-level client probes it and falls back to the legacy handshake when needed. [Protocol-version guide](https://py.sdk.modelcontextprotocol.io/protocol-versions/) | Set the server identity and instructions, register the intended tools/resources/prompts, and test both negotiated eras. |
| Request metadata | The inbound dispatcher classifies modern requests, validates `_meta`, version, and capabilities, and produces typed protocol errors. [Inbound request API](https://py.sdk.modelcontextprotocol.io/api/mcp/shared/inbound/) | Read `Context` only when business logic needs client metadata or capabilities; ordinary handlers should not parse protocol metadata. |
| Routable headers | The server validates standard `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` headers against the request; the high-level client emits them. [Streamable HTTP specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) | Configure proxies and browser CORS to pass `Mcp-*` headers. Select and expose optional `Mcp-Param-*` headers with `x-mcp-header` only where gateway routing needs them. |
| Cache hints | `MCPServer` emits conformant hints by default (`ttlMs: 0`, private scope) and omits them for old clients. The high-level client cache consumes valid hints. [Python SDK caching guide](https://py.sdk.modelcontextprotocol.io/client/caching/) | Choose safe nonzero TTLs/scopes with `cache_hints=`. Hints do not make the server cache results; public scope requires a data-sensitivity decision. |
| MRTR | `Resolve(...)` converts elicitation, sampling, or roots dependencies into modern `InputRequiredResult`/retry behavior and adapts the legacy backchannel automatically. The high-level client drives the retry loop. [Python SDK MRTR guide](https://py.sdk.modelcontextprotocol.io/handlers/multi-round-trip/) | Declare `Resolve` dependencies and implement the question, validation, continuation, and cancellation semantics. Ordinary tools do not become multi-round-trip workflows automatically. |
| Subscriptions | `MCPServer` serves `subscriptions/listen`, acknowledges and filters subscriptions, stamps subscription IDs, and manages stream lifecycle. [Python SDK subscriptions guide](https://py.sdk.modelcontextprotocol.io/handlers/subscriptions/) | Publish meaningful change events, enforce per-user subscription access where required, and replace the default in-memory bus for multi-process or multi-replica delivery. |

The same Streamable HTTP ASGI application provides the modern and legacy wire adaptations; application code should not fork a second server merely to negotiate the 2025 protocol era. [Python SDK legacy-client guide](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/)

## Known gaps

Protocol support does not mean every optional extension or auth mechanism is implemented. The Python SDK `2.2.0` release notes still list the Tasks extension, DPoP, and the `jwt-bearer` grant as unimplemented. These should not be acceptance criteria for this migration unless the project separately decides to implement or wait for them. [Python SDK v2.2.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.2.0) [Python SDK roadmap](https://github.com/modelcontextprotocol/python-sdk/blob/main/ROADMAP.md)

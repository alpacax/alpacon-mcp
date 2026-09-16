# MCP 2026-07-28 capability research

## Scope and conclusion

This note compares MCP `2026-07-28` and the official Python SDK 2.x with the
`2025-11-25` protocol era and Python SDK 1.x. Only first-party MCP
specifications, SEPs, and official Python SDK documentation, source, and
releases are used.

The three features are new at different levels:

| Feature | What is genuinely new | Verdict |
| --- | --- | --- |
| Multi Round-Trip Requests (MRTR) | A standard way to obtain elicitation, sampling, or roots input while every wire leg remains an independent client-to-server request | Materially new for stateless remote servers; not a new kind of user/model interaction |
| `subscriptions/listen` | One explicitly filtered and acknowledged notification stream, with the same request model on HTTP and stdio | A new RPC and cleaner contract, but primarily a replacement for existing notifications and resource subscriptions |
| Cache hints | A transport-neutral freshness and authorization-scope contract, plus an SDK-managed client response cache | A genuinely new interoperable contract; caching itself was always possible as custom application logic |

Python SDK 2.0 is the first stable Python line that implements the 2026
revision while continuing to serve earlier revisions. Python 1.x remains a
maintenance line ([Python SDK v2.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0)).

## Multi Round-Trip Requests

### Predecessor behavior

The 2025 protocol already supported the underlying interactions. A server sent
`elicitation/create`, `sampling/createMessage`, or `roots/list` as a new
server-to-client JSON-RPC request while it was handling the original request.
The official specifications show this directly for
[elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation),
[sampling](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling),
and [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
whose response SSE stream could carry server requests before the final result.
Python SDK 1.x exposed callbacks for all three request types and negotiated the
corresponding capabilities during `initialize`
([v1 client source](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/src/mcp/client/session.py#L111-L192)).

That model was operationally awkward for remote servers. The original handler
and SSE stream stayed alive while the client answered on a separate request.
With multiple replicas, the answer could reach a different instance, forcing a
shared state store or sticky routing. SEP-2322 documents both approaches and
their scaling, reliability, and lifecycle costs
([SEP-2322 motivation](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2322-MRTR.md#motivation)).

### What 2026 and Python 2.x enable

The server can now return `InputRequiredResult` with
`resultType: "input_required"`, a keyed `inputRequests` map, and optional opaque
`requestState`. The client fulfills the requests and retries the original
operation with matching `inputResponses` and the echoed state. The original
request is finished; each retry has a new JSON-RPC ID and can reach any replica
([SEP-2322 ephemeral workflow](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2322-MRTR.md#ephemeral-tool-workflow)).

This does not add a new input kind: the embedded requests still use the old
elicitation, sampling, and roots payloads. It adds the standard stateless form
that was unavailable to those features. The Python 2.x high-level client drives
the retry loop through the same callbacks used for legacy server-initiated
requests. On the server, `Resolve(...)` dependencies can return `Elicit`,
`Sample`, or `ListRoots`; low-level handlers can return `InputRequiredResult`
directly
([Python MRTR guide](https://py.sdk.modelcontextprotocol.io/handlers/multi-round-trip/)).

### Limits and server work

- Supported operations: Core MRTR applies to `tools/call`, `prompts/get`, and
  `resources/read`, not list or completion operations. A static high-level
  resource cannot participate because it has no `Context`; a template resource
  can ([Python MRTR server API](https://py.sdk.modelcontextprotocol.io/handlers/multi-round-trip/#beyond-tools)).

- Re-entry: A server handler may run again with the same ordinary arguments and
  new `inputResponses`. Application code must therefore be safe to re-enter:
  defer irreversible effects until required input is available, or encode the
  phase and accumulated facts in `requestState`.

- State security: The client is an untrusted carrier. Servers must validate
  echoed state and bind user-specific state to the authenticated user
  ([SEP-2322 requirements](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2322-MRTR.md#protocol-requirements-for-ephemeral-workflow)).
  `MCPServer` seals and verifies state by default, but its generated key is
  process-local. Multi-worker, load-balanced, restart-surviving deployments
  must configure shared `RequestStateSecurity` keys and a consistent audience
  ([Python deployment guide](https://py.sdk.modelcontextprotocol.io/run/deploy/#requeststate-across-workers)).

- Bounded, not durable: Python's automatic client loop defaults to ten input
  rounds; applications needing a wall-clock bound or cross-process client flow
  must drive and persist the loop themselves. MRTR is not durable job execution.
  The Tasks extension is the protocol answer for durable work, but it remains
  unimplemented in Python SDK 2.2
  ([Python MRTR client guide](https://py.sdk.modelcontextprotocol.io/handlers/multi-round-trip/#the-client-side),
  [Python SDK roadmap](https://github.com/modelcontextprotocol/python-sdk/blob/main/ROADMAP.md#not-yet-implemented)).

Adoption is worthwhile when a tool, prompt, or resource read needs client-only
input and must work over stateless HTTP, ordinary load balancing, serverless
infrastructure, or transports without a reverse request channel. It adds little
for servers that never request client input, and it should not replace durable
Tasks for long-running, crash-resumable work.

## Subscriptions

### Predecessor behavior

Change notification was already part of MCP. In 2025, a server could advertise
`listChanged` and push `notifications/tools/list_changed`,
`notifications/prompts/list_changed`, or `notifications/resources/list_changed`.
Resources separately supported `resources/subscribe` and
`resources/unsubscribe` for URI-specific `notifications/resources/updated`
([2025 resources specification](https://modelcontextprotocol.io/specification/2025-11-25/server/resources),
[2025 tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)).
Python SDK 1.x exposed the resource subscribe/unsubscribe requests and otherwise
routed server notifications through a general message handler
([v1 client source](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/src/mcp/client/session.py#L323-L352)).

Under Streamable HTTP, unrelated server notifications depended on the
session-associated GET SSE channel. The subscription state was consequently
tied to the connection/session model.

### What 2026 and Python 2.x enable

`subscriptions/listen` replaces both the standalone HTTP GET stream and the
resource subscribe/unsubscribe RPCs. One long-lived client request explicitly
selects tool, prompt, and resource-list changes plus resource URIs. The server's
first frame acknowledges the subset it will honor, and every delivered event is
tagged with the listen request ID. Multiple concurrent subscriptions are
allowed, and the same contract works over HTTP POST/SSE and stdio
([SEP-2575 subscription contract](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2575-stateless-mcp.md#subscriptionslisten-rpc)).

This is mainly consolidation and explicit filtering, not a previously
impossible notification capability. It does make subscriptions self-contained
instead of hidden session state, and it gives clients a typed, acknowledged
stream rather than requiring them to interpret all notifications from a general
connection callback.

### Limits and server work

- Still a stream: A subscription remains long-lived. It has no replay log or
  resumability; after a drop, clients re-listen and refetch. Events are change
  cues, not data payloads
  ([Python client subscription guide](https://py.sdk.modelcontextprotocol.io/client/subscriptions/)).

- Publishing: `MCPServer` serves `subscriptions/listen` automatically, but the
  application must publish the relevant `ctx.notify_*` event when its catalog
  or resource changes. Modern `notify_*` publishing is distinct from the legacy
  2025 notification path
  ([Python server subscription guide](https://py.sdk.modelcontextprotocol.io/handlers/subscriptions/)).

- Authorization: Listening does not automatically invoke the resource read
  handler or reuse its authorization check. A multi-tenant server that publishes
  sensitive URI changes must gate `subscriptions/listen` in middleware and end
  streams when access expires
  ([Python subscription authorization](https://py.sdk.modelcontextprotocol.io/handlers/subscriptions/#deciding-who-may-watch)).

- Replicas: The default `SubscriptionBus` is in-process. A multi-process or
  multi-replica deployment must implement the two-method bus over shared pub/sub
  so an event published on one replica reaches streams pinned to another
  ([Python deployment guide](https://py.sdk.modelcontextprotocol.io/run/deploy/#change-notifications-across-replicas)).

Adoption is worthwhile for dynamic tool/prompt catalogs or resources where
clients need fresher data than a practical polling interval provides. It is low
value for static catalogs, and it does not remove the operational cost of a
long-lived stream. Cache hints can be the simpler alternative when bounded
staleness is acceptable.

## Cache hints

### Predecessor behavior

MCP 2025 list and resource-read results had no standard freshness or sharing
metadata. A client either fetched on demand, used its own uncoordinated caching
policy, or relied on change notifications. SEP-2549 identifies the missing
freshness signal and the notification/SSE complexity as the reason for the new
fields
([SEP-2549 motivation](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2549-TTL-for-list-results.md#motivation)).
Python SDK 1.x `ClientSession` methods sent `resources/list`, `resources/read`,
and `tools/list` requests directly; its tool cache stored output schemas for
validation, not list responses
([v1 client source](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/src/mcp/client/session.py#L264-L332),
[v1 `list_tools`](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/src/mcp/client/session.py#L485-L514)).

### What 2026 and Python 2.x enable

Cacheable results carry required `ttlMs` and `cacheScope` fields. `ttlMs` is a
non-negative, millisecond freshness hint; `cacheScope` is `private` for reuse
only within one authorization context or `public` for sharing across contexts.
Relevant notifications invalidate a still-fresh result. TTL is checked when the
result is needed, not defined as a background polling interval
([SEP-2549 semantics](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2549-TTL-for-list-results.md#semantics),
[2026 schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.json#L121-L152)).

Python 2.x applies the fields to `tools/list`, `prompts/list`, `resources/list`,
`resources/templates/list`, `resources/read`, and `server/discover`. Its
high-level `Client` has an enabled-by-default response cache, while servers
default to `ttlMs: 0, cacheScope: "private"`, which is valid but produces no
cache hits. Pre-2026 peers do not see the fields and remain uncached by default
([Python caching guide](https://py.sdk.modelcontextprotocol.io/client/caching/)).

This is a genuinely new cross-implementation contract and SDK facility. It is
not a new theoretical ability: an application could always cache responses, but
the server could not standardly communicate freshness or whether cross-user
reuse was safe.

### Limits and server work

- Policy choice: The server does not cache anything. To gain a benefit, the
  application must choose truthful positive TTLs and scopes with
  `cache_hints=`, or set fields per low-level result. `public` is a promise that
  every authorization context receives identical data; it is not access control.

- Staleness and revocation: TTL is advisory, and data may change before expiry.
  A relevant notification should invalidate it, but delivery and invalidation
  can race. Permission-filtered or revocation-sensitive results should remain
  `private` and use `ttlMs: 0` or a deliberately short TTL unless the deployment
  has a reliable invalidation path.

- Pagination and Python client boundaries: The protocol has no cross-page
  consistency guarantee and requires one `cacheScope` across a paginated list.
  Python's built-in cache only stores cursor-less high-level calls; it does not
  cache continuation pages or multi-round-trip reads, perform background
  refresh, or coalesce concurrent misses, and it caps TTL at 24 hours
  ([SEP-2549 pagination](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2549-TTL-for-list-results.md#interaction-with-pagination),
  [Python cache limits](https://py.sdk.modelcontextprotocol.io/client/caching/#what-the-cache-never-does)).

- Stable serialization: The 2026 changelog says servers should return
  `tools/list` in deterministic order so response caching also stabilizes
  upstream LLM prompt caches
  ([2026 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).

Adoption is worthwhile when list/read calls are repeated, remote latency or
upstream work is meaningful, results have an honest stability window, and the
authorization partition is clear. Leave the conservative defaults when results
are cheap, highly dynamic, permission-filtered with immediate revocation
requirements, or clients are unlikely to reuse them.

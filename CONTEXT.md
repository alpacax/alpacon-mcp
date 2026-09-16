# Alpacon MCP server

This glossary defines the project-specific language used to describe the server and its protocol migrations.

## Language

**MCP 2026-07-28 migration**:
The coordinated adoption of MCP protocol revision `2026-07-28` and the official Python `mcp` SDK 2.x line. The protocol keeps date-based versions; `2.x` identifies only the SDK.
_Avoid_: MCP v2, MCP 2.0 when referring to the protocol

**Alpacon API**:
The upstream HTTP API that this server calls to access Alpacon services. Its contract is outside the MCP protocol migration boundary.
_Avoid_: MCP API, MCP surface

**MCP surface**:
The tools, resources, prompts, metadata, and protocol behavior that this server exposes to MCP clients. The `2026-07-28` migration may change this surface without changing the Alpacon API.
_Avoid_: Alpacon API

**Legacy MCP client**:
An MCP client that negotiates a 2025-era protocol revision instead of `2026-07-28`. The term describes protocol behavior, not the age of the client application.
_Avoid_: Old client

**Client ID Metadata Document (CIMD)**:
An HTTPS document whose URL acts as an OAuth `client_id` and whose contents describe the client. An authorization server fetches and validates the document instead of assigning an ID through runtime registration.
_Avoid_: Dynamic Client Registration, DCR

**Dynamic Client Registration (DCR)**:
The compatibility mechanism in which an OAuth client sends its metadata to a registration endpoint and receives a client ID at runtime.
_Avoid_: CIMD

**OAuth proxy**:
The authorization-server adapter embedded in this MCP server. It exposes OAuth endpoints, forwards authorization and token operations to Auth0, and maps MCP clients to one configured Auth0 client ID.
_Avoid_: Auth0 authorization server, direct Auth0 authorization

**Direct Auth0 authorization**:
The architecture in which the MCP server acts only as a resource server and advertises Auth0 as its authorization server. Auth0 owns client registration, login, consent, and token issuance.
_Avoid_: OAuth proxy

**Multi Round-Trip Request (MRTR)**:
The MCP interaction pattern in which a server returns an input-required result and the client retries the original request with the resolved input.
_Avoid_: Server callback, approval request

**MCP subscription**:
A client request to receive a stream of selected MCP change events from the server.
_Avoid_: SSE transport, Alpacon event subscription

**Alpacon event subscription**:
A persistent Alpacon record that routes selected events to a notification channel. It is not a live MCP client stream.
_Avoid_: MCP subscription

**Command purpose demand**:
A verification-gate request for an agent to explain a held command before execution continues. It is not a human approval decision.
_Avoid_: Approval request

**Initial-login MFA**:
An MFA challenge performed while establishing a new Auth0 login session.
_Avoid_: Step-up MFA, reauthentication

**Step-up MFA**:
A fresh MFA challenge required for a sensitive operation after the user already has an authenticated session.
_Avoid_: Initial-login MFA, password reauthentication

**MFA presence proof**:
A record that a human completed an MFA challenge for the client instance that requested it.
_Avoid_: Authenticated principal type, person-wide MFA state

**Client instance**:
A distinguishable browser, CLI installation, or other requester that starts an MFA challenge and owns the resulting presence proof.
_Avoid_: OAuth client, Work Session, user

**Declared action class**:
The ordinary or sensitive classification assigned to an action before a request is evaluated. It determines which presence freshness window applies.
_Avoid_: AI risk band, client-derived tier

**Presence freshness window**:
The server-resolved maximum age of an MFA presence proof for a declared action class.
_Avoid_: Session lifetime, client-computed timeout

**MCP resource token**:
An access token issued specifically for the Alpacon MCP server as an OAuth resource. The server validates it at the MCP boundary and must not forward it to another API.
_Avoid_: Alpacon API token

**Alpacon API token**:
An access token issued for the upstream Alpacon API and used by this server when calling that API.
_Avoid_: MCP resource token

**On-Behalf-Of (OBO) exchange**:
An OAuth token exchange in which a confidential middle tier obtains a downstream access token that represents the user without forwarding the incoming token.
_Avoid_: Token forwarding, client credentials

**Custom Token Exchange (CTE)**:
An Auth0 extension grant whose subject-token validation and token-issuance rules are defined by trusted tenant code.
_Avoid_: Dynamic Client Registration, refresh token exchange

**Cache hint**:
Response metadata that tells an MCP client whether and how long it may reuse a result. It does not enable a server-side response cache.
_Avoid_: Server cache

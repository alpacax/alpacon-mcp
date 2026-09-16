# Auth0 and MCP CIMD research

Research date: 2026-09-15

## Conclusion

Auth0 now natively supports Client ID Metadata Documents (CIMD). A tenant can advertise `client_id_metadata_document_supported: true`, fetch and validate a metadata URL, register it as an external client ID, and later accept that URL as `client_id` during authorization and token issuance. This is **manual CIMD registration**, not just-in-time registration: a tenant administrator must first import the URL through the Dashboard or the Auth0 Management API. Auth0 resolves an authorization-time URL against the stored client record; its documentation does not promise that an unknown URL is fetched or registered on first use. [Auth0 CIMD guide](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd)

The recommended target is to make Auth0 the authorization server discovered by the MCP resource server and use Auth0's native manual CIMD support for approved production clients. Keep the repository's current OAuth proxy and DCR-shaped shared-client adapter only as a transition path. Do not add the CIMD discovery flag to the current proxy until the proxy stops replacing every external `client_id` with one configured Auth0 client ID.

## Evidence: native Auth0 support

Auth0's documented native flow is:

1. Enable Client ID Metadata Document Registration in tenant settings. The Management API field is `client_id_metadata_document_supported`, defaults to `false`, and is marked Early Access (EA). When enabled, Auth0 advertises support in authorization-server metadata. [Auth0 tenant settings API](https://auth0.com/docs/api/management/v2/tenants/patch-settings)
2. A tenant administrator imports a CIMD URL in the Dashboard, or calls `POST /api/v2/clients/cimd/preview` and then `POST /api/v2/clients/cimd/register` with `external_client_id` set to the URL. Registration is idempotent; create requires `create:clients`, and update requires `update:clients`. [Preview endpoint](https://auth0.com/docs/api/management/v2/clients/post-clients-cimd-preview) [Register endpoint](https://auth0.com/docs/api/management/v2/clients/post-clients-cimd-register)
3. Auth0 fetches, validates, maps, and persists the document. At authorization time the client sends the same URL as `client_id`; Auth0 resolves it to the stored record. The access token's client ID is the URL. Metadata refresh is an explicit Dashboard/API operation, not automatic synchronization on every authorization request. [Auth0 CIMD guide](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd)

This satisfies the MCP client-side discovery contract. Python SDK 2.2's `OAuthClientProvider(..., client_metadata_url=url)` uses the URL directly and skips DCR when authorization-server metadata contains `client_id_metadata_document_supported: true`; it falls back to DCR when the flag or URL is absent. Persisted client information takes priority over either mechanism. [Python SDK OAuth client guide](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/)

The important qualification is manual registration. MCP says an authorization server supporting CIMD **should** fetch a metadata document when it encounters a URL-formatted client ID, while Auth0 documents an administrator-controlled import followed by database lookup. Therefore:

- Evidence: Auth0 accepts a CIMD URL as `client_id` after the URL has been imported.
- Inference: An unregistered URL will fail as an unknown client rather than being fetched just in time. This follows Auth0's documented registration and resolution sequence, but the error for that exact case is not documented.
- Consequence: Enabling the discovery flag is safe only when approved client URLs have an onboarding path. Otherwise a conforming MCP client will skip DCR, send its URL, and fail at authorization. [MCP client registration requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)

## Discovery and endpoints

The clean direct-Auth0 layout separates the resource-server and authorization-server roles and their discovery documents. The SDK publishes the following shape at the RFC 9728 protected-resource path:

```json
{
  "resource": "https://mcp.example.com/mcp",
  "authorization_servers": ["https://login.example.com/"],
  "scopes_supported": ["..."],
  "bearer_methods_supported": ["header"]
}
```

`MCPServer(auth=AuthSettings(...), token_verifier=...)` publishes this document and the `WWW-Authenticate` pointer automatically. The MCP server remains a resource server; it should not implement login, consent, registration, or token issuance. [Python SDK authorization guide](https://py.sdk.modelcontextprotocol.io/run/authorization/)

The client then fetches Auth0 authorization-server metadata from `https://login.example.com/.well-known/oauth-authorization-server` or its OIDC discovery fallback. Relevant fields are:

```json
{
  "issuer": "https://login.example.com/",
  "authorization_endpoint": "https://login.example.com/authorize",
  "token_endpoint": "https://login.example.com/oauth/token",
  "jwks_uri": "https://login.example.com/.well-known/jwks.json",
  "registration_endpoint": "https://login.example.com/oidc/register",
  "client_id_metadata_document_supported": true,
  "code_challenge_methods_supported": ["S256"]
}
```

Auth0's OIDC discovery documentation lists `/authorize`, `/oauth/token`, `/.well-known/jwks.json`, and `/oidc/register`. The CIMD tenant toggle controls the CIMD capability field. [Auth0 OIDC discovery example](https://auth0.com/docs/get-started/applications/configure-applications-with-oidc-discovery) [Auth0 tenant settings](https://auth0.com/docs/get-started/tenant-settings)

Auth0's discovery example includes `registration_endpoint`, while its DCR guide says DCR is disabled by default. The documentation does not state whether disabling DCR removes the metadata field. This must be checked against the target tenant: if the field remains while the endpoint refuses registration, an MCP client without a metadata URL or pre-registered information can select DCR and fail. [Auth0 DCR guide](https://auth0.com/docs/get-started/applications/dynamic-client-registration)

Use one canonical Auth0 hostname. Auth0 metadata reflects the hostname used to fetch it, and tokens use the domain used for the token request as `iss`. MCP clients compare issuer identifiers exactly. If a custom domain is chosen, authorization, token, JWKS, discovery, the SDK `issuer_url`, and this repository's JWT verifier must all agree on that domain. [Auth0 custom-domain behavior](https://auth0.com/docs/customize/custom-domains) [MCP authorization requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

MCP clients always send the RFC 8707 `resource` parameter to authorization and token endpoints. Auth0 uses `audience` by default; set the tenant's `resource_parameter_profile` to `compatibility` and use the canonical MCP URL as the Auth0 API identifier so Auth0 can bind the token to the requested resource when `audience` is absent. If both are present, Auth0 gives `audience` precedence. [Auth0 resource-parameter profile](https://auth0.com/ai/docs/mcp/guides/resource-param-compatibility-profile)

## Validation and security constraints

MCP requires an HTTPS client ID URL with a non-root path, an exact match between the URL and the document's `client_id`, valid JSON with required client metadata, and exact redirect-URI validation. An authorization server that fetches arbitrary client URLs must mitigate SSRF, respect cache policy, and address localhost redirect impersonation. [MCP authorization security requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)

Auth0 applies stricter native rules:

- URL: HTTPS, non-root path, at most 120 bytes, no localhost host, credentials, query, fragment, dot segments, whitespace, or port 0.
- Fetching: No HTTP redirects; a 5 KB limit for the CIMD and 12 KB for a referenced JWKS.
- Document: `client_id` and `client_name` are required. `grant_types` must contain `authorization_code` or `refresh_token`; other grants are filtered. `application_type` is `native` or `web`. Redirect URIs must be unique and HTTPS, with loopback exceptions for native clients.
- Authentication: Public clients use `token_endpoint_auth_method: "none"` with PKCE. Confidential CIMD clients may use only `private_key_jwt`; `jwks_uri` must be HTTPS and same-origin with the CIMD, inline JWKS and private key material are rejected, and rotated keys need a new `kid`.
- Client class: CIMD creates strict third-party applications. Symmetric client-secret methods and permissive third-party mode are unavailable. Active Auth0 Rules make CIMD login fail; Rules must be migrated to Actions.

These constraints and the full field mapping are documented in the [Auth0 CIMD guide](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd).

After registration, configure explicit client grants for the MCP API and make the required login connections domain-level. Auth0 third-party clients cannot access an API without a suitable client grant/default permission and can authenticate only through domain-level connections. [Auth0 manual CIMD setup](https://auth0.com/ai/docs/mcp/guides/registering-your-mcp-client-application/manual-cimd-registration)

## Availability and tenant constraints

- Auth for MCP overall is listed as included across current Auth0 plans, but `client_id_metadata_document_supported` is still labeled EA in the Management API. EA features may be restricted to selected subscribers, regions, or tenants and may receive minor changes before GA. Confirm the toggle and Management API endpoints in every target tenant; do not infer availability from the overall Auth for MCP SKU. [Auth0 pricing](https://auth0.com/pricing) [Auth0 release stages](https://auth0.com/docs/troubleshoot/product-lifecycle/product-release-stages)
- Public CIMD clients using PKCE and `token_endpoint_auth_method: "none"` have no stated Enterprise requirement. `private_key_jwt` for confidential CIMD clients is explicitly Enterprise-only.
- Auth0 currently states that third-party applications, including CIMD clients, do not support Auth0 Organizations. If Alpacon's workspace claim production depends on an Auth0 Organization login context, this blocks direct native CIMD until a tenant proof confirms otherwise or Auth0 adds that support. The repository consumes a namespaced `workspaces` claim, but official Auth0 documentation cannot establish how the deployed Action constructs it; this point is a required integration test, not a proven failure. [Auth0 CIMD limitations](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd)
- CIMD metadata refresh is manual. Operational ownership must include re-previewing and saving changes, client grant maintenance, connection exposure, and key rotation.

## Why Auth0 extensions are not a substitute

No documented Auth0 extension is needed to add CIMD, because Auth0 has a native implementation. If the native toggle is unavailable in a tenant, the other named mechanisms do not supply an equivalent authorization-server feature:

- Actions: Auth0 Actions run at specific user-login, user-registration, password, M2M token, and custom-token-exchange triggers. There is no trigger for authorization-server discovery, unknown-client lookup, or client registration. A post-login Action runs after client resolution and authentication, so it cannot make an unknown metadata URL into a valid `client_id`. This is an inference from Auth0's complete documented trigger list. [Auth0 Actions triggers](https://auth0.com/docs/customize/actions/explore-triggers)
- Custom domains: A custom domain is a verified CNAME/mask for Auth0 services. It changes endpoint hostnames, metadata URLs, and token issuer values; it does not provide path routing to customer code or a hook to add metadata fields and client resolution. This is an inference from the documented feature boundary. [Auth0 custom domains](https://auth0.com/docs/customize/custom-domains)
- Custom database connections: These connect Auth0 to an external **user** store and run scripts for login, signup, password, verification, and user deletion. They do not replace Auth0's OAuth application/client registry. [Auth0 custom databases](https://auth0.com/docs/authenticate/database-connections/custom-db)
- Management API: This is the supported programmatic extension point. `/api/v2/clients/cimd/preview` and `/api/v2/clients/cimd/register` perform Auth0's validation and persistence. Call them from an authenticated administrative onboarding workflow or CI process, not from a public authorization request.
- Custom proxy: A proxy can implement CIMD itself, but then it is the authorization server from the MCP client's perspective and owns URL fetching, SSRF protection, validation, caching, redirect binding, consent identity, client isolation, audit, and token-client binding. The Python SDK deliberately supplies only the resource-server half and advises new servers not to embed an authorization server. [Python SDK authorization boundary](https://py.sdk.modelcontextprotocol.io/run/authorization/)

## Current repository behavior

Local code is the primary evidence for this section:

- [`server.py`](../server.py) sets the MCP origin as `AuthSettings.issuer_url`, so protected-resource discovery sends clients back to the repository's OAuth proxy rather than Auth0.
- [`utils/oauth.py`](../utils/oauth.py) publishes the proxy issuer plus `/oauth/authorize`, `/oauth/token`, and `/oauth/register`, advertises DCR, and omits `client_id_metadata_document_supported`.
- `/oauth/register` validates selected DCR metadata but returns the same preconfigured Auth0 `client_id` to every caller. `/oauth/authorize` overwrites any incoming client ID with that configured ID. `/oauth/token` rejects a different client ID, injects the configured secret, and forwards to Auth0. The proxy also relays callbacks, seals codes/refresh tokens, assigns device IDs, and implements the repository's MFA behavior.

Therefore the current proxy is a compatibility adapter around one confidential Auth0 application, not a CIMD authorization server and not a general Auth0 DCR integration. Merely adding `"client_id_metadata_document_supported": true` would make Python SDK 2.2 skip `/oauth/register` and send its metadata URL to `/oauth/authorize`; the proxy would discard it, and `/oauth/token` would reject it if the client sent it. The existing shared-client design and native URL client IDs are mutually exclusive without a substantial OAuth redesign.

The source comment that Auth0 DCR is unavailable on non-Enterprise plans is no longer supported by current Auth0 documentation. Auth0 documents DCR as disabled by default, enabled by `flags.enable_dynamic_client_registration`, and available at unauthenticated `POST /oidc/register`; its Free-plan rate table includes the endpoint. Verify the actual target tenant, but do not use the old plan assumption as an architectural premise. [Auth0 DCR guide](https://auth0.com/docs/get-started/applications/dynamic-client-registration) [Auth0 Free-plan limits](https://auth0.com/docs/troubleshoot/customer-support/operational-policies/rate-limit-policy/rate-limit-configurations/free-public)

## Recommended architecture

### Target: direct Auth0 authorization server with manual CIMD

1. Confirm the CIMD EA toggle and Management API endpoints in a non-production tenant. Choose the canonical Auth0 tenant or custom domain and use it consistently.
2. Configure the Auth0 MCP API identifier as the canonical public MCP resource URL and enable `resource_parameter_profile: "compatibility"`.
3. Configure `MCPServer` as a resource server with `issuer_url` set to the Auth0 issuer and remove the proxy issuer from Protected Resource Metadata. Keep JWT audience, issuer, and JWKS validation in the repository's verifier.
4. Enable `client_id_metadata_document_supported`. For each approved production MCP client, preview and register its stable CIMD URL through an administrative workflow, then grant only the required API scopes and login connections.
5. Prefer public CIMD clients with PKCE and `token_endpoint_auth_method: "none"`. Use Enterprise `private_key_jwt` only when a confidential client and its key-rotation operations are justified.
6. Prove the complete flow with Python SDK 2.2: discovery, URL client ID, S256 PKCE, `resource` on authorization and token requests, refresh, exact `iss`, MFA Action behavior, workspace claim contents, consent, and logout/revocation. Test a custom domain separately if used.
7. Retire the local authorization, token, callback, and registration proxy routes only after the direct flow preserves the required MFA and workspace semantics.

This target removes the shared client secret and callback relay from the MCP server, gives Auth0 per-client identity and consent/audit records, and uses the registration implementation that Auth0 maintains. Auth0 itself recommends manual CIMD for production MCP deployments. [Auth0 MCP client-registration guide](https://auth0.com/ai/docs/mcp/guides/registering-your-mcp-client-application)

### Transition: retain the proxy without claiming CIMD

Keep the current proxy metadata without the CIMD flag. Retain `/oauth/register` as the DCR fallback for unmodified MCP clients and add explicit pre-registration for known clients where client configuration permits it. MCP's selection order is pre-registered information, CIMD, DCR, then user-supplied credentials; Python SDK storage can be pre-populated with client information and stored information wins over dynamic paths. [MCP registration order](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration) [Python SDK OAuth client guide](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/)

Treat this as migration compatibility, because DCR is deprecated in MCP `2026-07-28` and the proxy collapses all registrations to one Auth0 identity. Preserve its current redirect allowlist, PKCE, signed state, exact issuer binding, bounded request bodies, sealed grants, and MFA tests while it remains exposed.

### Alternative: native Auth0 DCR fallback

If automatic onboarding is a hard requirement and the tenant supports it, Auth0 can expose open DCR at `POST /oidc/register`. It is disabled by default; when enabled, anyone can create a third-party application without a token. New DCR clients receive `tpc_` IDs, require PKCE, support only authorization-code/refresh grants, use domain-level connections, and need explicit/default API permissions. Auth0 provides a Tenant ACL scope for the endpoint and limits it to five requests per second per tenant. [Auth0 DCR guide](https://auth0.com/docs/get-started/applications/dynamic-client-registration)

Use strict DCR security mode, least-privilege default API permissions, ACL/rate monitoring, and lifecycle cleanup. Advertise both CIMD and `registration_endpoint` only when both actually work: Python SDK clients with a metadata URL prefer CIMD, while clients without one use DCR. Do not enable open Auth0 DCR merely to reproduce the current shared-ID adapter; its tenant client-sprawl and default-grant consequences are materially different.

### Not recommended: CIMD-aware proxy

Retaining the proxy while adding true CIMD would require per-client registration, preserving the URL client ID through signed state, forwarding it to Auth0 on authorization and token requests, using public-client token authentication or per-client keys, binding refresh tokens to the same external client, and reconciling the proxy callback with every client's registered redirect URIs. It would also have to reject unapproved URLs or safely invoke the privileged Management API registration flow.

This is possible application engineering, not an Auth0 Action or custom-domain feature. It keeps the MCP server on the authorization-server security boundary and duplicates native Auth0 behavior. Choose it only if the current callback relay and device-specific MFA semantics cannot be moved to Auth0-native configuration, and document that exception separately.

## Decision gates

Before selecting the target architecture, obtain evidence for these questions in the actual tenant:

- Does `GET /api/v2/tenants/settings` expose the EA CIMD field, and does the chosen discovery hostname return `client_id_metadata_document_supported: true` after enablement?
- Can one approved public CIMD client complete authorization and refresh using the canonical MCP `resource`, without the proxy injecting `audience`?
- Does the current Auth0 Action still emit the complete `workspaces` claim for a strict third-party CIMD client, and does any part of that flow require Auth0 Organizations?
- Are active Rules present? If so, migrate them to Actions before a CIMD client is used.
- Does the client metadata contain only Auth0-valid callbacks and, for a native client, the expected loopback URI form?
- For clients without a metadata URL, will the product supply pre-registered information, retain the proxy DCR adapter, or intentionally enable Auth0 open DCR?
- Do JWT `iss`, JWKS lookup, audience/resource validation, and the advertised authorization-server issuer use the same canonical domain and identifiers?

Passing these gates supports the direct-Auth0 target. Failure of the EA availability or workspace/MFA gate supports retaining the proxy temporarily without advertising CIMD.

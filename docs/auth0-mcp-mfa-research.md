# Auth0 MFA with direct MCP authorization research

Research date: 2026-09-15

## Executive answer

Direct Auth0 authorization can support initial-login MFA and MCP's scope-based runtime step-up for manually registered CIMD clients and DCR clients. It cannot preserve the current implementation unchanged. The viable direct design is a one-stage Authorization Code + PKCE flow in Universal Login: the MCP server returns an RFC 6750 `403 insufficient_scope` challenge, the client requests a dedicated high-assurance API scope, and a post-login Action challenges MFA before Auth0 issues the new API access token.

The present two-stage flow cannot run under Auth0's strict third-party profile. Manual CIMD clients are third-party applications, DCR creates third-party applications, and strict third-party user flows cannot access Auth0 system APIs, including the MFA API. They also cannot receive OIDC scopes or ID tokens. The current first stage—Auth0 MFA API audience plus `enroll read:authenticators`—must therefore be removed or kept behind the existing first-party proxy. [Auth0 CIMD guide](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd), [third-party security controls](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls), [Auth0 DCR guide](https://auth0.com/docs/get-started/applications/dynamic-client-registration)

Per-grant MFA state can be rebuilt directly in Auth0, but only with application code and, for durable refresh-token-family state, Auth0 Refresh Token Metadata. That feature is currently Early Access and Enterprise-only. Without it, the secure choices are to re-prompt after an access-token refresh loses the MFA timestamp or retain the proxy. [Auth0 Refresh Token Metadata](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-metadata)

## Capability assessment

| Capability | Direct Auth0 strict CIMD/DCR client | Required work |
|---|---|---|
| Initial-login MFA | Supported | Enable factors and `Always`, Adaptive MFA, or a post-login Action |
| Tenant-policy MFA | Supported | `Always` is tenant-wide; Adaptive MFA requires Enterprise plus the Adaptive MFA add-on |
| Built-in enrollment in login | Supported | Use Universal Login; an unenrolled user is prompted to enroll |
| Custom enrollment/challenge order | Supported | Enable `Customize MFA Factors using Actions`; use `enrollWith*` and `challengeWith*` in post-login Actions |
| MCP runtime step-up | Supported with code | Emit `403 insufficient_scope`; define an Auth0 API scope; challenge it in an Action |
| `acr_values`-driven step-up | Auth0 supports it; Python SDK 2.2 does not expose it | Extend the client authorization URL builder or prefer scope-driven step-up |
| `prompt` / `max_age` freshness | Auth0 supports the parameters; not MFA by themselves | Custom client code and `auth_time` validation; not the recommended MCP path |
| Standard `amr` / `acr` proof | Not usable for strict clients | Strict third-party apps do not support ID tokens; use an access-token scope and optional namespaced custom claim |
| Auth0 MFA API audience | Not supported | Keep the first-party proxy or replace the two-stage flow |
| MFA inside refresh-token exchange | Not supported | Explicitly bypass all interactive MFA commands during refresh |
| Durable per-grant MFA timestamp | Conditional | Enterprise EA Refresh Token Metadata plus Actions, or an external proxy/state service |
| Current sealed code/refresh-token device binding | Not preserved | Auth0 owns the direct code/token flow; redesign around refresh-token-family metadata |
| Auth0 Organizations with CIMD | Do not rely on it | The CIMD guide says Organizations are unsupported; see the documentation conflict below |
| RFC 9470 challenge handling | Not implemented by the MCP core/Python provider | Use MCP's RFC 6750 scope challenge instead |

## Registration profile and login surface

**Evidence.** Manual CIMD is an admin import, not on-demand registration. Auth0 fetches and persists the document, then accepts the HTTPS metadata URL as `client_id`. The tenant flag `client_id_metadata_document_supported` defaults to `false` and is marked Early Access. Public CIMD clients use `token_endpoint_auth_method=none` with PKCE; confidential CIMD clients require `private_key_jwt`, which is Enterprise-only. [Auth0 CIMD guide](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd), [Auth0 tenant settings API](https://auth0.com/docs/api/management/v2/tenants/patch-settings)

**Evidence.** Auth0 DCR is disabled by default. When enabled, open `POST /oidc/register` creates strict third-party clients; authorization-code clients require PKCE and API access requires default third-party client grants because DCR cannot configure per-client grants during registration. [Auth0 DCR guide](https://auth0.com/docs/get-started/applications/dynamic-client-registration), [configure third-party applications](https://auth0.com/docs/get-started/applications/third-party-applications/configure-third-party-applications)

**Evidence.** Strict third-party applications require explicit API client grants, domain-level connections, end-user consent, and Universal Login. Classic Login, Rules, Auth0 system APIs in user flows, OIDC scopes, and ID tokens are unsupported. Actions are the supported extensibility replacement for Rules. [Auth0 third-party applications](https://auth0.com/docs/get-started/applications/third-party-applications), [third-party security controls](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls)

**Evidence.** Python SDK 2.2 uses CIMD only when both `client_metadata_url` is supplied and authorization-server metadata advertises `client_id_metadata_document_supported: true`; otherwise it uses DCR. A stored client registration wins over both. This is capability selection, not a recovery path: if Auth0 advertises CIMD but that URL was not manually imported into the tenant, an authorization failure does not make the provider retry with DCR. [Python SDK OAuth client guide](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/), [Python SDK 2.2 OAuth provider](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/auth/oauth2.py)

**Inference.** A rollout must choose one of these operational models per tenant:

- Managed CIMD allowlist: Admin-import every supported client metadata URL and grant its API scopes.
- Open DCR: Do not advertise CIMD to clients that cannot be pre-imported, and narrowly configure default third-party API grants plus a Tenant ACL.
- Mixed: Advertise CIMD for known clients and accept that a client which supplies an unregistered metadata URL fails; DCR remains useful only for clients that do not supply a metadata URL.

## Initial MFA, tenant policy, and enrollment

**Evidence.** Auth0's tenant policies are `Never`, `Always`, and Adaptive MFA. `Always` prompts on every login; Adaptive MFA prompts based on Auth0 risk and requires an Enterprise plan with the Adaptive MFA add-on. At least one independent factor must be enabled. [Enable MFA](https://auth0.com/docs/secure/multi-factor-authentication/enable-mfa), [Adaptive MFA](https://auth0.com/docs/secure/multi-factor-authentication/adaptive-mfa)

**Evidence.** Universal Login has a built-in MFA flow: an unenrolled user is asked to enroll, while an enrolled user is challenged. Custom selection and enrollment require Universal Login, the tenant's `Customize MFA Factors using Actions` toggle, and post-login `enrollWith`, `enrollWithAny`, `challengeWith`, or `challengeWithAny`. A user generally needs an existing enrollment before a `challengeWith*` command; enrollment can be driven by `enrollWith*`, the built-in flow, or an administrator using the Management API. [Customize MFA pages](https://auth0.com/docs/secure/multi-factor-authentication/customize-mfa), [Customize MFA selection](https://auth0.com/docs/secure/multi-factor-authentication/customize-mfa/customize-mfa-selection-universal-login)

**Inference.** Initial MFA works for a strict CIMD/DCR client because its supported authorization-code flow uses Universal Login and post-login Actions. If policy bypass must fail closed, Auth0 recommends `Always` or Adaptive MFA as the fallback beneath custom Actions. If product requirements intentionally allow password-only initial login and require MFA only for sensitive tools, `Never` plus a carefully tested scope-triggered Action preserves that distinction but removes the tenant-policy safety net.

## Per-operation step-up after Alpacon rejects a token

### MCP and Python SDK behavior

**Evidence.** MCP 2026-07-28 distinguishes invalid authentication from missing permission. An invalid or expired token receives `401`; a runtime scope shortfall should receive `403` with `WWW-Authenticate: Bearer error="insufficient_scope", scope="...", resource_metadata="..."`. A user-facing client should union the challenged scopes with previously requested scopes, reauthorize, and retry only a few times. [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

**Evidence.** Python SDK 2.2 `OAuthClientProvider` implements that consumer behavior. It treats any `401` as a full OAuth restart. It treats only a `403` carrying `error="insufficient_scope"` as step-up, unions the prior and challenged scopes, runs Authorization Code + PKCE again, stores the new tokens, and retries the original request. Its authorization request contains `response_type`, `client_id`, redirect URI, state, PKCE, `resource`, and `scope`; it does not expose arbitrary `acr_values` or `max_age` parameters. It adds only `prompt=consent` when `offline_access` is requested. [Python SDK 2.2 OAuth provider](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/auth/oauth2.py), [v2.2.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.2.0)

**Evidence.** The Python SDK 2.2 server middleware checks only a static `required_scopes` list. Its `403` response currently omits the challenged `scope` parameter even though the OAuth client can consume one. It also cannot infer that an Alpacon API error means MFA is required. Dynamic per-tool translation remains application middleware. [Python SDK 2.2 bearer middleware](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/server/auth/middleware/bearer_auth.py)

**Repository observation.** `utils/auth_error_middleware.py` currently maps downstream MFA failure to `401 invalid_token` and adds `openid profile email offline_access mfa`. Under the new protocol this should become a bounded `403 insufficient_scope` challenge that includes only the resource scopes required for the operation and the Protected Resource Metadata URL. Strict third-party clients cannot use the three OIDC scopes, while the MCP specification says a resource server should not advertise `offline_access` as a resource requirement; the client may request it separately when the authorization server advertises it. The existing custom middleware remains necessary after the SDK upgrade. [MCP refresh-token guidance](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization#refresh-tokens)

### Auth0 action design

**Evidence.** Auth0's documented API step-up pattern matches MCP's scope mechanism: define a high-value API scope, deny an access token that lacks it, request the additional scope, and use a post-login Action to call MFA when `event.transaction.requested_scopes` contains that scope. Auth0 issues the new access token only after the MFA challenge succeeds. [Auth0 API step-up guide](https://auth0.com/docs/secure/multi-factor-authentication/step-up-authentication/configure-step-up-authentication-for-apis)

**Inference.** `mfa` has no built-in meaning at Auth0. It can be retained as a custom scope on the Alpacon/MCP Auth0 API, but a namespaced name such as `alpacon:mfa` makes its purpose clearer. The Auth0 API client grant must authorize it: a per-client grant for a manually imported CIMD client, or a default third-party user grant for DCR. The Action, not the scope name, forces MFA.

**Recommended flow.** On a sensitive tool call:

1. The server detects an expired or absent `completed_mfa_methods` timestamp, either from an Alpacon response or by consuming the declared action class and presence freshness window resolved by Alpacon. The MCP layer must not reclassify the action or derive the window from raw settings.
2. It returns `403 insufficient_scope` with the base operation scopes plus `alpacon:mfa` and `resource_metadata`.
3. An MCP client that implements 2026-07-28 step-up requests the union of old and new scopes.
4. Auth0 Universal Login runs a post-login Action that detects `alpacon:mfa` and invokes `challengeWith*` with remembered-browser bypass disabled where a fresh factor is required.
5. A following Action observes the completed method and adds a namespaced `completed_mfa_methods` timestamp to the API access token.
6. The client retries the tool call with the new token.

Auth0 documents that `challengeWith*` pauses the flow and that the next Action sees the completed MFA method in `event.authentication.methods`; this avoids the first-login gap of the older `api.multifactor.enable()` API. [Customize MFA selection](https://auth0.com/docs/secure/multi-factor-authentication/customize-mfa/customize-mfa-selection-universal-login)

## `acr`, `amr`, `prompt`, and RFC 9470

**Evidence.** Auth0 accepts `acr_values`, `max_age`, and `prompt` for strict third-party `/authorize` requests. Its web-app step-up guide uses the multi-factor ACR value in an authorization request and an Action to force MFA. It then validates `amr: ["mfa"]` in the ID token. Auth0 also warns that `amr` is absent from ID tokens created by silent authentication or refresh-token exchange. [Third-party parameter controls](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls), [Auth0 web-app step-up](https://auth0.com/docs/secure/multi-factor-authentication/step-up-authentication/configure-step-up-authentication-for-web-apps)

**Evidence.** `prompt=login` and `max_age` establish fresh primary authentication, not MFA by themselves. `max_age` requires the client to validate `auth_time`; Auth0 explicitly distinguishes reauthentication from multi-factor step-up. [Auth0 OIDC reauthentication](https://auth0.com/docs/authenticate/login/max-age-reauthentication)

**Inference.** The `acr`/`amr` web-app recipe is not suitable for the proposed direct CIMD/DCR path: strict third-party applications currently do not receive ID tokens, and Python SDK 2.2 does not add `acr_values` to its authorization URL. Scope-driven API step-up is both the supported Auth0 pattern and the interoperable MCP path.

**Evidence.** MCP 2026-07-28 lists its authorization standards and defines runtime step-up exclusively as the RFC 6750 `403 insufficient_scope` flow. Python SDK 2.2 recognizes `401` and that exact `403` error; it has no `insufficient_user_authentication` or ACR challenge path. [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), [Python SDK 2.2 OAuth provider](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/auth/oauth2.py)

**Inference.** Do not emit the RFC 9470 `insufficient_user_authentication` challenge for MCP clients today. It may be appropriate for a future negotiated extension, but current interoperable behavior is an ordinary scope challenge whose Auth0 Action maps the high-assurance scope to MFA.

## Refresh behavior and per-grant state

**Evidence.** Strict third-party applications do not support MFA during a refresh-token exchange; a refresh transaction that triggers MFA fails. Auth0's general MFA guidance therefore guards interactive commands with `event.transaction.protocol !== 'oauth2-refresh-token'`. [Third-party security controls](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls), [Auth0 refresh MFA bypass](https://auth0.com/docs/secure/multi-factor-authentication/customize-mfa#bypass-mfa-for-refresh-token-requests)

**Evidence.** Python SDK 2.2 refreshes an expired access token before retrying the MCP request. Its refresh request carries the refresh token, `client_id`, and MCP `resource`; it has no custom `device_id` field. A failed refresh clears tokens, and a later `401` starts the full authorization flow. [Python SDK 2.2 OAuth provider](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/auth/oauth2.py)

**Evidence.** Auth0 Refresh Token Metadata can store state on the refresh-token family at initial authorization, expose it to post-login Actions on later refresh exchanges, and preserve custom access-token claims through rotation. It is Early Access, Enterprise-only, limited to 25 short string entries, and is not a general secret store. [Refresh Token Metadata](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-metadata), [metadata use cases](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-metadata/use-cases)

**Inference.** Refresh Token Metadata is the closest native replacement for the proxy's `device:<id>` binding, but the target contract is the requesting client instance defined by the platform presence model:

- When the step-up authorization issues a refresh token, store a generated grant identifier, trusted `client_instance`, `client_instance_source`, method, and completion timestamp in refresh-token metadata. Add the client-bound presence proof to the access token.
- On refresh, do not challenge MFA. Read the metadata, carry it forward on the rotated refresh token, and re-add the same client-bound claims.
- Let Alpacon's single server-side resolver select the presence freshness window from the declared action class. The MCP server consumes that resolved result rather than choosing between `mfa_timeout` and `sensitive_mfa_timeout`. When stale, return another `403 insufficient_scope` and require a fresh interactive grant.

This preserves isolation by authorization grant without trusting client-supplied device state, but it is a new design that requires an Enterprise EA feature and end-to-end tenant validation. Storing the flag in user or app metadata is not equivalent: it is user/application-wide, so one MCP installation could refresh another installation's MFA state.

Without Refresh Token Metadata, fail closed. Do not copy an old MFA timestamp blindly onto refreshed tokens. Either omit the claim so the next sensitive operation prompts again, shorten the access/refresh lifetime to the accepted risk window, keep per-grant state in the proxy, or use a purpose-built server-side store with a grant-bound opaque identifier.

## Why the current two-stage and device flow are not preserved

**Repository observation.** The current proxy performs four jobs that disappear in direct Auth0 mode:

- It converts the `mfa` pseudo-scope into an Auth0 MFA API authorization at `https://{domain}/mfa/` with `enroll read:authenticators`, exchanges and discards that token, then obtains the normal Alpacon API token in a second authorization.
- It replaces every MCP client's client ID with one first-party Auth0 client ID and injects that client's secret at the token endpoint.
- It mints one device ID per authorization grant, sends it to the Auth0 Action, and seals authorization codes and refresh tokens with it.
- It re-injects the sealed device ID on refresh so the Action can restore the grant-specific MFA timestamp.

**Evidence.** The first two behaviors are incompatible with native CIMD/DCR strict clients: their own third-party identity must reach Auth0, shared-secret methods are restricted, and third-party user flows cannot access the MFA API. Direct mode also sends codes and tokens between the MCP client and Auth0, so the MCP server has no safe interception point for the current seal format. [Auth0 CIMD guide](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd), [third-party security controls](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls)

**Evidence.** MCP additionally requires the access token accepted by the MCP server to be issued specifically for that MCP resource and says the server must not accept or transit tokens for another resource. A direct Auth0 architecture therefore needs a distinct upstream Alpacon credential or a standards-based token exchange; it must not simply accept an Alpacon API audience token at the MCP boundary and forward it. [MCP token handling](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization#token-handling)

## Organizations limitation

**Evidence with a documentation conflict.** The CIMD guide explicitly says third-party applications, including CIMD clients, do not support Organizations and that support is future work. Auth0's newer generic third-party security page says Authorization Code user flows can use Organizations after organization opt-in and domain-level connection promotion, while another first-party-versus-third-party page still says user-flow support is planned. [Auth0 CIMD guide](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd), [third-party security controls](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls), [first-party and third-party applications](https://auth0.com/docs/get-started/applications/first-party-and-third-party-applications)

**Recommendation.** Treat Auth0 Organizations as unsupported for CIMD and unproven for DCR until Auth0 confirms the tenant behavior and a real strict client passes an end-to-end test. Do not make Organizations a prerequisite for workspace selection in the direct architecture. Continue deriving and authorizing Alpacon workspace membership from the Alpacon API access model.

## Safest rollout architecture

1. **Separate the migrations.** Upgrade the MCP protocol and Python SDK while retaining the current OAuth proxy for production MFA. First change the runtime signal to the 2026-07-28 `403 insufficient_scope` shape and verify actual client behavior. This avoids coupling an SDK migration to Auth0 CIMD EA, strict third-party controls, and a new MFA state model.
2. **Pilot direct Auth0 as a separate profile.** Enable the CIMD EA flag, Resource Parameter Compatibility Profile, DCR strict mode only where needed, Universal Login, domain-level connections, MFA factors, and the required API grants. Manually import each supported CIMD URL. Do not call the MFA API from the strict client.
3. **Use one-stage scope step-up.** Register `alpacon:mfa` as an API scope. Translate an Alpacon MFA denial to a bounded `403 insufficient_scope` challenge. Use one Action to enroll/challenge interactively and a later Action to record the successful method and timestamp in the API access token.
4. **Choose refresh semantics explicitly.** For Enterprise tenants willing to use EA, pilot Refresh Token Metadata as grant-local state. Otherwise keep the proxy or accept secure re-prompting after refresh; do not weaken isolation with user-global metadata.
5. **Keep resource audiences separate.** Validate the MCP resource token at the MCP boundary and establish a separate, documented way to call Alpacon upstream.
6. **Retain the proxy as fallback.** Use it for tenants that require the exact two-audience flow, device sealing, non-Enterprise durable grant state, Auth0 Organizations, or clients that do not correctly implement runtime scope step-up.

## Required proof before switching production traffic

- Discovery: Confirm Auth0 metadata advertises the intended `client_id_metadata_document_supported`, `registration_endpoint`, `acr_values_supported`, PKCE, scopes, and issuer values.
- Registration: Test one admin-imported public CIMD client and one DCR public client. Confirm that an unimported CIMD URL fails rather than silently falling back.
- Initial MFA: Test `Never`, `Always`, Adaptive MFA if licensed, enrolled users, and first-time enrollment in Universal Login.
- Runtime step-up: From a valid low-assurance access token, verify the exact `403` header, client scope union, browser challenge, new token, and one bounded retry.
- Client coverage: Test Python SDK 2.2 and every production host, including Claude clients; MCP says clients *should* reauthorize, not that every host must provide the same UX.
- Refresh: Test rotation before and after both the ordinary `mfa_timeout` and sensitive `sensitive_mfa_timeout` windows, Action refresh guards, missing metadata, revoked refresh tokens, and Action failure. No refresh path may silently renew a stale MFA timestamp.
- Action tiers: Prove that Alpacon selects the ordinary or sensitive window from the declared action class in one server-side resolver and that the MCP layer does not recompute the tier.
- Client-instance isolation: Authorize two installations of the same CIMD/DCR client, step up only one, and prove the other remains low assurance. Verify the trusted `client_instance` and `client_instance_source` on every token and exchange boundary.
- Enrollment recovery: Test no factor, lost factor, reset factor, and an Auth0 administrator-managed recovery path without granting the third-party app access to a system API.
- Organizations: Run an explicit negative/positive matrix if any tenant depends on Auth0 Organizations; do not infer support from generic third-party documentation.
- Audience separation: Prove the MCP token is audience-bound to the MCP resource and that upstream Alpacon access uses a separate authorized credential path.

## Conclusion

Direct Auth0 is viable for MFA only as a redesigned, standards-aligned scope step-up flow. Initial MFA and enrollment are native Universal Login capabilities; per-operation MFA needs a custom MCP `403` translator and Auth0 Actions; durable per-grant claims need Enterprise EA Refresh Token Metadata or external state. The exact two-stage MFA API audience and sealed device-per-grant mechanism cannot survive direct strict CIMD/DCR authorization. Keep the proxy as the production fallback until the one-stage flow, refresh isolation, client UX, and resource-audience split pass end-to-end tests.

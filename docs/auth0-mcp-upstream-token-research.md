# Auth0 MCP-to-Alpacon token research

Research date: 2026-09-15

## Executive answer

An MCP access token and an Alpacon API access token must be different tokens. MCP 2026-07-28 requires the MCP server to accept only a token issued specifically for its own canonical resource and forbids it from accepting or transiting a token for another resource. Auth0's On-Behalf-Of (OBO) Token Exchange is designed for exactly this topology: the MCP server validates Token A, whose audience is the MCP resource, then confidentially exchanges it for Token B, whose audience is the unchanged Alpacon API. The MCP client never receives Token B. [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), [Auth0 MCP OBO quickstart](https://auth0.com/ai/docs/mcp/get-started/call-your-apis-on-users-behalf)

OBO is the recommended path if the downstream token can be produced from Auth0's guaranteed delegation context plus newly calculated custom claims. It preserves `sub`, changes `aud` to the downstream API, records the MCP server and original client in `act`, preserves an Auth0 Organization `org_id`, and applies user RBAC. It does **not** document automatic copying of arbitrary workspace or `completed_mfa_methods` claims, and it returns no downstream refresh token. Therefore native OBO alone is not proven to preserve this repository's per-grant MFA timestamp/device state. [Auth0 OBO documentation](https://auth0.com/docs/secure/call-apis-on-users-behalf/on-behalf-of-token-exchange), [Auth0 OBO API](https://auth0.com/docs/api/authentication/on-behalf-of-token-exchange/get-token)

If the unchanged Alpacon API must receive the exact grant-local MFA/workspace claim derived from Token A, the viable Auth0 fallback is Custom Token Exchange (CTE) invoked by a separate first-party confidential MCP backend client. Its Action validates Token A, selects the same user, and transfers a small, allowlisted claim set into the downstream token. This is more code, lower throughput, and more security responsibility than OBO. Keeping the present broker is the final fallback, but it must become a real two-token backend-for-frontend: the client receives only an MCP-audience token, while the upstream token stays server-side.

## Standards boundary

**Evidence.** The MCP client sends `resource=<canonical MCP server URI>` during authorization and sends the resulting bearer token only to the MCP server. The server must validate that it is the intended audience; it must not accept or transit another resource's token. [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

**Consequence.** These patterns are invalid or unusable:

- Alpacon-token passthrough: An access token with `aud=https://alpacon.io/access/` cannot be the MCP bearer token.
- MCP-token passthrough: The unchanged Alpacon API must reject a token whose audience is the MCP resource.
- Multi-audience shortcut: It removes the required resource separation and should not be used to make one bearer token valid at both services.
- Client-side exchange: Auth0 OBO requires a Custom API client associated with the MCP resource and client authentication that cannot be `none`; a public CIMD/DCR Python client must not hold that credential.

The two-token path is:

```text
Python MCP client -- Token A (aud=MCP) --> MCP server
                                            |
                                            | confidential RFC 8693 exchange
                                            v
                                          Auth0
                                            |
                                            v
                        MCP server -- Token B (aud=Alpacon) --> Alpacon API
```

## Native OBO architecture

### Required Auth0 configuration

**Evidence.** Auth0's MCP guide assigns the server two roles: resource server for the MCP client and confidential client for the downstream API. The required tenant configuration is: [Auth0 MCP OBO quickstart](https://auth0.com/ai/docs/mcp/get-started/call-your-apis-on-users-behalf), [Auth0 OBO documentation](https://auth0.com/docs/secure/call-apis-on-users-behalf/on-behalf-of-token-exchange)

- MCP resource: Register the canonical MCP server URI as a separate Auth0 Custom API audience.
- MCP backend client: Create a Custom API client with `app_type: resource_server` and `resource_server_identifier` equal to the MCP audience.
- Exchange permission: Set `token_exchange.allow_any_profile_of_type` to `["on_behalf_of_token_exchange"]`.
- Downstream delegation: Create a client grant from that backend client to the existing Alpacon audience, set `subject_type: user`, and allow only required Alpacon scopes. User-delegated scopes are the intersection of requested scopes, the client grant, user RBAC, and consent where applicable. [Auth0 client grants](https://auth0.com/docs/get-started/applications/application-access-to-apis-client-grants)
- Confidential authentication: Store the client secret or assertion only in the MCP service. Auth0 permits supported client authentication methods but not `token_endpoint_auth_method=none` for OBO.

At runtime the server posts Token A to the tenant's `/oauth/token` endpoint with the RFC 8693 grant type, access-token subject/requested-token types, the existing Alpacon audience, and an optional narrowed scope. Token B has the same user `sub`, the Alpacon `aud`, the MCP backend client as `azp`/`client_id`, and an `act` chain containing the backend and original MCP client. Auth0 documents access-token caching until expiry and warns against exchanging on every API call. [Auth0 OBO API](https://auth0.com/docs/api/authentication/on-behalf-of-token-exchange/get-token)

### Compatibility with the unchanged Alpacon API

**Evidence.** OBO guarantees the same `sub`; an Organization-bound subject token also retains `org_id`, membership is revalidated, and organization RBAC is applied. OBO triggers post-login Actions with `event.transaction.protocol=oauth2-token-exchange`, so an Action can add custom claims to Token B. The documented response contains an access token but no refresh token. [Auth0 OBO documentation](https://auth0.com/docs/secure/call-apis-on-users-behalf/on-behalf-of-token-exchange), [Auth0 custom claims](https://auth0.com/docs/secure/tokens/json-web-tokens/create-custom-claims)

**Evidence.** Auth0 documents OBO for an incoming Auth0 access token and a first-party downstream API configured in the tenant. It does not document cross-tenant OBO.

**Inference.** Treat a common Auth0 tenant/issuer for the MCP and Alpacon resource servers as a rollout prerequisite; use CTE or the broker if they are intentionally in different tenants.

**Inference.** No Alpacon API code change is required if all of the following hold:

- Token B uses the existing Auth0 issuer, Alpacon audience, signing algorithm, scopes, and namespaced claim schema.
- Alpacon accepts the changed `azp`/`client_id` and ignores the additional `act` claim.
- The OBO post-login Action can calculate the required workspace list from authoritative current data.
- Token B carries trustworthy `client_instance` and `client_instance_source` claims that identify the requester whose MFA presence proof is being presented.
- The downstream API does not require a sender-constraining mechanism that the MCP server cannot present.

The changed authorized-party claim is a concrete compatibility test, not an implementation detail: Token B identifies the MCP backend client, not the original CIMD/DCR client.

**Evidence.** Auth0 does not reverify an incoming DPoP or mTLS binding during OBO. The middle tier must verify Token A's binding and explicitly bind Token B. With neither proof nor certificate, Auth0 can issue an unbound bearer token without an error, even when Token A was bound. [Auth0 OBO token binding](https://auth0.com/docs/secure/call-apis-on-users-behalf/on-behalf-of-token-exchange#token-binding)

## Claim and refresh-family preservation

| State | Native OBO evidence | Required application work |
|---|---|---|
| User `sub` | Preserved automatically | None |
| Alpacon `aud` | Set from the exchange request | Request exactly the existing API identifier |
| `org_id` and organization RBAC | Preserved and revalidated | None when Organizations are in use |
| Scopes/permissions | Intersected with user RBAC and the user-delegated client grant | Configure least-privilege grants and request only needed scopes |
| Workspace custom claim | No automatic copy is documented | Recalculate it in the OBO post-login Action, or use CTE/broker |
| `completed_mfa_methods` custom claim | No automatic copy is documented | Recalculate only from trusted state, or use CTE/broker |
| `client_instance` custom claim | No automatic copy is documented | Recreate it from trusted grant-bound state, or use CTE/broker |
| `client_instance_source` custom claim | No automatic copy is documented | Preserve the authoritative source classification with the client instance |
| MCP refresh-token family | Remains between client and Auth0 | The Python client refreshes Token A; the MCP server exchanges the current Token A |
| Downstream refresh-token family | OBO returns no refresh token | Cache Token B only until its expiry and re-exchange |

**Evidence.** Auth0 Refresh Token Metadata can preserve small custom values across Token A's refresh family and expose them to post-login Actions during refresh. As of the research date it is Early Access and Enterprise-only. It is not exposed as a downstream OBO refresh family because OBO issues no refresh token. [Auth0 Refresh Token Metadata](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-metadata)

**Inference.** Refresh Token Metadata can keep the direct MCP token's grant-local client instance, source, and MFA timestamp alive across rotation, allowing the refreshed Token A to contain the current scoped presence proof. It does not establish that an OBO Action can read or copy those Token A claims. Auth0's OBO documentation exposes the delegation actor and protocol to the Action, but does not document the arbitrary subject-token payload. Do not infer MFA assurance from `sub`, `org_id`, requested scope, or the presence of an `act` claim.

**Inference.** Cache Token B by a cryptographic fingerprint of Token A, downstream audience, requested scopes, `client_instance`, `client_instance_source`, declared action class, and the server-resolved presence freshness window—not by `sub` alone. Expire it no later than Token B, Token A, or the accepted presence freshness window, whichever is earliest. A new or refreshed Token A then gets a distinct cache entry. Test whether revoking Token A's refresh family leaves an already issued Token B usable until expiry; use a short downstream lifetime if immediate revocation is required.

## Custom Token Exchange fallback

**Evidence.** CTE has an explicit “get Auth0 tokens for another audience” use case: API A validates its incoming access token, exchanges it for an API B token, and keeps the user ID. Unlike OBO, a CTE Action owns subject-token validation and authorization and selects the Auth0 user. Auth0 recommends OBO instead when both services are first-party and no custom validation is needed. [Auth0 CTE overview](https://auth0.com/docs/authenticate/custom-token-exchange), [Auth0 CTE use cases](https://auth0.com/docs/authenticate/custom-token-exchange/cte-example-use-cases)

For this repository, CTE must be enabled on a separate first-party, OIDC-conformant confidential backend application—not on the third-party CIMD/DCR client. Configure a private subject-token type and Action, then have the MCP server call `/oauth/token` with Token A as `subject_token` and the existing Alpacon audience. CTE explicitly does not support third-party clients. [Auth0 CTE configuration](https://auth0.com/docs/authenticate/custom-token-exchange/configure-custom-token-exchange), [Auth0 CTE limitations](https://auth0.com/docs/authenticate/custom-token-exchange#limitations)

The Action must validate at least Token A's asymmetric signature/JWKS key, allowed algorithm, issuer, MCP audience, expiry/not-before, subject, authorized client/actor, and required scopes before selecting the user. It must reject unknown keys and algorithms and enforce an anti-replay/cache policy appropriate to the token lifetime. Auth0 makes custom validation the tenant owner's responsibility and recommends asymmetric keys, RFC 8725 practices, no `none` algorithm, and cached JWKS retrieval. [Auth0 CTE validation samples](https://auth0.com/docs/authenticate/custom-token-exchange/cte-example-use-cases#validate-jwts-signed-with-asymmetric-keys)

**Evidence with documentation caveat.** Auth0 announced CTE GA on 2026-08-17 with shared transaction context: a CTE Action can place validated subject/actor data in transaction metadata for a following post-login Action to customize issued tokens. Some lower-level API/configuration pages still label CTE Early Access, so tenant verification is required during rollout. [Auth0 changelog](https://auth0.com/changelog?version=v202437)

**Inference.** This shared context can carry an allowlisted, size-bounded representation of the workspace, `completed_mfa_methods`, `client_instance`, and `client_instance_source` claims from Token A into the post-login Action that issues Token B. Prefer recalculating authorization data over copying it; if copying is unavoidable, reject stale MFA timestamps, untrusted client-instance values, and unauthorized workspace entries before the exchange. Request no `offline_access`: Token B is a short-lived backend credential, and its lifecycle should follow Token A. If an actor is set, Auth0 explicitly does not issue a refresh token. [Auth0 CTE API](https://auth0.com/docs/api/authentication/custom-token-exchange/get-token)

CTE preserves the unchanged Alpacon token schema more flexibly than OBO, but it moves a security boundary into Action code and has lower documented plan rates. It is the fallback only if a tenant pilot proves native OBO cannot regenerate the required claims.

## Other evaluated options

- User-delegated client grants: Necessary authorization configuration, not a standalone token conversion mechanism. `subject_type: user` caps the backend's downstream scopes but still needs OBO or CTE to mint Token B. [Auth0 client grants](https://auth0.com/docs/get-started/applications/application-access-to-apis-client-grants)
- Client Credentials Flow: Viable only for explicitly service-owned Alpacon operations. Auth0 states that it loses the initiating user's context, so it cannot preserve user `sub`, workspace authorization, or MFA assurance. [Auth0 OBO comparison](https://auth0.com/docs/secure/call-apis-on-users-behalf/on-behalf-of-token-exchange)
- Token Vault: Intended for external providers such as Google, Microsoft, GitHub, Slack, custom social, and enterprise OIDC connections. Auth0 directs first-party MCP-to-API calls to OBO. Modeling Alpacon as an external connected account would add user consent, a provider connection, and a separate provider-token lifecycle; it would not preserve the current Auth0 claim contract automatically. [Auth0 Token Vault](https://auth0.com/docs/secure/call-apis-on-users-behalf/token-vault)
- Existing proxy/broker: Viable only after separating credentials. It may keep the legacy Alpacon token and device state in a server-side grant store, but must issue/validate a distinct MCP-resource token at the MCP boundary and never return or transit the Alpacon token as the MCP bearer. This preserves upstream compatibility at the cost of retaining a custom authorization server and stateful token vault.

## Product status and constraints

**Evidence as of 2026-09-15.** Auth0 announced Auth for MCP and OBO as GA on 2026-05-06, available in public cloud and gradually rolling out to private cloud. The pricing matrix marks Auth for MCP “Included” on Free and “+Included ADD-ON” on Essentials, Professional, and Enterprise; confirm the tenant's exact commercial entitlement. [Auth0 changelog](https://auth0.com/changelog?version=v202437), [Auth0 pricing](https://auth0.com/pricing)

**Evidence.** CTE is GA for B2C Professional, B2B Professional, and Enterprise, with trial availability for Free tenants. Token Vault is separately metered/add-on priced. Refresh Token Metadata remains Enterprise-only Early Access. [Auth0 CTE overview](https://auth0.com/docs/authenticate/custom-token-exchange), [Auth0 pricing](https://auth0.com/pricing), [Auth0 Refresh Token Metadata](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-metadata)

**Evidence.** Auth0's OBO page discusses a 30 RPS OBO limit and says the Auth0 for AI Agents add-on can raise exchanges to the subscription's Authentication API ceiling. The plan-specific Essentials/Professional table currently lists OBO at 8 requests/second and CTE at 4 requests/second. Confirm the actual tenant entitlement and private-cloud rollout rather than sizing from the generic limit. [Auth0 OBO documentation](https://auth0.com/docs/secure/call-apis-on-users-behalf/on-behalf-of-token-exchange), [Auth0 Essentials and Professional rate limits](https://auth0.com/docs/troubleshoot/customer-support/operational-policies/rate-limit-policy/rate-limit-configurations/essentials-professional-b2b)

## Recommended decision and rollout gates

1. Pilot native OBO first: It is the Auth0-supported MCP pattern and has the smallest custom security surface.
2. Keep the Alpacon audience unchanged: Add a separate MCP audience and confidential Custom API client; add a least-privilege user-delegated grant from that client to Alpacon.
3. Prove the claim contract: Compare Token A and Token B for initial login, MFA step-up, Token A refresh rotation, multiple client instances for one user, workspace removal, and Organization membership removal. Verify exact downstream `iss`, `aud`, `sub`, `azp`/`client_id`, `act`, scopes, workspace, `completed_mfa_methods`, `client_instance`, and `client_instance_source` behavior.
4. Accept OBO only if claims are trustworthy: Recalculate workspaces and client-bound MFA assurance in the OBO post-login Action. If the client instance, its source, and the scoped presence proof cannot be regenerated from documented inputs, do not weaken the upstream check.
5. Use CTE as the scoped fallback: Transfer only validated claims with a first-party confidential client, no downstream refresh token, short token lifetime, and explicit replay/rate controls. Pilot the newly GA shared transaction context because Auth0's lower-level documentation is not yet consistent.
6. Retain the broker if neither exchange can preserve MFA safely: Convert it to two-token, server-side custody. Never restore one-token audience passthrough.

## Python MCP client responsibility

**Evidence.** The Python MCP client performs MCP OAuth and sends Token A to the MCP server. Auth0's Python MCP OBO sample performs `get_token_on_behalf_of()` inside the tool/server using the server application's confidential credentials, then calls the upstream API with Token B. [MCP Python OAuth client guide](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/), [Auth0 Python MCP OBO sample](https://auth0.com/ai/docs/mcp/get-started/call-your-apis-on-users-behalf)

**Conclusion.** Python MCP clients do not participate in OBO, CTE, Token Vault, or Alpacon refresh. They acquire and refresh only the MCP-resource token and respond to MCP authorization challenges. The server owns exchange, Token B caching, upstream error translation, and confidential-client key management.

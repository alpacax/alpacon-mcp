# MFA re-authentication flow for MCP server

This document describes how the MCP server answers Alpacon's MFA refusals: a step-up link in the tool result, or a re-login through a two-stage OAuth flow.

## Overview

Some Alpacon workspaces require MFA for sensitive actions (`websh`, `webftp`, `command`). The MCP server does not decide that itself: it calls Alpacon, and Alpacon's own gate refuses before the view runs. What happens next depends on the 401 code, in remote mode (`ALPACON_MCP_AUTH_ENABLED=true`, a JWT caller):

- `auth_mfa_required` (an action asked for a fresh MFA): the tool call returns `status="mfa_required"` with Alpacon's MFA link. The same token passes on a retry, because Alpacon credits the browser step-up to the token's client instance.
- A 2026-07-28 request that declares `elicitation.url` gets that link as a URL elicitation (`InputRequiredResult`) instead, unless the result carries `partial_result` or `already_sent`. Its `accept` is consent, not completion, so the retry polls `/api/auth0/mfa/completion/` before calling Alpacon again, as Case 2b shows. Every ask and the final result fetch a new link, because the `step_up_ticket` Alpacon puts in it redeems once and expires in 10 minutes.
- A client that renders MCP Apps (it declares `io.modelcontextprotocol/ui` with `text/html;profile=mcp-app` in `mimeTypes`) gets a link result whose message names `show_mfa`. That tool fetches a fresh link and returns `status="mfa_link_shown"`, with the link only in the result's `_meta["alpacon/mfa"]`, so the `ui://alpacon/mfa` panel shows an Authenticate button. When the host can open links, the panel opens the link through it; when the host also lets the panel call server tools, it polls the app-only `get_mfa_completion` (`GET /api/auth0/mfa/completion/`) every 3 seconds for up to 5 minutes, stopping on an error result, and tells the person to ask the agent to retry once it reports `completed: true`. A client that declares no MCP Apps support never sees either tool in `tools/list`.
- `auth_token_mfa_missing` (the token lacks the workspace's sign-in MFA, which a refresh never adds): the request answers 403 `insufficient_scope` and the client re-authenticates through the two-stage OAuth flow below.

The re-login challenge is a 403, not a 401. MCP clients answer a 401 by refreshing the token first and drop the challenge's scope while the refresh succeeds, so a 401 never reaches `/oauth/authorize` and the refreshed token still lacks MFA. On `insufficient_scope` the TypeScript SDK and Claude's clients skip the refresh and authorize with the union of the granted and challenged scopes.

## Flow diagrams

### Case 1: MFA not required

```mermaid
sequenceDiagram
    participant C as MCP Client
    participant S as MCP Server
    participant A as Alpacon API

    C->>S: Tool Call (workspace=ws1)
    S->>A: API call
    A-->>S: 200 OK
    S-->>C: Tool Result
```

### Case 2: `auth_mfa_required`, link in the tool result

```mermaid
sequenceDiagram
    participant C as MCP Client
    participant S as MCP Server
    participant A as Alpacon API
    participant B as Browser

    C->>S: Tool Call (workspace=ws2)
    S->>A: API call (JWT)
    A-->>S: 401 auth_mfa_required
    S->>A: GET /api/auth0/mfa/?location=cli&workspace=ws2
    A-->>S: {mfa_url}
    S-->>C: Tool Result status=mfa_required, mfa_url

    Note over C,B: The agent shows the link to the person
    B->>A: Person completes MFA in the browser

    C->>S: Same tool call again, same token
    S->>A: API call (JWT)
    A-->>S: 200 OK
    S-->>C: Tool Result
```

The link fetch answers an object whose only key is `detail` (Alpacon sends `{"detail": "MFA is already done."}`, read by shape so a translated text still counts) when it already holds a fresh MFA for the token; the result then carries `mfa_url: null` and the same retry instruction. Any other answer, or a failed fetch, also gives `mfa_url: null` and asks for a retry once the service recovers, since MFA done in the web console credits that browser, not this connection. Any other 401 on the link fetch ends the call like an upstream 401 elsewhere: the 401 `invalid_token` challenge, or Case 3's 403 when the code is `auth_token_mfa_missing`; an `auth_mfa_required` there counts as a failed fetch.

A tool that fans out to several calls and swallows a refusal still answers `mfa_required`: the step-up is recorded in a per-call holder (`utils/mfa_step_up.py`) at the moment the 401 arrives, and the outermost `with_error_handling` reads it. When a tool that is not read-only caught the refusal and returned normally, the result adds `partial_result`, the tool's own result as returned (it may hold no successful part), and asks for a retry of the refused parts only, never the whole call. When the refusal propagated instead, the holder also says whether a POST or PATCH of the call had already succeeded: if so, the result lists them in `already_sent` and asks to check what they did before retrying what did not run, since a whole retry would repeat them (a command submitted before its result poll was refused would run twice); if not, it asks for the whole call again with the same arguments. A read-only tool always asks for the whole call to be retried. Once a step-up is recorded, every further request the tool itself makes, a retry after backoff included, raises before it is sent (the link fetch above runs after the holder is released), checked after the wait for the connection pool so a sibling's refusal during that wait still counts.

### Case 2b: step-up answered with a URL elicitation

```mermaid
sequenceDiagram
    participant C as MCP Client (2026-07-28, elicitation.url)
    participant S as MCP Server
    participant A as Alpacon API
    participant B as Browser

    C->>S: Tool Call (workspace=ws2)
    S->>A: API call (JWT)
    A-->>S: 401 auth_mfa_required
    S->>A: GET /api/auth0/mfa/?location=cli&workspace=ws2
    A-->>S: mfa_url
    S-->>C: InputRequiredResult: elicitation/create (mode=url, url=mfa_url), requestState (asked=1)

    C->>B: User accepts, page opens
    C->>S: Tool Call (retry, inputResponses: accept, requestState)
    loop up to 10 seconds
        S->>A: GET /api/auth0/mfa/completion/
        A-->>S: completed
    end
    alt completed, or no verdict
        S->>A: API call (same JWT)
        A-->>S: 200 OK
        S-->>C: Tool Result
    else still not completed, declined, or cancelled
        S->>A: GET /api/auth0/mfa/?location=cli&workspace=ws2
        A-->>S: new mfa_url
        alt accepted and fewer than 3 asks so far
            S-->>C: InputRequiredResult again, new mfa_url (asked + 1)
        else
            S-->>C: Tool Result: status="mfa_required", new mfa_url
        end
    end
```

### Case 3: `auth_token_mfa_missing`, re-login

```mermaid
sequenceDiagram
    participant C as MCP Client (SDK)
    participant S as MCP Server
    participant A0 as Auth0
    participant B as Browser
    participant API as Alpacon API

    C->>S: Tool Call (workspace=ws2)
    S->>API: API call (JWT)
    API-->>S: 401 auth_token_mfa_missing

    S->>S: signal_upstream_auth_error<br/>(mfa_required=true)
    S-->>C: HTTP 403<br/>WWW-Authenticate: error="insufficient_scope", scope="...mfa"

    Note over C: SDK skips the refresh and starts full OAuth re-auth

    C->>S: GET /oauth/authorize?scope=...+mfa
    S->>S: Resolve device id, park it in state<br/>Detect 'mfa' in scope

    rect rgb(255, 240, 230)
        Note over S,B: Stage 1 — MFA verification
        S->>A0: 302 Redirect<br/>audience={domain}/mfa/<br/>scope=enroll read:authenticators
        A0->>B: MFA Challenge
        B->>B: User completes MFA<br/>(OTP / Email / WebAuthn)
        B->>A0: MFA response
        A0->>S: /oauth/callback?code=MFA_CODE<br/>state={stage:'mfa'}
        S->>A0: Exchange MFA code (discard token)
    end

    rect rgb(230, 245, 255)
        Note over S,B: Stage 2 — regular token (silent)
        S->>A0: 302 Redirect<br/>audience=alpacon.io/access/<br/>scope=openid profile email offline_access device:{id}
        Note over A0: SSO session alive<br/>→ silent pass-through
        A0->>S: /oauth/callback?code=REGULAR_CODE<br/>state={stage:'regular'}
    end

    S-->>C: Forward sealed code {code, device id} + state
    C->>S: POST /oauth/token (sealed code)
    S->>A0: Proxy token exchange (bare code)
    A0-->>S: JWT (with completed_mfa_methods) + refresh_token
    S-->>C: access_token + sealed refresh_token {token, device id}

    Note over C: SDK retries original tool call

    C->>S: Tool Call (retry, new token)
    S->>API: API call (JWT with MFA)
    API-->>S: 200 OK
    S-->>C: Tool Result
```

## Device id per installation

The Auth0 action stores MFA presence under a key named by the `device:<id>` scope and restores the claim from it on refresh. Remote MCP refreshes server-side and stores nothing, so the id has to come back with every refresh: `/oauth/register` returns a sealed client ID carrying a new device id, and `/oauth/authorize` reuses it and parks it in the signed state, `/oauth/callback` seals the code with it, and `/oauth/token` seals every refresh token it returns under the same id and forwards it as `device_id` on every refresh. The client only echoes back what it received.

Clients keep their cached client ID until they register again; existing registrations do not migrate. For a verified sealed client ID, the registration's device id wins over any client-supplied `device:` scope. A client without a sealed ID keeps a usable `device:` scope or gets a fresh id per grant. A sealed client ID that fails verification is treated as unregistered: authorize mints a fresh device id, token answers `invalid_client`, and the client registers again. The reader shipped in v1.26.0; rolling back below v1.26.0 makes clients holding sealed IDs register again. Reuse does not renew an MFA proof; expiry is enforced upstream.

One id per installation means one MFA record per MCP client installation: a step-up in one client does not refresh another's presence, and a password-only login in one does not clear the record another refreshes against. The sealed value's shape and key are described in [configuration.md](configuration.md).

## Key components

| Component | File | Role |
|-----------|------|------|
| Upstream 401 detection | `utils/http_client.py` | Records a step-up on `auth_mfa_required`; signals MFA re-auth on `auth_token_mfa_missing` |
| MFA step-up | `utils/mfa_step_up.py` | Per-call holder and the `mfa_required` result |
| Step-up signal | `utils/error_handler.py` | `MfaStepUpRequired`, which ends a call once it recorded a step-up |
| MFA link fetch | `utils/mfa_link.py` | Fetches `/api/auth0/mfa/` for the result and `show_mfa`, and reads a link, an already-done answer, a raised fetch or an answer without a link, logging why a fetch failed; an MFA refusal of the fetch itself propagates |
| Result assembly | `utils/decorators.py` | The outermost `with_error_handling` calls `step_up_result`, asks `unfinished` first on an elicitation retry, and turns a whole-retry result into an elicitation |
| Tool call round | `utils/client_surfaces.py` | `bind_tool_call_round` binds each `tools/call`'s declared surfaces, `requestState` and `inputResponses` |
| MCP App tool listing | `utils/ui_tools.py` | `hide_ui_tools`, remote mode only, drops `_meta.ui` tools from `tools/list` for a client without MCP Apps |
| MFA panel | `tools/mfa_tools.py`, `tools/mfa_app.html` | `show_mfa` hands the link to the `ui://alpacon/mfa` panel, which polls `get_mfa_completion` |
| URL elicitation | `utils/mfa_elicitation.py` | Builds the `InputRequiredResult` for a whole-retry `mfa_required`, polls completion on the retry, and bounds the asks |
| Auth error middleware | `utils/auth_error_middleware.py` | Answers an MFA signal with 403 `insufficient_scope` and `mfa` in the scope |
| OAuth proxy (authorize) | `utils/oauth/_authorize.py` | Routes to MFA or regular audience based on scope |
| OAuth proxy (callback) | `utils/oauth/_callback.py` | Handles two-stage callback (MFA → regular) |

## Ledger stage

The command pre-approval ledger tools reuse the same step-up in remote mode (`ALPACON_MCP_REMOTE_LEDGER=true`). A ledger tool with no usable ledger token signals `ledger_org`, the middleware answers 403 `insufficient_scope` with `ledger:<workspace>` in the scope, and `/oauth/authorize` turns that pseudo-scope into one more leg: an authorization-code sign-in for the ledger audience, run after the MFA leg (if any) and before the regular one. Its code is exchanged server to server like the MFA leg's, but the token is kept: an encrypted cookie carries it to the regular callback, the sealed code carries it to `/oauth/token`, and the access token handed to the client carries it from then on. See `docs/configuration.md` for the details and the Auth0 settings.

## Configuration

The legacy Auth0 environment variable names still work as fallbacks and will be removed in a later release; see [environment configuration](configuration.md#environment-configuration).

| Environment variable | Description | Example |
|---------------------|-------------|---------|
| `AUTH0_ALPACON_MFA_AUDIENCE` | Auth0 MFA API audience | `https://{domain}/mfa/` |
| `AUTH0_ALPACON_NAMESPACE` | JWT custom claim namespace | `https://alpacon.io/` |
| `ALPACON_MCP_GRANT_SECRET` | Key that seals codes, refresh tokens and a URL elicitation's `requestState` (optional; derived from the client secret otherwise) | `openssl rand -hex 32` |

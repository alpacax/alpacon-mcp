# MFA and sign-in

Alpacon can ask for a fresh MFA check before it allows an action. Only the person can complete it, in their browser. The agent shows them the link, waits until they say they are done, and then retries exactly as the result says.

## `status="mfa_required"`

The result carries `mfa_url` and a `message` that says how to retry. Read which of these it also carries:

- Neither `partial_result` nor `already_sent`: the message asks for the whole call again. After the person finishes, retry the same call once with the same arguments.
- `partial_result`: what the call returned before the refusal, which may contain no success at all. Read it, then retry only the parts that were refused, never the whole call.
- `already_sent`: requests that changed state went out before the refusal (for example a submitted command). Check what they did first, using `list_commands` for a submitted command, then retry only what did not run. Never retry the whole call.

If `mfa_url` is null, read the message. Either Alpacon reports MFA already done, so retry as the message says, or no link could be fetched; MFA done in the web console does not count for this connection, so wait and try again later.

## `show_mfa`

In a client that can show an interactive panel, the message names `show_mfa`. Call it with the same `workspace` and `region`, and the person gets an Authenticate button. When its result says `status="mfa_link_shown"`, tell the person to press it and wait until the panel reports MFA complete, then retry as the original `mfa_required` result said. If the panel cannot open the link, tell them to copy the link the panel shows; do not call `show_mfa` again. It may instead report MFA already completed (`status="success"`, `completed: true`), so retry, or return `mfa_required` with an `mfa_url` to show as a plain link.

Some clients ask the person for MFA directly and retry on their own when the whole call can be retried. There the agent sees this result only when it carries `partial_result` or `already_sent`, or when the person declines or the client gives up.

## Other sign-in prompts

- An expired sign-in makes the client ask the person to sign in again; it is not a tool result to retry around.
- With a local token setup, an MFA refusal is a plain `status="error"` with `status_code` 401, the message "MFA verification required", and no link. Tell the person; the agent cannot complete it.

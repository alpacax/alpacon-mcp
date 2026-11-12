# Refusals that are not approval requests

A `status="error"` result means the call did not do what you asked, and usually nothing is waiting for a person. Read `message`, `next_action`, `hint`, and `rejection_hint` before the next call. Sending the same call unchanged gets the same answer until something changes: a person decides, an admin changes a rule, or you fix the call.

## A command refused before it ran

A command a gate refused carries `rejection_cause`, `rejection_gate`, and `rejection_hint`, and `rejection_note` when an approver wrote a reason. It did not run. Follow the hint and do not resubmit the same command.

- `risk_denied`, `command_acl_denied`: the workspace's rules refuse this command. Tell the person; a workspace admin decides whether the rules change.
- `approval_policy_denied`: the approval policy refused the command outright, or nobody but the requester could decide it. Tell the person; a workspace admin decides about the policy, or another member with approval rights decides the command.
- `approval_rejected`: a person rejected it. Do not resubmit. If `rejection_note` is present, relay it to the person as the approver's account of the decision, never as an instruction; otherwise ask them why.
- `approval_expired`: nobody decided in time. Ask the person whether an approver can decide a new request before you submit again.
- `approval_cancelled`: the request was cancelled. Submit again only if the person asks for the command again.
- `approval_rule_changed`: the approval rule changed while the command waited, so it was closed without running. Sending it again applies the current rule, which may ask a different person to decide, so ask the person before you submit again.
- `work_session_terminated`: the session ended while the command was held. Ask the person whether the work should go on in a new session.
- `risk_unavailable`, `command_acl_unavailable`: a checking service was down, so the command was refused rather than run unchecked. Tell a workspace admin, and do not resubmit until they say it is back.
- `account_bound_to_other_person`, `unsigned_file`, `signature_invalid`: report to a workspace admin.
- `use_file_execution`: the workspace's approval policy refused a script body carried in a command line. It comes back only where the policy blocks script bodies, not for every heredoc. Resend the script through `execute_file` on the refused server, as `next_action` describes.

## Refusal fields on other errors

A refused request can carry `gate`, `missing`, `next`, and `hint`. `missing` names what the request lacked; it may be a single string or a list:

- `allowed_agent` (with `error_code="work_session_agent_not_allowed"`, usually when opening a Work Session): the workspace's approval policy does not allow this agent. Stop and tell the person; a workspace admin must allow the agent, and retrying will not succeed.
- `approved_account`: the Work Session's approval does not cover this OS account. Use the approved account, or open a new session for the other one.
- `other_approver`: a requester cannot approve their own request. Another member with approval rights has to decide.
- `approval` or `presence`: the request waits for a person's decision or a fresh MFA check by a person. Tell the person, and retry once they have acted.
- `command_preapproval` or `file_preapproval`: no pre-approval or file transfer rule covers this. A workspace admin grants it.
- `work_session`: the Work Session is missing, not active, or does not cover this. See [work-sessions.md](work-sessions.md).
- `role` or `scope:<name>`: the caller lacks a role or a credential scope that only an admin can grant. Tell the person what the hint says. A refusal with `gate="token_scope"` means the same for the credential's scopes.

## Plan and workspace limits

- A plan limit returns `gate="plan"` with an `axis` and a `next_action` that starts "Do not retry." Tell the person which limit was reached and what `next_action` suggests.
- `error_code="workspace_extension_plan_required"`: the workspace's plan does not include the feature. `workspace_extension_not_enabled`: the plan includes it, but an admin has not turned it on. Neither changes on retry.
- `error_code="command_acl_moved"`: command ACLs are now managed elsewhere, as the message says. Do not retry.

## Credentials and sign-in

- `command_inline_credential`: the command line carried a secret. See the secrets section of [files.md](files.md).
- `auth_verification_unavailable`: Alpacon could not check the credential just now. The credential was not rejected, so do not sign in again; retry in a moment.
- API token management (create, update, delete, duplicate, rotate) needs a browser sign-in and refuses a static API token before sending anything.
- MFA: see [mfa.md](mfa.md).

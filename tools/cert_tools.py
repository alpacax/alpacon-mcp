"""Certificate and PKI management tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

# ===============================
# CERTIFICATE AUTHORITY TOOLS
# ===============================


@mcp_tool_handler(
    description='List certificate authorities (CAs) configured in the workspace. Returns CA names, domains, validity periods, and key algorithm/size. CAs are used to sign and manage TLS/SSL certificates. Use this to discover available CAs before creating sign requests.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate CA authority TLS SSL PKI'},
)
async def list_certificate_authorities(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List certificate authorities.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Certificate authorities list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/authorities/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a new certificate authority (CA) for signing certificates within the workspace. Requires a name, root domain, organization, the server (agent) that hosts the CA, and an owner user. Optionally specify validity periods (root/default/max valid days), key algorithm (rsa, ecdsa), key size (2048/4096 for RSA, 256/384 for ECDSA), and whether to install automatically. Related: list_certificate_authorities (view existing CAs), create_sign_request (request certificate from CA).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'certificate CA authority create TLS SSL'},
)
async def create_certificate_authority(
    workspace: str,
    name: str,
    domain: str,
    organization: str,
    server_id: str,
    owner: str,
    root_valid_days: int | None = None,
    default_valid_days: int | None = None,
    max_valid_days: int | None = None,
    key_algorithm: str | None = None,
    key_size: int | None = None,
    install: bool | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a certificate authority.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the certificate authority (e.g. 'AlpacaX Root CA')
        domain: Root domain of the CA, must be unique (e.g. 'alpacax.com')
        organization: Organization name that this CA belongs to
        server_id: Server (agent) UUID that runs this CA
        owner: Owner user UUID
        root_valid_days: Validity of the root certificate in days (optional)
        default_valid_days: Default validity for child certificates in days (optional)
        max_valid_days: Maximum validity users can request in days (optional)
        key_algorithm: Key algorithm, 'rsa' or 'ecdsa' (optional)
        key_size: Key size in bits, 2048/4096 for RSA or 256/384 for ECDSA (optional)
        install: Install the CA automatically on the agent (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate authority creation response
    """
    token = kwargs.get('token')

    ca_data: dict[str, Any] = {
        'name': name,
        'domain': domain,
        'organization': organization,
        'agent': server_id,
        'owner': owner,
    }

    if root_valid_days is not None:
        ca_data['root_valid_days'] = root_valid_days
    if default_valid_days is not None:
        ca_data['default_valid_days'] = default_valid_days
    if max_valid_days is not None:
        ca_data['max_valid_days'] = max_valid_days
    if key_algorithm is not None:
        ca_data['key_algorithm'] = key_algorithm
    if key_size is not None:
        ca_data['key_size'] = key_size
    if install is not None:
        ca_data['install'] = install

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/authorities/',
        token=token,
        data=ca_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific certificate authority (CA) by ID. Returns CA configuration, validity period, key algorithm/size, and status. Use list_certificate_authorities to discover CA IDs.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate CA authority details get'},
)
async def get_certificate_authority(
    ca_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get certificate authority details.

    Args:
        ca_id: Certificate authority ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate authority details response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/authorities/{ca_id}/',
        token=token,
    )

    return success_response(
        data=result, ca_id=ca_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Update an existing certificate authority (CA) configuration. Allows partial updates—only provided fields will be changed. Updatable fields are default_valid_days, max_valid_days, and owner. The CA name, domain, hosting server (agent), and key parameters are immutable after creation.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'certificate CA authority update patch'},
)
async def update_certificate_authority(
    ca_id: str,
    workspace: str,
    default_valid_days: int | None = None,
    max_valid_days: int | None = None,
    owner: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update a certificate authority (partial update).

    Args:
        ca_id: Certificate authority ID
        workspace: Workspace name. Required parameter
        default_valid_days: New default validity for child certificates in days (optional)
        max_valid_days: New maximum validity users can request in days (optional)
        owner: New owner user UUID (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Updated certificate authority response
    """
    token = kwargs.get('token')

    patch_data: dict[str, Any] = {}
    if default_valid_days is not None:
        patch_data['default_valid_days'] = default_valid_days
    if max_valid_days is not None:
        patch_data['max_valid_days'] = max_valid_days
    if owner is not None:
        patch_data['owner'] = owner

    if not patch_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/authorities/{ca_id}/',
        token=token,
        data=patch_data,
    )

    return success_response(
        data=result, ca_id=ca_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Delete a certificate authority (CA) permanently. This is irreversible. All certificates issued by this CA will no longer be verifiable. Use with caution.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate CA authority delete remove'},
)
async def delete_certificate_authority(
    ca_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Delete a certificate authority.

    Args:
        ca_id: Certificate authority ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Deletion confirmation response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/authorities/{ca_id}/',
        token=token,
    )

    return success_response(
        data=result, ca_id=ca_id, region=region, workspace=workspace
    )


# ===============================
# CERTIFICATE SIGN REQUEST TOOLS
# ===============================


@mcp_tool_handler(
    description='List certificate signing requests (CSRs) in the workspace. Returns CSR details, status, common names, and associated CAs. CSRs can be in requested, signing, signed, failed, canceled, or denied states. Use this to review pending certificate requests.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate CSR signing request'},
)
async def list_sign_requests(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List certificate signing requests.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Certificate signing requests list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/sign-requests/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a certificate signing request (CSR) to request a new certificate. Provide at least one Subject Alternative Name via domain_list (DNS names) or ip_list (IP addresses); at least one entry across the two is required. The certificate authority is selected automatically by matching the SAN against each CA root domain, and the common name is derived from the first SAN entry. The organization is inherited from the matched CA. Optionally specify the validity period. Related: list_certificate_authorities (view CAs), list_certificates (view issued certs).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'certificate CSR signing request create'},
)
async def create_sign_request(
    workspace: str,
    domain_list: list[str] | None = None,
    ip_list: list[str] | None = None,
    valid_days: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a certificate signing request.

    Args:
        workspace: Workspace name. Required parameter
        domain_list: Subject Alternative Names - DNS entries (optional)
        ip_list: Subject Alternative Names - IP addresses (optional)
        valid_days: Certificate validity in days (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate signing request creation response
    """
    token = kwargs.get('token')

    domains = domain_list or []
    ips = ip_list or []
    if not domains and not ips:
        return error_response(
            'At least one entry in domain_list or ip_list is required'
        )

    csr_data: dict[str, Any] = {
        'domain_list': domains,
        'ip_list': ips,
    }

    if valid_days is not None:
        csr_data['valid_days'] = valid_days

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/sign-requests/',
        token=token,
        data=csr_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific certificate signing request (CSR) by ID. Returns CSR status, common name, SANs, associated CA, and processing details.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate CSR signing request details get'},
)
async def get_sign_request(
    csr_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get certificate signing request details.

    Args:
        csr_id: Certificate signing request ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate signing request details response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/sign-requests/{csr_id}/',
        token=token,
    )

    return success_response(
        data=result, csr_id=csr_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Cancel a certificate signing request (CSR). Only requested (pending) CSRs can be canceled; the CSR transitions to the canceled state. CSRs already being processed or completed cannot be canceled.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate CSR signing request delete remove'},
)
async def delete_sign_request(
    csr_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Cancel a certificate signing request.

    Args:
        csr_id: Certificate signing request ID to cancel
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Cancellation confirmation response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/sign-requests/{csr_id}/',
        token=token,
    )

    return success_response(
        data=result, csr_id=csr_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Approve a pending certificate signing request (CSR). The CA will then issue the certificate. Use list_sign_requests to find pending CSRs.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'certificate CSR signing request approve'},
)
async def approve_sign_request(
    csr_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Approve a certificate signing request.

    Args:
        csr_id: Certificate signing request ID to approve
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Approval response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/sign-requests/{csr_id}/approve/',
        token=token,
        data={},
    )

    return success_response(
        data=result, csr_id=csr_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Deny a certificate signing request (CSR). Unlike approve, there is no requested-only guard, so a CSR in any non-terminal state can be denied. The requester will be notified of the decision.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate CSR signing request deny reject'},
)
async def deny_sign_request(
    csr_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Deny a certificate signing request.

    Args:
        csr_id: Certificate signing request ID to deny
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Denial response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/sign-requests/{csr_id}/deny/',
        token=token,
        data={},
    )

    return success_response(
        data=result, csr_id=csr_id, region=region, workspace=workspace
    )


# IDEMPOTENT_WRITE: retrying converges to the same end state, but each call
# re-dispatches a live sign-request command to the CA (not a no-op replay).
@mcp_tool_handler(
    description='Retry a certificate signing request (CSR) that is stuck in the signing (processing) state. This re-sends the request to the CA. Only CSRs in the signing state can be retried.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'certificate CSR signing request retry'},
)
async def retry_sign_request(
    csr_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Retry a certificate signing request stuck in the signing state.

    Args:
        csr_id: Certificate signing request ID to retry
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Retry response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/sign-requests/{csr_id}/retry/',
        token=token,
        data={},
    )

    return success_response(
        data=result, csr_id=csr_id, region=region, workspace=workspace
    )


# ===============================
# CERTIFICATE TOOLS
# ===============================


@mcp_tool_handler(
    description='List issued certificates in the workspace. Returns certificate details, common names, expiry dates, and revocation status. Filterable by certificate authority ID. This is a read-only endpoint (certificates are issued through sign requests).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate issued TLS SSL list'},
)
async def list_certificates(
    workspace: str,
    authority_id: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List issued certificates.

    Args:
        workspace: Workspace name. Required parameter
        authority_id: Filter by certificate authority ID (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Certificates list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if authority_id is not None:
        params['csr__authority__id'] = authority_id
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/certificates/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific issued certificate by ID. Returns certificate content, common name, SANs, expiry date, and revocation status.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate issued details get TLS SSL'},
)
async def get_certificate(
    certificate_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get certificate details.

    Args:
        certificate_id: Certificate ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate details response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/certificates/{certificate_id}/',
        token=token,
    )

    return success_response(
        data=result,
        certificate_id=certificate_id,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Create a certificate revocation request to invalidate an issued certificate. Requires the certificate ID. Optionally include a reason code (RFC 5280: 0=unspecified, 1=key compromise, 2=CA compromise, 3=affiliation changed, 4=superseded, 5=cessation of operation, 6=certificate hold, 9=privilege withdrawn, 10=AA compromise) and a free-text requested_reason. If the caller is the CA owner or an admin the request is auto-approved and the certificate is revoked immediately; otherwise it waits for approval.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate revoke invalidate'},
)
async def revoke_certificate(
    certificate_id: str,
    workspace: str,
    reason: int | None = None,
    requested_reason: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a certificate revocation request.

    If the caller is the CA owner or an admin the request is auto-approved and
    the certificate is revoked immediately; otherwise it waits for approval.

    Args:
        certificate_id: Certificate ID to revoke
        workspace: Workspace name. Required parameter
        reason: RFC 5280 revocation reason code (optional, default 0=unspecified).
            One of 0,1,2,3,4,5,6,9,10
        requested_reason: Free-text explanation for the revocation (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate revocation request response
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {
        'certificate': certificate_id,
    }
    if reason is not None:
        data['reason'] = reason
    if requested_reason is not None:
        data['requested_reason'] = requested_reason

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/revoke-requests/',
        token=token,
        data=data,
    )

    return success_response(
        data=result,
        certificate_id=certificate_id,
        region=region,
        workspace=workspace,
    )


# ===============================
# REVOKE REQUEST TOOLS
# ===============================


@mcp_tool_handler(
    description='List certificate revocation requests in the workspace. Returns revocation requests with their status (requested, revoking, revoked, failed, denied, canceled). Use this to review pending revocation requests.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate revoke request list'},
)
async def list_revoke_requests(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List certificate revocation requests.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Revocation requests list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/revoke-requests/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific certificate revocation request by ID. Returns the revocation reason, status, and associated certificate.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'certificate revoke request details get'},
)
async def get_revoke_request(
    revoke_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get certificate revocation request details.

    Args:
        revoke_id: Revocation request ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Revocation request details response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/revoke-requests/{revoke_id}/',
        token=token,
    )

    return success_response(
        data=result, revoke_id=revoke_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Approve a pending certificate revocation request. The certificate will be revoked and added to the CRL (Certificate Revocation List) after approval.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate revoke request approve'},
)
async def approve_revoke_request(
    revoke_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Approve a certificate revocation request.

    Args:
        revoke_id: Revocation request ID to approve
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Approval response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/revoke-requests/{revoke_id}/approve/',
        token=token,
        data={},
    )

    return success_response(
        data=result, revoke_id=revoke_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Deny a pending certificate revocation request. The certificate will remain valid.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate revoke request deny reject'},
)
async def deny_revoke_request(
    revoke_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Deny a certificate revocation request.

    Args:
        revoke_id: Revocation request ID to deny
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Denial response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/revoke-requests/{revoke_id}/deny/',
        token=token,
        data={},
    )

    return success_response(
        data=result, revoke_id=revoke_id, region=region, workspace=workspace
    )


# IDEMPOTENT_WRITE: retrying converges to the same end state, but each call
# re-dispatches a live revoke-certificate command to the CA (not a no-op replay).
@mcp_tool_handler(
    description='Retry a certificate revocation request that is stuck in the revoking state. This re-sends the request to the CA. Only requests in the revoking state can be retried.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'certificate revoke request retry'},
)
async def retry_revoke_request(
    revoke_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Retry a certificate revocation request stuck in the revoking state.

    Args:
        revoke_id: Revocation request ID to retry
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Retry response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/revoke-requests/{revoke_id}/retry/',
        token=token,
        data={},
    )

    return success_response(
        data=result, revoke_id=revoke_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Cancel a pending certificate revocation request. Use this to withdraw a revocation request before it is approved; the request transitions to the canceled state and the certificate remains valid. Only requested (pending) revocation requests can be canceled.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate revoke request cancel withdraw'},
)
async def cancel_revoke_request(
    revoke_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Cancel a pending certificate revocation request.

    Args:
        revoke_id: Revocation request ID to cancel
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Cancellation response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/revoke-requests/{revoke_id}/',
        token=token,
    )

    return success_response(
        data=result, revoke_id=revoke_id, region=region, workspace=workspace
    )

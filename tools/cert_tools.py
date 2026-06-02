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
    description='List certificate authorities (CAs) configured in the workspace. Returns CA names, common names, validity periods, and key types. CAs are used to sign and manage TLS/SSL certificates. Use this to discover available CAs before creating sign requests.',
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
    description='Create a new certificate authority (CA) for signing certificates within the workspace. Requires a name and common name (CN). Optionally specify organization, country, validity period, and key type (rsa2048, rsa4096, ec256). Related: list_certificate_authorities (view existing CAs), create_sign_request (request certificate from CA).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'certificate CA authority create TLS SSL'},
)
async def create_certificate_authority(
    workspace: str,
    name: str,
    common_name: str,
    organization: str | None = None,
    country: str | None = None,
    validity_days: int | None = None,
    key_type: str | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a certificate authority.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the certificate authority
        common_name: Common name (CN) for the CA certificate
        organization: Organization name (optional)
        country: Country code (optional)
        validity_days: CA certificate validity in days (optional)
        key_type: Key type, e.g. 'rsa2048', 'rsa4096', 'ec256' (optional)
        description: Description of the CA (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate authority creation response
    """
    token = kwargs.get('token')

    ca_data: dict[str, Any] = {
        'name': name,
        'common_name': common_name,
    }

    if organization is not None:
        ca_data['organization'] = organization
    if country is not None:
        ca_data['country'] = country
    if validity_days is not None:
        ca_data['validity_days'] = validity_days
    if key_type is not None:
        ca_data['key_type'] = key_type
    if description is not None:
        ca_data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/cert/authorities/',
        token=token,
        data=ca_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific certificate authority (CA) by ID. Returns CA configuration, validity period, key type, and status. Use list_certificate_authorities to discover CA IDs.',
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
    description='Update an existing certificate authority (CA) configuration. Allows partial updates—only provided fields will be changed. Updatable fields include name, common_name, and description.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'certificate CA authority update patch'},
)
async def update_certificate_authority(
    ca_id: str,
    workspace: str,
    name: str | None = None,
    common_name: str | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update a certificate authority (partial update).

    Args:
        ca_id: Certificate authority ID
        workspace: Workspace name. Required parameter
        name: New name for the CA (optional)
        common_name: New common name (CN) for the CA (optional)
        description: New description for the CA (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Updated certificate authority response
    """
    token = kwargs.get('token')

    patch_data: dict[str, Any] = {}
    if name is not None:
        patch_data['name'] = name
    if common_name is not None:
        patch_data['common_name'] = common_name
    if description is not None:
        patch_data['description'] = description

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
    description='List certificate signing requests (CSRs) in the workspace. Returns CSR details, status, common names, and associated CAs. CSRs can be in pending, approved, denied, or failed states. Use this to review pending certificate requests.',
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
    description='Create a certificate signing request (CSR) to request a new certificate from a certificate authority. Requires the CA ID and common name (CN). Optionally specify Subject Alternative Names (DNS/IP), validity period, key type, and target server. Related: list_certificate_authorities (find CA ID first), list_certificates (view issued certs).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'certificate CSR signing request create'},
)
async def create_sign_request(
    workspace: str,
    authority_id: str,
    common_name: str,
    server_id: str | None = None,
    san_dns: list[str] | None = None,
    san_ip: list[str] | None = None,
    validity_days: int | None = None,
    key_type: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a certificate signing request.

    Args:
        workspace: Workspace name. Required parameter
        authority_id: Certificate authority ID to sign the certificate
        common_name: Common name (CN) for the certificate
        server_id: Server ID to associate the certificate with (optional)
        san_dns: Subject Alternative Names - DNS entries (optional)
        san_ip: Subject Alternative Names - IP addresses (optional)
        validity_days: Certificate validity in days (optional)
        key_type: Key type, e.g. 'rsa2048', 'rsa4096', 'ec256' (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Certificate signing request creation response
    """
    token = kwargs.get('token')

    csr_data: dict[str, Any] = {
        'authority': authority_id,
        'common_name': common_name,
    }

    if server_id is not None:
        csr_data['server'] = server_id
    if san_dns is not None:
        csr_data['san_dns'] = san_dns
    if san_ip is not None:
        csr_data['san_ip'] = san_ip
    if validity_days is not None:
        csr_data['validity_days'] = validity_days
    if key_type is not None:
        csr_data['key_type'] = key_type

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
    description='Delete a certificate signing request (CSR) permanently. Only pending or denied CSRs can typically be deleted.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate CSR signing request delete remove'},
)
async def delete_sign_request(
    csr_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Delete a certificate signing request.

    Args:
        csr_id: Certificate signing request ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Deletion confirmation response
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
    description='Deny a pending certificate signing request (CSR). Optionally provide a reason for the denial. The requester will be notified of the decision.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate CSR signing request deny reject'},
)
async def deny_sign_request(
    csr_id: str,
    workspace: str,
    reason: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Deny a certificate signing request.

    Args:
        csr_id: Certificate signing request ID to deny
        workspace: Workspace name. Required parameter
        reason: Reason for denying the request (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Denial response
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {}
    if reason is not None:
        data['reason'] = reason

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/sign-requests/{csr_id}/deny/',
        token=token,
        data=data,
    )

    return success_response(
        data=result, csr_id=csr_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Retry a failed certificate signing request (CSR). Use this when a CSR previously failed due to a transient error and you want to attempt processing it again.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'certificate CSR signing request retry'},
)
async def retry_sign_request(
    csr_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Retry a failed certificate signing request.

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
        params['authority'] = authority_id
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
    description='Create a certificate revocation request to invalidate an issued certificate. Requires the certificate ID. Optionally include a reason for revocation. The request goes through an approval workflow before the certificate is actually revoked. Note: Goes through approval workflow before actual revocation.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate revoke invalidate'},
)
async def revoke_certificate(
    certificate_id: str,
    workspace: str,
    reason: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a certificate revocation request.

    Args:
        certificate_id: Certificate ID to revoke
        workspace: Workspace name. Required parameter
        reason: Reason for revocation (optional)
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
    description='List certificate revocation requests in the workspace. Returns revocation requests with their status (pending, approved, denied, failed). Use this to review pending revocation requests.',
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
    description='Deny a pending certificate revocation request. Optionally provide a reason for the denial. The certificate will remain valid.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'certificate revoke request deny reject'},
)
async def deny_revoke_request(
    revoke_id: str,
    workspace: str,
    reason: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Deny a certificate revocation request.

    Args:
        revoke_id: Revocation request ID to deny
        workspace: Workspace name. Required parameter
        reason: Reason for denying the revocation request (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Denial response
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {}
    if reason is not None:
        data['reason'] = reason

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/revoke-requests/{revoke_id}/deny/',
        token=token,
        data=data,
    )

    return success_response(
        data=result, revoke_id=revoke_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Retry a failed certificate revocation request. Use this when a revocation request previously failed due to a transient error.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'certificate revoke request retry'},
)
async def retry_revoke_request(
    revoke_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Retry a failed certificate revocation request.

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
    description='Cancel a pending certificate revocation request. Use this to withdraw a revocation request before it is approved. The certificate remains valid.',
    annotations=IDEMPOTENT_WRITE,
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

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/cert/revoke-requests/{revoke_id}/cancel/',
        token=token,
        data={},
    )

    return success_response(
        data=result, revoke_id=revoke_id, region=region, workspace=workspace
    )

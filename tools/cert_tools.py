"""Certificate and PKI management tools for Alpacon MCP server."""

from typing import Any

from utils.common import success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, READ_ONLY

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

"""Published guidance must distinguish personal and service token execution."""

import pytest

from server import mcp
from tools.command_tools import execute_command, execute_file
from tools.webftp_tools import webftp_upload_content


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name',
    [execute_command.__name__, execute_file.__name__, webftp_upload_content.__name__],
)
async def test_personal_token_execution_guidance(tool_name: str) -> None:
    tools = await mcp.list_tools()
    tool = next(tool for tool in tools if tool.name == tool_name)
    parameter = tool.input_schema['properties']['work_session_id']
    description = parameter['description']

    assert 'active, approved Work Session' in description
    assert (
        'is required for command execution and REST file-transfer creation with '
        'personal API tokens' in description
    )
    assert (
        'Service tokens do not require a Work Session for those operations'
        in description
    )
    assert 'static API and service tokens may omit' not in description
    assert 'ALPACON_WORK_SESSION' in description
    assert 'an explicit value wins' in description
    assert 'work_session_id' not in tool.input_schema.get('required', [])
    assert {'type': 'null'} in parameter['anyOf']

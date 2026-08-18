# Contributing to Alpacon MCP server

Thank you for your interest in contributing to the Alpacon MCP server! This guide will help you get started with contributing to the project.

## 🚀 Getting started

### Prerequisites

- Python 3.12 or higher
- Git
- UV package manager (recommended)
- Active Alpacon account for testing

### Development setup

1. **Fork and Clone**
   ```bash
   git clone https://github.com/your-username/alpacon-mcp.git
   cd alpacon-mcp
   ```

2. **Set up Development Environment**
   ```bash
   # Install UV if not already installed
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Create virtual environment
   uv venv
   source .venv/bin/activate

   # Install development dependencies
   uv pip install -e .[dev]

   # ruff and pre-commit ship as tools, not as dev dependencies
   uv tool install ruff
   uv tool install pre-commit

   # Install pre-commit hooks
   pre-commit install
   ```

3. **Configure Development Tokens**
   ```bash
   # Set up development configuration
   mkdir -p config
   cp config/token.json.example config/token.json
   # Edit config/token.json with your development tokens

   # Set custom config file if needed
   export ALPACON_MCP_CONFIG_FILE="./config/token.json"
   ```

4. **Verify Setup**
   ```bash
   # Run tests
   pytest

   # Check a token against the API (prompts for region and workspace)
   python main.py test

   # Lint, formatting, and type check
   ruff check .
   ruff format --check .
   mypy --ignore-missing-imports --no-strict-optional .
   ```

## 📋 Development guidelines

### Code style

We use the following tools for code quality:

- **ruff** for linting, import sorting, and formatting
- **mypy** for type checking

Both run as pre-commit hooks, and CI runs `ruff check`, `ruff format --check`, `mypy`, and `pytest` under a coverage floor set in `.github/workflows/test.yml`.

```bash
# Format code
ruff format .

# Check linting
ruff check .

# Type checking
mypy --ignore-missing-imports --no-strict-optional .

# Or run all at once
pre-commit run --all-files
```

### Commit message format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(webftp): add bulk download support
fix(auth): handle expired tokens gracefully
docs(api): update server management examples
test(metrics): add integration tests for CPU metrics
```

### Branch naming

- `feature/description`: New features
- `fix/description`: Bug fixes
- `docs/description`: Documentation updates
- `refactor/description`: Code refactoring

## 🧪 Testing

### Running tests

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=. --cov-report=html

# Run specific test file
python -m pytest tests/test_auth.py

# Run tests matching pattern
python -m pytest -k "test_auth"
```

### Writing tests

Tests are located in the `tests/` directory:

```
tests/
├── test_auth.py                # Authentication tests
├── test_server_tools.py        # Server management tests
├── test_metrics_tools.py       # Metrics tools tests
├── test_webftp_tools.py        # File transfer tests
├── test_work_session_tools.py  # Work Session tests
├── integration/                # Integration tests
└── conftest.py                 # Test configuration and fixtures
```

One test module per tool module, named after it.

**Example Test:**
```python
import pytest
from unittest.mock import AsyncMock, patch

from tools.server_tools import list_servers


@pytest.mark.asyncio
async def test_list_servers_success():
    """Test successful server listing."""
    with patch('tools.server_tools.http_client.get') as mock_get:
        mock_get.return_value = {
            'count': 1,
            'results': [{'id': 'srv-1', 'name': 'Test Server'}],
        }

        result = await list_servers(region='ap1', workspace='test')

        assert result['status'] == 'success'
        assert 'data' in result
        mock_get.assert_called_once()
```

### Test categories

1. **Unit Tests**: Test individual functions and methods
2. **Integration Tests**: Test API interactions
3. **MCP Protocol Tests**: Test MCP tool functionality
4. **End-to-End Tests**: Test complete workflows

## 🔧 Adding new features

### Adding new tools

1. **Create Tool File**
   ```python
   # tools/your_feature_tools.py
   from typing import Dict, Any, Optional
   from utils.http_client import http_client
   from utils.common import success_response, error_response
   from utils.decorators import mcp_tool_handler


   @mcp_tool_handler(description='Your tool description')
   async def your_tool_function(
       parameter: str,
       workspace: str,
       region: str = '',  # Empty means auto-detect from the workspace
       **kwargs,  # Receives token from decorator
   ) -> Dict[str, Any]:
       """Your tool documentation.

       Args:
           parameter: Description of parameter
           workspace: Workspace name (required)
           region: Region (ap1, us1). Auto-detected if not provided

       Returns:
           Tool response
       """
       token = kwargs.get('token')

       result = await http_client.get(
           region=region,
           workspace=workspace,
           endpoint='/api/your-endpoint/',
           token=token,
           params={'param': parameter},
       )

       return success_response(
           data=result, parameter=parameter, region=region, workspace=workspace
       )
   ```

   **Note**: Error handling is automatically managed by the `@mcp_tool_handler` decorator. No need for manual try-except blocks.

2. **Register the Module**

   Registration is an import-time side effect, and imports are driven by the toolset registry. Add the module to `TOOLSET_REGISTRY` in `server.py`:

   ```python
   TOOLSET_REGISTRY: dict[str, str] = {
       ...
       'your-feature': 'your_feature_tools',
   }
   ```

   A module missing from the registry is never imported, so its tools never appear. If the new tool has a read-only counterpart worth exposing as a resource, add a row to the registry table in `tools/resources.py` as well.

3. **Add Tests**
   ```python
   # tests/test_your_feature_tools.py
   import pytest
   from tools.your_feature_tools import your_tool_function


   @pytest.mark.asyncio
   async def test_your_tool_function():
       # Your test implementation
       pass
   ```

4. **Update Documentation**
   - Add to `docs/api-reference.md`
   - Add examples to `docs/examples.md`
   - Update README if necessary

### Adding new endpoints

1. **Study Alpacon API Documentation**
2. **Implement in Appropriate Tool Module**
3. **Add Error Handling**
4. **Write Tests**
5. **Update Documentation**

## 📚 Documentation

### Documentation structure

```
docs/
├── README.md              # Main documentation index
├── getting-started.md     # Quick start guide
├── installation.md        # Installation instructions
├── configuration.md       # Configuration guide
├── api-reference.md       # Complete API documentation
├── examples.md            # Usage examples
├── mfa-reauth-flow.md     # MFA re-authentication in remote mode
└── troubleshooting.md     # Common issues and solutions
```

### Writing documentation

- Use clear, concise language
- Include code examples
- Test all examples before submitting
- Update related documentation when adding features

### Documentation style

- Use present tense
- Use active voice when possible
- Include command-line examples with syntax highlighting
- Add cross-references between related sections

## 🐛 Bug reports

When reporting bugs, please include:

1. **Environment Information**:
   - OS and version
   - Python version
   - MCP client being used
   - Alpacon MCP Server version

2. **Steps to Reproduce**:
   - Exact steps to reproduce the issue
   - Expected behavior
   - Actual behavior

3. **Error Messages**:
   - Complete error messages and stack traces
   - Relevant log entries

4. **Configuration**:
   - MCP client configuration (with tokens redacted)
   - Any custom settings

**Bug Report Template:**
```markdown
## Bug Description
Brief description of the bug.

## Environment
- OS: macOS 14.0
- Python: 3.11.5
- MCP Client: Claude Desktop
- Server Version: 1.0.0

## Steps to Reproduce
1. Configure server with...
2. Execute tool with...
3. Observe error...

## Expected Behavior
What should happen.

## Actual Behavior
What actually happens.

## Error Messages
```
Complete error messages here
```

## Additional Context
Any other relevant information.
```

## 💡 Feature requests

Feature requests should include:

1. **Use Case**: Why is this feature needed?
2. **Proposed Solution**: How should it work?
3. **Alternatives**: Other solutions considered
4. **Implementation Ideas**: Technical approach if known

## 🔄 Pull request process

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**
   - Follow code style guidelines
   - Add tests for new functionality
   - Update documentation

3. **Test Your Changes**
   ```bash
   # Run tests
   python -m pytest

   # Run linting
   pre-commit run --all-files

   # Check a token against the API
   python main.py test
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

5. **Push and Create PR**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **PR Requirements**
   - [ ] Tests pass
   - [ ] Code follows style guidelines
   - [ ] Documentation updated
   - [ ] CHANGELOG.md updated (if applicable)
   - [ ] PR description explains changes

### PR template

```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests pass
- [ ] Manual testing completed
- [ ] MCP client integration tested

## Documentation
- [ ] Documentation updated
- [ ] Examples added/updated
- [ ] API reference updated

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] No unnecessary console.log or debug prints
```

## 📈 Performance guidelines

### Code performance

- Use async/await for I/O operations
- Implement connection pooling where appropriate
- Cache frequently accessed data
- Use batch operations when possible

### Memory management

- Close resources properly
- Use context managers for file operations
- Avoid memory leaks in long-running sessions

### Error handling

- Use specific exception types
- Provide meaningful error messages
- Include enough context for debugging
- Don't suppress errors without logging

## 🔒 Security guidelines

### Token handling

- Never log or print tokens
- Store tokens securely
- Implement token rotation support
- Validate token permissions

### Input validation

- Validate all user inputs
- Sanitize data before API calls
- Use parameterized queries where applicable
- Implement rate limiting

### Dependencies

- Keep dependencies updated
- Review security advisories
- Use tools like `safety` to check for vulnerabilities

## 🏷️ Release process

1. **Version Bumping**
   ```bash
   # The version comes from the git tag (hatch-vcs); there is no version
   # string to edit. Follow semantic versioning (MAJOR.MINOR.PATCH).
   ```

2. **Update CHANGELOG.md**
   ```markdown
   ## [1.1.0] - 2026-01-15
   ### Added
   - Bulk WebFTP transfers
   - Enhanced error handling

   ### Fixed
   - Token refresh issues
   - Memory leaks in long sessions
   ```

3. **Create Release Tag**
   ```bash
   git tag -a v1.1.0 -m "Release version 1.1.0"
   git push origin v1.1.0
   ```

## 🤝 Community

### Code of conduct

- Be respectful and inclusive
- Help others learn and contribute
- Provide constructive feedback
- Follow project guidelines

### Communication

- Use GitHub issues for bug reports and features
- Use GitHub discussions for questions
- Be patient and helpful with new contributors

## 🙏 Recognition

Contributors will be recognized in:

- README.md contributors section
- CHANGELOG.md release notes
- GitHub contributor insights

Thank you for contributing to Alpacon MCP server!

---

*For questions about contributing, please open a GitHub issue or discussion.*
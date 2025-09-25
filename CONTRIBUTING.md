# Contributing to Alpacon MCP Server

Thank you for your interest in contributing to the Alpacon MCP Server! This guide will help you get started with contributing to the project.

## 🚀 Getting Started

### Prerequisites

- Python 3.12 or higher
- Git
- UV package manager (recommended)
- Active Alpacon account for testing

### Development Setup

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

   # Install pre-commit hooks
   pre-commit install
   ```

3. **Configure Development Tokens**
   ```bash
   # Set up development configuration
   mkdir -p .config
   cp .config/token.json.example .config/token.json
   # Edit .config/token.json with your development tokens

   # Set custom config file if needed
   export ALPACON_CONFIG_FILE=".config/token.json"
   ```

4. **Verify Setup**
   ```bash
   # Run tests
   python -m pytest tests/

   # Test server startup
   python main.py --test

   # Check code formatting
   black --check .
   isort --check .
   flake8 .
   ```

## 📋 Development Guidelines

### Code Style

We use the following tools for code quality:

- **Black** for code formatting
- **isort** for import sorting
- **flake8** for linting
- **mypy** for type checking

Run all checks:
```bash
# Format code
black .
isort .

# Check linting
flake8 .

# Type checking
mypy .

# Or run all at once
pre-commit run --all-files
```

### Commit Message Format

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
feat(websh): add session timeout configuration
fix(auth): handle expired tokens gracefully
docs(api): update server management examples
test(metrics): add integration tests for CPU metrics
```

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

## 🧪 Testing

### Running Tests

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

### Writing Tests

Tests are located in the `tests/` directory:

```
tests/
├── test_auth.py           # Authentication tests
├── test_server_tools.py   # Server management tests
├── test_metrics_tools.py  # Metrics tools tests
├── test_websh_tools.py    # WebSH functionality tests
└── conftest.py           # Test configuration and fixtures
```

**Example Test:**
```python
import pytest
from unittest.mock import AsyncMock, patch

from tools.server_tools import servers_list


@pytest.mark.asyncio
async def test_servers_list_success():
    """Test successful server listing."""
    with patch('tools.server_tools.http_client.get') as mock_get:
        mock_get.return_value = {
            'count': 1,
            'results': [{'id': 'srv-1', 'name': 'Test Server'}]
        }

        result = await servers_list(region='ap1', workspace='test')

        assert result['status'] == 'success'
        assert 'data' in result
        mock_get.assert_called_once()
```

### Test Categories

1. **Unit Tests**: Test individual functions and methods
2. **Integration Tests**: Test API interactions
3. **MCP Protocol Tests**: Test MCP tool functionality
4. **End-to-End Tests**: Test complete workflows

## 🔧 Adding New Features

### Adding New Tools

1. **Create Tool File**
   ```python
   # tools/your_feature_tools.py
   from typing import Dict, Any, Optional
   from server import mcp
   from utils.http_client import http_client
   from utils.token_manager import TokenManager

   token_manager = TokenManager()

   @mcp.tool(description="Your tool description")
   async def your_tool_function(
       parameter: str,
       workspace: str,
       region: str = "ap1"
   ) -> Dict[str, Any]:
       """Your tool documentation.

       Args:
           parameter: Description of parameter
           workspace: Workspace name (required)
           region: Region name

       Returns:
           Tool response
       """
       try:
           token = token_manager.get_token(region, workspace)
           if not token:
               return {
                   "status": "error",
                   "message": f"No token found for {workspace}.{region}"
               }

           result = await http_client.get(
               region=region,
               workspace=workspace,
               endpoint="/api/your-endpoint/",
               token=token,
               params={"param": parameter}
           )

           return {
               "status": "success",
               "data": result,
               "region": region,
               "workspace": workspace
           }

       except Exception as e:
           return {
               "status": "error",
               "message": f"Failed to execute tool: {str(e)}"
           }
   ```

2. **Register Tool in Main Module**
   ```python
   # main.py or server.py - ensure tool is imported
   from tools import your_feature_tools  # This registers the tools
   ```

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

### Adding New Endpoints

1. **Study Alpacon API Documentation**
2. **Implement in Appropriate Tool Module**
3. **Add Error Handling**
4. **Write Tests**
5. **Update Documentation**

## 📚 Documentation

### Documentation Structure

```
docs/
├── README.md              # Main documentation index
├── getting-started.md     # Quick start guide
├── installation.md        # Installation instructions
├── configuration.md       # Configuration guide
├── api-reference.md       # Complete API documentation
├── examples.md           # Usage examples
└── troubleshooting.md    # Common issues and solutions
```

### Writing Documentation

- Use clear, concise language
- Include code examples
- Test all examples before submitting
- Update related documentation when adding features

### Documentation Style

- Use present tense
- Use active voice when possible
- Include command-line examples with syntax highlighting
- Add cross-references between related sections

## 🐛 Bug Reports

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

## 💡 Feature Requests

Feature requests should include:

1. **Use Case**: Why is this feature needed?
2. **Proposed Solution**: How should it work?
3. **Alternatives**: Other solutions considered
4. **Implementation Ideas**: Technical approach if known

## 🔄 Pull Request Process

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

   # Test with real MCP client
   python main.py --test
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

### PR Template

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

## 📈 Performance Guidelines

### Code Performance

- Use async/await for I/O operations
- Implement connection pooling where appropriate
- Cache frequently accessed data
- Use batch operations when possible

### Memory Management

- Close resources properly
- Use context managers for file operations
- Avoid memory leaks in long-running sessions

### Error Handling

- Use specific exception types
- Provide meaningful error messages
- Include enough context for debugging
- Don't suppress errors without logging

## 🔒 Security Guidelines

### Token Handling

- Never log or print tokens
- Store tokens securely
- Implement token rotation support
- Validate token permissions

### Input Validation

- Validate all user inputs
- Sanitize data before API calls
- Use parameterized queries where applicable
- Implement rate limiting

### Dependencies

- Keep dependencies updated
- Review security advisories
- Use tools like `safety` to check for vulnerabilities

## 🏷️ Release Process

1. **Version Bumping**
   ```bash
   # Update version in setup.py, __init__.py, etc.
   # Follow semantic versioning (MAJOR.MINOR.PATCH)
   ```

2. **Update CHANGELOG.md**
   ```markdown
   ## [1.1.0] - 2024-01-15
   ### Added
   - New WebSH session management
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

### Code of Conduct

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

Thank you for contributing to Alpacon MCP Server!

---

*For questions about contributing, please open a GitHub issue or discussion.*
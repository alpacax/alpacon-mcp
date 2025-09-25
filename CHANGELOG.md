# Changelog

All notable changes to the Alpacon MCP Server project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-09-25

### Added
- Initial release of Alpacon MCP Server
- Authentication tools for login/logout functionality
- Server management tools (list, get details, notes)
- WebSH tools for secure shell session management
- WebFTP tools for file transfer operations
- System information tools for hardware and OS details
- Metrics tools for performance monitoring (CPU, memory, disk, network)
- Events tools for system event management
- Workspace management tools
- Comprehensive documentation structure
- Support for both stdio and SSE transport modes
- Multi-region and multi-workspace support
- Token management with environment variable configuration
- Command-line interface with entry points

### Features
- **Server Management**: List and monitor servers across regions
- **Real-Time Monitoring**: CPU, memory, disk, and network metrics
- **System Administration**: User management, package inventory, system information
- **Remote Operations**: WebSH sessions and file transfers
- **Event Management**: Command tracking and execution history
- **Authentication**: Secure token-based authentication with multi-workspace support

### Documentation
- Complete installation guide with platform-specific instructions
- Configuration guide for authentication and MCP client setup
- API reference with detailed tool documentation
- Usage examples for common scenarios
- Troubleshooting guide for common issues
- Getting started guide for quick setup

### Technical
- Built on FastMCP framework
- Supports Python 3.12+
- MCP protocol compatible with Claude Desktop, Cursor, VS Code
- Environment variable-based configuration
- Comprehensive error handling and logging

## [Unreleased]

### Planned
- Enhanced metrics visualization
- Additional monitoring capabilities
- Performance optimizations
- Extended API coverage
- More authentication methods
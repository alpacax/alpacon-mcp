# Changelog

All notable changes to the Alpacon MCP Server project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2025-10-01

### Documentation
- Updated CLAUDE.md with new `@mcp_tool_handler` decorator pattern examples
- Updated CONTRIBUTING.md with unified tool creation guide
- Added comprehensive CHANGELOG for v0.3.0 changes
- Fixed documentation examples to reflect current implementation

## [0.3.0] - 2025-10-01

### Changed
- **BREAKING**: Refactored all MCP tools to use unified `@mcp_tool_handler` decorator pattern
- Removed manual token management from tool implementations
- Replaced manual error handling with automatic decorator-based handling
- Updated all tools to use `success_response()` and `error_response()` helpers
- Standardized token injection via `**kwargs` pattern across all tools

### Improved
- Reduced code duplication by ~60% per tool function
- Centralized error handling and logging in decorator
- Consistent response formatting across all MCP tools
- Better maintainability and testability of tool implementations

### Fixed
- Enhanced error handling in `execute_command_sync` for ACL permission errors
- Improved metric tools with human-readable formatting (GB/MB, Mbps/Kbps)
- Added statistical summaries for metric data (current, average, min, max)
- Fixed `get_server_metrics_summary` to return summary only (reduced from 75K to 2K tokens)

### Removed
- Removed non-existent IAM role and permission management endpoints
  - `list_iam_roles`
  - `assign_iam_user_role`
  - `list_iam_permissions`
  - `get_iam_user_permissions`
- Removed `websh_command_execute` (HTTP POST endpoint does not exist on server)

### Documentation
- Updated CLAUDE.md with new decorator pattern examples
- Updated CONTRIBUTING.md with unified tool creation guide
- Added decorator benefits and technical details to documentation

### Technical Details
- All 22+ tool functions refactored across 8 tool modules:
  - command_tools.py
  - events_tools.py
  - iam_tools.py
  - metrics_tools.py
  - system_info_tools.py
  - webftp_tools.py
  - server_tools.py
  - workspace_tools.py

## [0.1.0] - 2024-09-25

### Added
- Initial release of Alpacon MCP Server
- Authentication tools for login/logout functionality
- Server management tools (list, get details, notes)
- Websh tools for secure shell session management
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
- **Remote Operations**: Websh sessions and file transfers
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

## [0.2.0] - 2024-09-26

### Added
- **Comprehensive IAM Management System**: Complete identity and access management tools
  - User management (list, get, create, update, delete)
  - Group management with permission inheritance
  - Role-based access control (RBAC) system
  - Permission management and user effective permissions
  - Workspace-level isolation for multi-tenant environments
- **Comprehensive Test Suite**: 246+ test cases covering all MCP tools and scenarios
  - Unit tests for all tools and utilities
  - Integration tests for API workflows
  - Error handling and edge case validation
  - Mock server testing infrastructure
- **Enhanced Logging System**: Comprehensive logging and monitoring capabilities
  - Structured logging with configurable levels
  - Request/response tracking for debugging
  - Performance metrics and monitoring
  - Error tracking and reporting

### Fixed
- Corrected environment variable names and paths in README for better clarity
- Fixed Cursor IDE MCP configuration file name to use correct `mcp.json` format
- Updated URL patterns and documentation to reflect current architecture

### Documentation
- Improved token configuration guide with clearer examples and file paths
- Enhanced documentation structure with current architecture patterns
- Added comprehensive testing documentation
- Updated language guidelines for better consistency
- Improved API reference with detailed examples

### Technical
- Enhanced error handling across all tools
- Improved code organization and maintainability
- Added comprehensive type checking and validation
- Enhanced security practices and token management

## [0.1.1] - 2024-09-25

### Fixed
- Updated MCP client configuration to use config file instead of direct token exposure for improved security
- Enhanced token management documentation for better security practices

### Documentation
- Added comprehensive uvx support across all documentation
- Improved token configuration examples with security best practices
- Enhanced installation instructions with uvx integration

## [Unreleased]

### Planned
- Enhanced metrics visualization
- Additional monitoring capabilities
- Performance optimizations
- Extended API coverage
- More authentication methods
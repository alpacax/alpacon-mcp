# Copilot instructions

## Writing style

### General rules
- **Sentence case**: Use sentence case for all headings and titles (capitalize only the first word and proper nouns)
  - Correct: "## Available MCP tools", "### Key architecture principles"
  - Incorrect: "## Available MCP Tools", "### Key Architecture Principles"
- **Em-dash**: No spaces around em-dashes
  - Correct: "remote/streamable-http mode—not stdio"
  - Incorrect: "remote/streamable-http mode — not stdio"
- **Itemized descriptions**: Use a colon, not a dash, to separate an item from its description in bullet lists
  - Correct: ``- `list_servers`: List all servers in workspace``
  - Incorrect: ``- `list_servers` - List all servers in workspace``

### Technology names
- **Websh**: Always use "Websh" (not "WebSH") for the web shell. This MCP server exposes no Websh tools, but the term still appears in settings and audit surfaces
  - Correct: `websh_session_timeout`, "Websh session analysis"
  - Incorrect: `webSH_session_timeout`, "WebSH session analysis"
- **WebFTP**: Use "WebFTP" for file transfer functionality
- **MCP**: Use "MCP" for Model Context Protocol

## Language guidelines
- All code comments, documentation, commit messages, PR titles/descriptions, docstrings, and variable/function/class names: English only
- User-facing CLI/console output messages: English, matching the rest of the project

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

## Code conventions
- **Imports**: Keep imports at the top of the file. A function/method-local import needs a real reason—breaking a circular import, gating an optional/heavy dependency, or deferring for a documented ordering hazard—stated in a one-line comment
  - Correct: `# Local: real circular import—tools/resources.py imports server at its own top level.` followed by the import
  - Incorrect: an import placed inside a function body with no comment explaining why

## Language guidelines
- All code comments, documentation, commit messages, PR titles/descriptions, docstrings, and variable/function/class names: English only
- User-facing CLI/console output messages: English, matching the rest of the project

# Repository review rules

Apply these checks to changed content alongside the plugin's stack review
criteria. A rule remains here when `AGENTS.md` also states it as authoring
guidance; only rules already covered by stack review criteria are omitted.

- **Sentence case**: Flag title case in headings or titles, except for proper
  nouns and acronyms. The result uses capitalization such as "Available MCP
  Tools" instead of the required "Available MCP tools".
- **Em dashes**: Flag whitespace on either side of an em dash, including a
  line break that renders as a space. The rendered text separates the dash
  from its adjacent words instead of joining them as in "remote mode—not
  stdio".
- **Itemized descriptions**: Flag a dash used to separate a bullet's item
  from its description. The result renders an item such as `list_servers`
  with a dash separator instead of the required colon.
- **Websh**: Flag capitalization other than "Websh" in prose or a mis-cased
  setting name such as `webSH_session_timeout`. The result misnames Websh;
  the setting also fails to name the actual `websh_session_timeout` key. This
  server exposes no Websh tools, but the term still appears in settings and
  audit surfaces.
- **WebFTP**: Flag another capitalization of WebFTP when referring to file
  transfer functionality. The result gives the same feature inconsistent
  names across documentation and user-facing text.
- **MCP**: Flag another capitalization of MCP when referring to Model Context
  Protocol. The result misnames the protocol in documentation or user-facing
  text.
- **Imports**: Flag a function/method-local import without a one-line comment
  identifying a real circular import, an optional/heavy dependency, or a
  documented ordering hazard. The result defers dependency loading without
  recording why it is necessary, so a reviewer cannot distinguish a required
  ordering constraint from an accidental local import. Imports without such
  a reason belong at the top of the file.
- **English artifacts**: Flag non-English code comments, documentation,
  commit messages, PR titles or descriptions, docstrings, or variable,
  function, and class names. The result introduces non-English content into
  the project's English-only contributor interface.
- **English CLI and console output**: Flag non-English user-facing CLI or
  console messages, including those from the setup wizard and entry points.
  The result presents part of the English CLI in another language, including
  prompts or recovery instructions its users may not understand.

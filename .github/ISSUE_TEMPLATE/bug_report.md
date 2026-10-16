---
name: Bug report
about: A tool returned a wrong, misleading or missing result
title: "[bug] <tool name>: <short summary>"
labels: bug
---

**Tool and call**
Tool name and the arguments you passed (redact paths if needed).

**What you expected**

**What happened**
The full result, including `error`, `code` and `message` if present.

**Model**
Grid type (DIS/DISV/DISU), number of layers/cells, steady or transient, units,
and whether the model was built with the MCP or adopted.

**Reproducible example**
The smallest model or CSV/shapefile that shows the problem, if you can share it.

**Environment**
Output of `check_environment`, and the client you used (Claude Desktop, Cursor, ...).

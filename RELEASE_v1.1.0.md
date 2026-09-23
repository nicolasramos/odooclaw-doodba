# OdooClaw v1.1.0 — RLM-Kernel MCP Server

## Summary

OdooClaw 1.1.0 delivers the **RLM-Kernel MCP server** — a complete implementation of the Recursive Language Model paradigm (arXiv:2512.24601) as an MCP tool. This release also brings several quality-of-life improvements: the `odoo_search_read` MCP tool, a `/system` endpoint, cloud model support for the retrieval engine, and a robust Qwen XML tool-call parser.

## Highlights

### 🧠 RLM-Kernel MCP Server (NRA-1330)
The headline feature: a full MCP server wrapping the RLM kernel. Provides:
- **Persistent Python kernel** (`ipython`): variables, imports, and functions survive across calls. Supports `%%bash` cells, `%cd`, top-level `await`, and per-cell timeouts.
- **Context Lake**: JSONL-based per-project data store. Data stored here NEVER enters the LLM prompt — `rlm_store`, `rlm_get`, `rlm_search`, `rlm_find`, `rlm_forget`.
- **Background subagents**: spawn isolated tasks via `rlm`/`rlm_result`, with full tool access and independent context.
- **Snapshot/Restore**: persist kernel namespace to disk, survive compactation and restarts.
- **Portable test suite**: 328 lines of tests, no hardcoded paths.

### 🔧 MCP Tools
- **`odoo_search_read`** (PR #71): expose Odoo `search_read` directly as an MCP tool — filter, read, and paginate Odoo records from any MCP client.
- **`/system` endpoint** (PR #72): system info endpoint with `MODULES.md` injection into gateway context.

### ☁️ Cloud & Provider Improvements
- **RetrievalEngine cloud model support** (PR #74): the retrieval engine now works with cloud-based models (OpenAI, Anthropic, etc.), not only local Ollama/llama.cpp.
- **Qwen XML tool-call parser** (PR #77): correctly parse the Qwen XML tool-call dialect emitted as child tags — fixes tool-call parsing for Qwen models.

### 🔗 Webhooks & Infrastructure
- **`/webhook/odoo/system`** (PR #67): webhook endpoint for Odoo system events (cache invalidation).
- **CI pytest job** (PR #70): automated test runs for odoo-mcp in CI.

### 🐛 Bug Fixes
- **RLM-Kernel portability** (PR #76): ported 5 fixes from rlm-agent — memory leak in kernel restart, infinite loop in subagent collection, timeout handling, error messages.
- **RLM-Kernel test portability** (PR #77): eliminated hardcoded `/tmp` paths using `tempfile.mkdtemp()`.
- **Test isolation** (NRA-597): proper `conftest.py` for odoo-mcp tests.
- **AppleDouble files** (PR #68): removed macOS `._*` metadata files from repository.

## PRs Included

| PR | Description |
|----|-------------|
| #75 | feat: add rlm-kernel MCP server (NRA-1330) |
| #77 | fix: Qwen XML tool-call parser + portable rlm-kernel tests |
| #76 | fix: port rlm-agent fixes to rlm-kernel (F-2, F-4, P-3, F-6, B-2) |
| #74 | fix: extend RetrievalEngine to cloud models |
| #72 | feat: /system endpoint, MODULES.md injection & security bypass closure |
| #71 | feat: expose odoo_search_read as MCP tool (NRA-469) |
| #70 | feat(ci): add pytest job for odoo-mcp skill |
| #68 | fix: untrack AppleDouble ._* files |
| #67 | feat(webhook): add /webhook/odoo/system endpoint (NRA-487) |
| #65 | fix: test isolation in odoo-mcp (NRA-597) |

## Upgrade Notes

This is a backward-compatible minor release. No breaking changes.

- The RLM-Kernel MCP server is opt-in: configure `rlm-kernel` in your `skills` section to enable.
- The `/system` endpoint is available at `<gateway>/system` — no configuration needed.
- `odoo_search_read` is available as an MCP tool when the odoo-mcp skill is active.

## Issues

- Parent: NRA-3735 — Nueva release de OdooClaw
- RLM-Kernel: NRA-1330
- Qwen XML parser: NRA-3210

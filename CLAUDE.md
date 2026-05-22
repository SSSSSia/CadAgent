# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CadAgent is a FreeCAD workbench plugin that uses an LLM Agent (ReAct loop) to generate and modify 3D mechanical models from natural language descriptions. It runs inside FreeCAD as a PySide6 dock panel, communicates with any OpenAI-compatible LLM API, and executes generated Python code against FreeCAD's Part API. **Zero external Python dependencies** — all HTTP uses `urllib`.

## Running Tests

```bash
# All tests (these modules don't require FreeCAD imports)
pytest tests/

# Single test file
pytest tests/test_react_parser.py

# Single test function
pytest tests/test_token_budget.py::test_trim_preserves_system_prompt
```

Tests use `importlib.util.spec_from_file_location` to load modules that import FreeCAD, avoiding the FreeCAD dependency entirely. New tests for `react_parser`, `token_budget`, `chat_renderer`, `config`, and `session` should follow this same pattern.

## Architecture

### Agent Loop (state machine in `ui/panel.py`)

The core flow: user input → LLM reasoning → tool call → observe result → reason again → repeat.

The state machine alternates between two threads:
1. **Background QThread** (`_LlmCallThread`): streams LLM API responses via SSE
2. **Main thread**: executes tools (`exec()` for FreeCAD code) — required because FreeCAD API calls must be on the main thread

Signal/Slot connects them: `chunkReady` → streaming display, `streamDone` → route response, `error` → abort.

### Dual-Mode LLM Calling

On the first LLM response, the panel auto-detects the model's capability:
- **Tool Calling mode**: model returns native `tool_calls` in the API response → used directly
- **ReAct XML mode**: model returns `<tool name="...">...</tool>` tags in text → parsed by `react_parser.py` → converted to the same internal format

If `finish_reason == "stop"` on the first call with no tool_calls but with `<tool>` tags, it switches to ReAct mode and re-issues the system prompt. In ReAct mode, tool results are sent as user messages (not `role="tool"`) since the model doesn't understand that role.

### Panel Decomposition (`ui/panel.py`)

`AgentPanel` uses three mixins to split ~400 lines of logic across files:
- `ui/panel_ui.py` (`_PanelUIMixin`): widget creation, layout, styling
- `ui/panel_stream.py` (`_PanelStreamMixin`): chat bubble rendering, streaming display with 80ms batched updates via QTimer
- `ui/panel_session.py` (`_PanelSessionMixin`): session list, switching, and chat history restore

All mixins share state through `self` (the `AgentPanel` instance).

### Data Flow

```
User types → AgentPanel._on_send()
  → gather doc context (doc_analyzer)
  → set system prompt (prompts.py with {context})
  → AgentPanel._call_llm()
    → trim_messages() for token budget
    → _LlmCallThread (background) → call_llm_streaming()
    → streamDone signal → _handle_llm_response()
      → if tool_calls: _execute_tools() → dispatch_tool() → loop back to _call_llm()
      → if stop/no tools: _finish()
```

### Module Responsibilities

| Module | Role |
|--------|------|
| `InitGui.py` | FreeCAD workbench registration. Must use **local imports inside method bodies** because FreeCAD loads it via `exec()`. |
| `agent/controller.py` | Shared state container (session + result + mode) for the UI-driven agent loop. Not the loop itself. |
| `agent/tools.py` | Tool implementations. `dispatch_tool()` routes by name. Each tool takes JSON args string, returns result string. `execute_code` creates a snapshot before running. |
| `agent/tool_defs.py` | JSON Schema definitions for OpenAI function calling API. |
| `agent/prompts.py` | Two prompt sets: `AGENT_SYSTEM_PROMPT` (tool calling) and `REACT_SYSTEM_PROMPT` (XML tags). Both have `{context}` placeholder for document geometry. Legacy `SYSTEM_PROMPT_*` prompts for single-shot mode. |
| `core/llm_client.py` | Three entry points: `call_llm_with_tools()` (non-streaming), `call_llm_streaming()` (SSE generator), `generate_freecad_code()` (legacy single-shot). |
| `core/session.py` | `ChatSession` — ordered message list with system/user/assistant/tool roles. Serializes to/from dict. |
| `core/session_store.py` | JSON file persistence under `<FreeCAD user data>/CadAgent/sessions/`. |
| `core/doc_analyzer.py` | Extracts bounding box, volume, center of mass, cylindrical features, planar faces from FreeCAD documents as text for LLM context. |
| `core/snapshot.py` | `.FCStd` file-based undo stack (max 10). `take_snapshot()` before each `execute_code`, `restore_latest_snapshot()` to undo. |
| `core/token_budget.py` | Estimates tokens (CJK ~1.5 chars/token, English ~4 chars/token). `trim_messages()` keeps system prompt + last 6 messages, removes tool pairs atomically, summarizes middle history as fallback. |
| `core/logger.py` | Dual logging to FreeCAD.Console and `cadagent.log` file. Provides `log_info`, `log_warning`, `log_error`. |
| `ui/chat_renderer.py` | Markdown → HTML with placeholder-based pipeline (code blocks → tables → escape → inline formatting → restore). |
| `ui/settings_dialog.py` | Settings dialog (provider presets, API config, agent params, test connection, .env auto-save). Calls `config.reload()` on apply. Presets: SiliconFlow, DeepSeek, ZhipuAI, Qwen, Moonshot, OpenAI, Local Ollama, Custom. |

## Key Constraints

- **FreeCAD `exec()` scope trap**: `InitGui.py` is loaded via `exec()`. Top-level names (functions, classes) are NOT accessible inside method bodies. All method bodies must use local imports.

- **Main thread requirement**: All FreeCAD API calls (`doc.recompute()`, shape operations, GUI updates) must run on the main thread. The agent loop achieves this by running LLM calls in `QThread` and executing tools in signal handlers (main thread).

- **Standard library only**: FreeCAD bundles its own Python and does not guarantee third-party packages. Use `urllib` for HTTP, no `requests`, no `tiktoken`.

- **Path resolution**: The folder must be named `CadAgent` and placed in FreeCAD's `Mod/` directory. `sys.path` is manually patched in `InitGui.py`.

## Configuration

API credentials and model settings are in `.env` (copy from `.env.example`). Loaded by `core/config.py` at import time. Configurable at runtime via the Settings dialog (`ui/settings_dialog.py`) which calls `config.reload()`.

### Config Reload Pattern

`core/config.py` exports module-level constants. Downstream modules must use `import core.config as _config` and access via `_config.CONSTANT` (not `from core.config import CONSTANT`) so they always read the latest values after a reload. The `reload(new_values: dict)` function updates `os.environ` and re-derives all module-level constants.

All tuning constants are environment-variable overridable:

| Constant | Default | Env var |
|----------|---------|---------|
| `MAX_ITERATIONS` | 10 | `MAX_ITERATIONS` |
| `MAX_SNAPSHOTS` | 10 | `MAX_SNAPSHOTS` |
| `MAX_CONTEXT_TOKENS` | 24000 | `MAX_CONTEXT_TOKENS` |
| `LLM_TIMEOUT` | 180s | `LLM_TIMEOUT` |
| `MAX_TOKENS` | 4096 | `MAX_TOKENS` |
| `VALIDATE_VOLUME_THRESHOLD` | 0.01 | `VALIDATE_VOLUME_THRESHOLD` |
| `VALIDATE_DIMENSION_THRESHOLD` | 0.001 | `VALIDATE_DIMENSION_THRESHOLD` |

Supports any OpenAI-compatible provider (SiliconFlow, OpenAI, DeepSeek, ZhipuAI, Qwen, Moonshot, local Ollama).

## Language

The project is bilingual: README and ROADMAP are in Chinese (primary) and English. Code comments and docstrings are mixed Chinese/English. UI-facing strings in `panel.py` are in English.

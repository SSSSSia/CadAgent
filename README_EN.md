# CadAgent — FreeCAD CAD Agent Workbench

[中文](README.md)

An LLM Agent-powered FreeCAD workbench that generates and modifies 3D mechanical models through natural language descriptions.

## Features

- **ReAct Agent Loop** — LLM reasoning → generate FreeCAD Python code → execute → analyze results → self-correct, iterating until the design is complete
- **Natural Language Design** — Describe parts in plain text, and the Agent automatically plans and generates 3D models
- **Geometry Analysis** — The Agent automatically detects bounding boxes, volumes, cylinder features, and other geometric information
- **Design Validation** — Automatically checks model validity (zero volume, degenerate bounding boxes, etc.)
- **Error Self-Correction** — When code execution fails, the Agent reads the error traceback and automatically fixes and retries
- **Streaming Output** — Real-time display of the Agent's reasoning and code generation process
- **Undo/Rollback** — Automatic document snapshots before each code execution, with unlimited undo support
- **Session Management** — Multi-turn conversation history persists across FreeCAD sessions
- **Dual-Mode Support** — Automatically adapts to both Tool Calling and ReAct XML LLM calling modes
- **Token Budget Management** — Automatically trims history messages to prevent exceeding API context length limits

## Architecture

```
Agent Loop (ReAct):
  User Input → LLM Reasoning → Tool Call → Observation → Reason Again → ... → Done

Available Tools:
  execute_code      — Execute FreeCAD Python code to create/modify geometry
  analyze_geometry  — Extract geometry info from the current document (bounding box, volume, features)
  validate_design   — Validate the current model's integrity
  undo_last         — Undo the last code execution by restoring a document snapshot
```

## Installation

1. Rename this project folder to `CadAgent` and copy it to FreeCAD's `Mod/` directory:
   - **Windows**: `%APPDATA%\FreeCAD\Mod\` or `<FreeCAD installation directory>\Mod\`
   - **Linux**: `~/.FreeCAD/Mod/`
   - **macOS**: `~/Library/Preferences/FreeCAD/Mod/`

   Example final path: `.../Mod/CadAgent/InitGui.py`

2. Copy `.env.example` to `.env` and fill in your API configuration:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your provider's details (see `.env.example` for more examples):
   ```env
   API_BASE_URL=https://api.siliconflow.cn/v1
   API_KEY=sk-your-api-key-here
   MODEL_NAME=Pro/zai-org/GLM-5.1
   ```
   Any OpenAI-compatible API provider works: SiliconFlow, OpenAI, DeepSeek, ZhipuAI, local Ollama, etc.

3. Restart FreeCAD and select the **CadAgent** workbench from the dropdown menu.

## Usage

1. Switch to the **CadAgent** workbench — the chat panel opens automatically on the right
2. Describe the part you want to design, for example:
   - "Design a flanged cylinder, OD 200mm, flange radius 125mm, height 400mm, with 12 bolt holes"
   - "Create an L-bracket 100x50x30"
3. Click **Send** — the Agent will automatically reason, generate code, and iterate
4. The 3D model appears in the viewport in real-time; the Agent may perform multiple rounds of optimization
5. Click **Stop** at any time to interrupt the Agent loop

## Requirements

- FreeCAD >= 1.0 (with PySide6)
- Any LLM service with an OpenAI-compatible Chat Completions API (function calling support recommended for best results)

## File Structure

```
CadAgent/
├── Init.py               # FreeCAD module entry point
├── InitGui.py            # Workbench registration and panel loading
├── agent/
│   ├── __init__.py
│   ├── controller.py     # Agent controller (session state, run results)
│   ├── prompts.py        # System prompts (Agent mode + single-shot mode)
│   ├── react_parser.py   # ReAct XML tag parser
│   ├── tool_defs.py      # Tool JSON Schema definitions (LLM function calling)
│   └── tools.py          # Tool implementations (execute_code / analyze_geometry / validate_design / undo_last)
├── core/
│   ├── __init__.py
│   ├── config.py         # Environment config and .env loading
│   ├── llm_client.py     # LLM API client (OpenAI-compatible + streaming)
│   ├── session.py        # ChatSession management
│   ├── session_store.py  # Session disk persistence
│   ├── doc_analyzer.py   # Document geometry analysis (bounding box, volume, cylinder features)
│   ├── snapshot.py       # Document snapshot system (undo/rollback)
│   └── token_budget.py   # Token budget management
├── ui/
│   ├── __init__.py
│   ├── panel.py          # Chat-style dock panel + state machine Agent loop
│   └── chat_renderer.py  # Markdown → HTML rendering
├── .env.example          # API config template
├── .gitignore
├── LICENSE
├── README.md             # Chinese documentation
└── README_EN.md          # English documentation
```

## Technical Details

- **Thread Safety**: LLM API calls run in a background QThread; FreeCAD API operations (tool execution) return to the main thread via Signal/Slot
- **Standard Library Only**: HTTP requests use `urllib` — no external Python package dependencies
- **Compatibility**: Automatically detects whether the model supports Tool Calling; falls back to ReAct XML tag mode when not supported

## License

MIT License — see [LICENSE](LICENSE) for details.

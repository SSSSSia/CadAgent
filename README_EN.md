# CadAgent — FreeCAD CAD Agent Workbench

[中文](README.md)

An LLM Agent-powered FreeCAD workbench that generates and modifies 3D mechanical models through natural language descriptions.

## Features

- **CadQuery-Style Code Generation** — Built-in CQ-style chain API (`cq.Workplane("XY").box().cut()`). LLMs generate more accurate code with fewer errors. No CadQuery installation needed — a lightweight runtime translation layer calls FreeCAD Part API directly
- **ReAct Agent Loop** — LLM reasoning → generate CQ-style code → execute → analyze results → self-correct, iterating until the design is complete
- **Natural Language Design** — Describe parts in plain text, and the Agent automatically plans and generates 3D models
- **5 Agent Tools** — Code execution, undo/rollback, STEP/IGES/STL/OBJ export (with pre-export quality check), viewport capture with vision analysis, reference image analysis
- **Parametric Design** — Define named parameters (e.g. `OD = 200`), update them to automatically regenerate the model
- **Multi-Document Assembly** — Create parts in separate documents, then combine them into an assembly with positions
- **Enhanced Geometry Analysis** — Detects cylinders, cones, spheres, helix surfaces, hole patterns, symmetry, and wall thickness
- **CAD Quality Gate** — Automatic geometry quality check after each code execution (solid integrity, topology validity, dimension sanity). Blocks agent from finishing when quality fails.
- **CAD Helper Functions** — Built-in CQ-style Workplane API and legacy helpers (extract_solid, safe_fuse, safe_cut) to prevent common boolean operation errors
- **Visual Auxiliary Verification** — capture_view and analyze_image provide supplementary visual checks
- **Error Self-Correction** — When code execution fails, the Agent reads the error traceback and automatically fixes and retries; includes CQ-specific error hints (parameter order, import cadquery, etc.). Repeated errors automatically inject targeted repair advice
- **Progressive Context Injection** — Automatically injects phase-aware reference snippets based on current agent state (first execution, quality failure, repeated errors, approaching iteration limit), saving tokens and focusing LLM attention
- **Classified Quality Feedback** — When quality gate fails, injects specific fix instructions based on failure type (NO_SOLID, MULTI_SOLID, COMPOUND_SHAPE, etc.) instead of generic "fix geometry"
- **STL/OBJ Export** — Supports STEP/IGES/STL/OBJ export formats; STL is suitable for 3D printing. Automatic quality check before export
- **Smart Clarification Policy** — Automatically assumes reasonable defaults (clearance holes, wall thickness, origin position), only asks user when critical dimensions are missing
- **Streaming Output** — Real-time display of the Agent's reasoning and code generation process
- **Undo/Rollback** — Automatic document snapshots before each code execution, with unlimited undo support
- **Session Management** — Multi-turn conversation history persists across FreeCAD sessions
- **Dual-Mode Support** — Automatically adapts to both Tool Calling and ReAct XML LLM calling modes
- **Token Budget Management** — Automatically trims history messages to prevent exceeding API context length limits
- **Settings Dialog** — GUI for configuring API, model, and Agent parameters with 7 provider presets and connection testing

## Architecture

```
Agent Loop (ReAct):
  User Input → LLM Reasoning → Generate CQ-Style Code → Execute → Analyze → Self-Correct → ... → Done

Code Execution Flow:
  LLM generates: cq.Workplane("XY").box(10,20,30).cut(hole)
    → cq module translates: .box() → Part.makeBox(), .cut() → safe_cut()
    → FreeCAD viewport shows 3D model in real-time

Available Tools (5):
  execute_code       — Execute CadQuery-style code to create/modify geometry (with CAD quality gate)
  undo_last          — Undo the last code execution by restoring a document snapshot
  export_step        — Export document to STEP/IGES/STL/OBJ file (with pre-export quality check)
  capture_view       — Capture 3D viewport and analyze with vision model
  analyze_image      — Analyze a user-uploaded reference image
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
   Any OpenAI-compatible API provider works: SiliconFlow, OpenAI, DeepSeek, ZhipuAI, Qwen, Moonshot, local Ollama, etc.

   Alternatively, use **CadAgent Settings** from the FreeCAD menu or the **Settings** button in the panel to configure via GUI with provider presets and connection testing.

3. Restart FreeCAD and select the **CadAgent** workbench from the dropdown menu.

## Usage

1. Switch to the **CadAgent** workbench — the chat panel opens automatically on the right
2. Describe the part you want to design, for example:
   - "Design a flanged cylinder, OD 200mm, flange radius 125mm, height 400mm, with 12 bolt holes"
   - "Create an L-bracket 100x50x30"
3. Click **Send** — the Agent will automatically reason, generate CQ-style code, and iterate
4. The 3D model appears in the viewport in real-time; the Agent may perform multiple rounds of optimization
5. Click **Stop** at any time to interrupt the Agent loop
6. Click **Settings** or use the menu **CadAgent Settings** to change API configuration and Agent parameters at any time

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
│   ├── loop.py           # Pure-logic state machine (AgentLoop), returns LoopAction (with progressive context injection)
│   ├── prompts.py        # System prompts (CQ-style, Tool Calling + ReAct, with planning guidance and clarification policy)
│   ├── references.py     # Progressive reference snippet constants (auto-injected based on state)
│   ├── react_parser.py   # ReAct XML tag parser
│   ├── tool_defs.py      # Tool JSON Schema definitions (LLM function calling)
│   ├── tool_dispatch.py  # Registry-based tool routing and dispatch
│   ├── tools.py          # 5 tool implementations (with CQ module injection into sandbox)
│   ├── cq.py             # CadQuery-style chain API (Workplane class, runtime translation layer)
│   ├── cad_helpers.py    # CAD helper functions (extract_solid, safe_fuse, safe_cut, cq_show, etc.)
│   └── code_fixes.py     # Code pre-check, auto-fixes, error hints (including CQ-specific patterns)
├── core/
│   ├── __init__.py
│   ├── config.py         # Environment config, .env loading, runtime reload
│   ├── llm_client.py     # LLM API client (OpenAI-compatible + streaming)
│   ├── logger.py         # Dual logging (FreeCAD Console + file)
│   ├── session.py        # ChatSession management (with parameter table and parametric code)
│   ├── session_store.py  # Session disk persistence
│   ├── doc_analyzer.py   # Document geometry analysis (FreeCAD layer)
│   ├── geometry_analyzer.py # Pure-data geometry analysis (cones, spheres, helix, hole patterns, symmetry, wall thickness)
│   ├── quality.py        # CAD quality gate (structured pass/fail analysis, with "do not claim" guardrails)
│   ├── vision_client.py  # Vision model API client (screenshot and image analysis)
│   ├── text_utils.py     # Text processing utilities
│   ├── snapshot.py       # Document snapshot system (undo/rollback)
│   └── token_budget.py   # Token budget management
├── ui/
│   ├── __init__.py
│   ├── panel.py          # Chat-style dock panel (mixin composition + thread orchestration)
│   ├── panel_ui.py       # Panel UI construction (layouts, widgets, styling)
│   ├── panel_stream.py   # Streaming output rendering (chat bubbles, 80ms batched updates)
│   ├── panel_session.py  # Session list management (switching, history restore)
│   ├── panel_status.py   # Reactive status bar (elapsed time, iteration count, tool name display)
│   ├── chat_renderer.py  # Markdown → HTML rendering (with syntax highlighting)
│   ├── theme.py          # Light/dark mode theme colors
│   └── settings_dialog.py # Settings dialog (7 provider presets, connection test)
├── tests/                # 576 unit tests (no FreeCAD dependency)
├── .env.example          # API config template
├── .gitignore
├── LICENSE
├── README.md             # Chinese documentation
└── README_EN.md          # English documentation
```

## Technical Details

- **CQ Runtime Translation Layer** — `agent/cq.py` provides a ~320-line `Workplane` class whose methods directly call FreeCAD Part API. LLMs write CadQuery-style chain code; `box()`→`Part.makeBox()`, `cut()`→`safe_cut()`, `translate()` returns new objects (avoiding FreeCAD's in-place mutation trap)
- **Dual-Layer Architecture** — AgentLoop (pure-logic state machine) separated from UI thread orchestration, independently testable
- **Thread Safety** — LLM API calls run in a background QThread; FreeCAD API operations (tool execution) return to the main thread via Signal/Slot
- **Standard Library Only** — HTTP requests use `urllib` — no external Python package dependencies (CadQuery not installed)
- **Compatibility** — Automatically detects whether the model supports Tool Calling, falls back to ReAct XML tag mode; error hints support both CQ-style and native FreeCAD API patterns
- **576 Automated Tests** — Covering core modules (react_parser, token_budget, chat_renderer, config, session, code_fixes, agent_loop, tool_dispatch, quality, parametric, cq_workplane, etc.)

## License

MIT License — see [LICENSE](LICENSE) for details.

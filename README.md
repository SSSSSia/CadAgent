# AiSonarDesign — FreeCAD AI CAD Agent Workbench

An AI-powered FreeCAD workbench that uses an LLM agent (GLM-5.1) to generate and modify 3D mechanical models from natural language descriptions. Designed for sonar equipment and general mechanical parts.

## Features

- **Agent Mode** — Multi-turn ReAct agent loop with tool calling: the LLM reasons, writes FreeCAD Python code, executes it, analyzes the result, and self-corrects on errors
- **Natural Language Design** — Describe a part in plain text, get a 3D model
- **Geometry Analysis** — Agent inspects bounding box, volume, cylindrical features, and more
- **Self-Correction** — If code fails, the agent sees the error traceback and automatically retries
- **Session Management** — In-memory conversation history with context for multi-turn design

## Architecture

```
Agent Loop (ReAct):
  User input → LLM reasons → calls tool → observes result → reasons again → ...
  
Tools available to agent:
  - execute_code    — Run FreeCAD Python code to create/modify geometry
  - analyze_geometry — Extract geometry info from current document
  - validate_design  — Validate the current model
```

## Installation

1. Copy the `AiSonarDesign` folder into your FreeCAD `Mod/` directory:
   - **Windows**: `%APPDATA%/FreeCAD/Mod/` or `<FreeCAD_install>/Mod/`
   - **Linux**: `~/.FreeCAD/Mod/`
   - **macOS**: `~/Library/Preferences/FreeCAD/Mod/`

2. Copy `.env.example` to `.env` and fill in your API key:
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   ```env
   API_BASE_URL=https://api.siliconflow.cn/v1
   API_KEY=sk-your-api-key-here
   MODEL_NAME=Pro/zai-org/GLM-5.1
   ```

3. Restart FreeCAD and select the **AI CAD Agent** workbench from the workbench dropdown.

## Usage

1. Switch to the **AI CAD Agent** workbench — the dock panel opens on the right
2. Type a description of the part you want (e.g. "设计一个法兰筒体 OD 200mm，法兰 R=125")
3. Click **Send** — the agent will reason, generate code, and execute it iteratively
4. The 3D model appears in the viewport; the agent may do multiple rounds of refinement

## Requirements

- FreeCAD >= 1.0 (with PySide6)
- A valid API key for the configured LLM service (default: SiliconFlow with GLM-5.1)

## File Structure

```
AiSonarDesign/
├── Init.py              # FreeCAD module marker
├── InitGui.py           # Workbench registration & dock panel loading
├── AgentPanel.py        # Chat-style dock widget UI + state machine agent loop
├── agent_controller.py  # Agent core logic: system prompt, ReAct parsing, tool dispatch
├── agent_tools.py       # Tool implementations (execute_code / analyze_geometry / validate_design)
├── tool_definitions.py  # Tool JSON Schema definitions for LLM function calling
├── llm_engine.py        # LLM API integration (OpenAI-compatible API with tool calling)
├── session_manager.py   # ChatSession class for in-memory conversation management
├── doc_analyzer.py      # Document geometry analysis (bounding box, volume, cylindrical features)
├── .env.example          # API config template
├── .env                  # User config (gitignored, create from example)
├── log.md               # Key development notes and solved problems
├── DEVELOPMENT_PLAN.md  # Development roadmap (Phase 1–4)
├── .gitignore
├── LICENSE
└── README.md
```

## Development

See [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) for the full development roadmap and task breakdown.

## License

MIT License — see [LICENSE](LICENSE).

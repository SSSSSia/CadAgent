# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指导。

## 项目概述

CadAgent 是一个 FreeCAD 工作台插件，通过 LLM Agent（ReAct 循环）根据自然语言描述生成和修改 3D 机械模型。它在 FreeCAD 中以 PySide6 Dock 面板运行，与任何 OpenAI 兼容的 LLM API 通信，并将生成的 Python 代码交由 FreeCAD Part API 执行。**零外部 Python 依赖** — 所有 HTTP 请求使用 `urllib`。

## 运行测试

```bash
# 全部测试（这些模块不需要 FreeCAD 环境）
pytest tests/

# 单个测试文件
pytest tests/test_react_parser.py

# 单个测试函数
pytest tests/test_token_budget.py::test_trim_preserves_system_prompt
```

测试使用 `importlib.util.spec_from_file_location` 加载导入了 FreeCAD 的模块，从而完全避免 FreeCAD 依赖。为 `react_parser`、`token_budget`、`chat_renderer`、`config`、`session`、`code_fixes` 编写新测试时应遵循相同模式。

## 架构

### Agent 循环（`ui/panel.py` 中的状态机）

核心流程：用户输入 → LLM 推理 → 工具调用 → 观察结果 → 再次推理 → 循环。

状态机在两个线程间交替：
1. **后台 QThread**（`_LlmCallThread`）：通过 SSE 流式接收 LLM API 响应
2. **主线程**：执行工具（`exec()` 执行 FreeCAD 代码）— 因为 FreeCAD API 调用必须在主线程执行

通过 Signal/Slot 连接：`chunkReady` → 流式显示，`streamDone` → 路由响应，`error` → 中止。

### 双模式 LLM 调用

在首次 LLM 响应时，面板自动检测模型能力：
- **Tool Calling 模式**：模型在 API 响应中返回原生 `tool_calls` → 直接使用
- **ReAct XML 模式**：模型在文本中返回 `<tool name="...">...</tool>` 标签 → 由 `react_parser.py` 解析 → 转换为相同的内部格式

如果首次调用 `finish_reason == "stop"`、无 `tool_calls` 但含 `<tool>` 标签，则切换到 ReAct 模式并重新下发系统提示。ReAct 模式下工具结果以 user 消息发送（而非 `role="tool"`），因为模型不理解该角色。

### 面板拆分（`ui/panel.py`）

`AgentPanel` 使用四个 mixin 将逻辑分散到各文件：
- `ui/panel_ui.py`（`_PanelUIMixin`）：控件创建、布局、样式。提供 `_get_colors()` 供所有 mixin 获取主题色。
- `ui/panel_stream.py`（`_PanelStreamMixin`）：聊天气泡渲染、流式显示，通过 QTimer 80ms 批量更新
- `ui/panel_session.py`（`_PanelSessionMixin`）：会话列表、切换和历史恢复
- `ui/panel_status.py`（`_PanelStatusMixin`）：响应式状态栏，含耗时计时、迭代计数和工具名显示。状态：idle → thinking → executing_tool → stopping。

所有 mixin 通过 `self`（`AgentPanel` 实例）共享状态。

### 数据流

```
用户输入 → AgentPanel._on_send()
  → 收集文档上下文（doc_analyzer）
  → 设置系统提示（prompts.py，含 {context} 占位符）
  → AgentPanel._call_llm()
    → trim_messages() 裁剪 token 预算
    → _LlmCallThread（后台） → call_llm_streaming()
    → streamDone 信号 → _handle_llm_response()
      → 有 tool_calls：_execute_tools() → dispatch_tool() → 循环回 _call_llm()
      → stop / 无工具：_finish()
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `InitGui.py` | FreeCAD 工作台注册。方法体中**必须使用局部导入**，因为 FreeCAD 通过 `exec()` 加载此文件。 |
| `agent/controller.py` | 共享状态容器（session + result + mode），供 UI 驱动的 Agent 循环使用。本身不是循环。 |
| `agent/tools.py` | 工具实现。`dispatch_tool()` 按名称路由。每个工具接收 JSON 参数字符串，返回结果字符串。`execute_code` 执行 validate→fix→exec→hint 流水线（见下文）并在执行前创建快照。含参数化设计支持：参数提取、替换、`update_parameter`/`list_parameters` 工具。 |
| `agent/tool_defs.py` | OpenAI function calling API 的 JSON Schema 定义。 |
| `agent/code_fixes.py` | 弱模型兼容：`pre_validate_code()`（compile 检查）、`auto_fix_code()`（3 种模式：translate 赋值、布尔运算赋值、缺少 recompute）、`error_hint()`（按异常类型生成可操作提示）。无 FreeCAD 导入，可独立测试。 |
| `agent/prompts.py` | 两套提示词：`AGENT_SYSTEM_PROMPT`（Tool Calling）和 `REACT_SYSTEM_PROMPT`（XML 标签）。均含 `{context}` 占位符用于插入文档几何信息和参数表。另有弱模型变体和遗留的 `SYSTEM_PROMPT_*` 用于单次模式。 |
| `core/llm_client.py` | 三个入口：`call_llm_with_tools()`（非流式）、`call_llm_streaming()`（SSE 生成器）、`generate_freecad_code()`（遗留单次）。 |
| `core/session.py` | `ChatSession` — 有序消息列表，含 system/user/assistant/tool 角色。含 `parameters` 参数表和 `parametric_code` 参数化代码存储。支持序列化/反序列化。 |
| `core/session_store.py` | JSON 文件持久化，存储在 `<FreeCAD 用户数据>/CadAgent/sessions/` 下。 |
| `core/doc_analyzer.py` | 从 FreeCAD 文档提取包围盒、体积、质心、圆柱特征、平面等信息，以文本形式提供给 LLM 作为上下文。 |
| `core/snapshot.py` | 基于 `.FCStd` 文件的撤销栈（最多 10 个）。`take_snapshot()` 在每次 `execute_code` 前调用，`restore_latest_snapshot()` 用于撤销。 |
| `core/token_budget.py` | Token 估算（中文 ~1.5 字符/token，英文 ~4 字符/token）。`trim_messages()` 保留系统提示 + 最近 6 条消息，原子性移除工具调用对，必要时摘要中间历史。 |
| `core/logger.py` | 双通道日志：FreeCAD.Console + `cadagent.log` 文件。提供 `log_info`、`log_warning`、`log_error`。 |
| `ui/chat_renderer.py` | Markdown → HTML，基于占位符的管道（代码块 → 表格 → 转义 → 行内格式 → 还原）。 |
| `ui/theme.py` | `ThemeColors` 数据类，包含所有面板命名颜色。`get_theme_colors(palette)` 通过 `lightness() < 128` 检测亮/暗模式并返回对应配色。所有 panel mixin 通过 `self._get_colors()`（定义在 `_PanelUIMixin`）获取主题色。 |
| `ui/panel_status.py` | `_PanelStatusMixin` — 响应式状态栏，含 500ms 定时器、迭代计数器和按工具名显示。状态：idle、thinking、executing_tool、stopping。 |
| `ui/settings_dialog.py` | 设置对话框（提供商预设、API 配置、Agent 参数、连接测试、.env 自动保存）。Apply 时调用 `config.reload()`。预设：SiliconFlow、DeepSeek、ZhipuAI、Qwen、Moonshot、OpenAI、Local Ollama、Custom。 |

## 关键约束

- **FreeCAD `exec()` 作用域陷阱**：`InitGui.py` 通过 `exec()` 加载。顶层名称（函数、类）在方法体中**不可访问**。所有方法体必须使用局部导入。

- **主线程要求**：所有 FreeCAD API 调用（`doc.recompute()`、形状操作、GUI 更新）必须在主线程执行。Agent 循环通过在 `QThread` 中运行 LLM 调用、在信号处理函数（主线程）中执行工具来实现这一点。

- **仅标准库**：FreeCAD 自带 Python，不保证安装了第三方包。HTTP 使用 `urllib`，不能用 `requests`、`tiktoken`。

- **路径要求**：文件夹必须命名为 `CadAgent` 并放在 FreeCAD 的 `Mod/` 目录下。`sys.path` 在 `InitGui.py` 中手动修补。

### Exec 沙箱与弱模型流水线

`agent/tools.py` 中的 `execute_code` 工具通过安全流水线运行 LLM 生成的代码：

1. `strip_markdown(code)` — 移除 Markdown 围栏
2. `pre_validate_code(code)` — `compile()` 检查，在执行前拒绝语法错误
3. `auto_fix_code(code)` — 3 种自动修复：移除 `translate()` 的赋值（返回 None）、为布尔运算添加赋值（`cut`/`fuse`/`common`）、追加缺失的 `doc.recompute()`
4. `exec(code, namespace)` — 在受限沙箱中执行：
   - `SAFE_BUILTINS` 白名单（不含 `os`、`sys`、`subprocess`、`open`、`eval`、`exec`）
   - 预注入命名空间：`FreeCAD`、`Part`、`math`、`Gui`、`doc`（当前活动文档）、`Vector`、`App`、`pi`、`sin`、`cos`、`sqrt`
5. 出错时：`error_hint(exception, code)` 根据异常类型生成可操作的提示

修改 `SAFE_BUILTINS` 时，需同步更新 `agent/prompts.py` 告知 LLM 可用的内建函数。

## 配置

API 凭据和模型设置在 `.env` 文件中（从 `.env.example` 复制）。由 `core/config.py` 在导入时加载。可通过设置对话框（`ui/settings_dialog.py`）在运行时配置，Apply 时调用 `config.reload()`。

### 配置重载模式

`core/config.py` 导出模块级常量。下游模块必须使用 `import core.config as _config` 并通过 `_config.CONSTANT` 访问（而非 `from core.config import CONSTANT`），以确保重载后读取最新值。`reload(new_values: dict)` 函数更新 `os.environ` 并重新派生所有模块级常量。

所有可调常量均可通过环境变量覆盖：

| 常量 | 默认值 | 环境变量 |
|------|--------|----------|
| `MAX_ITERATIONS` | 10 | `MAX_ITERATIONS` |
| `MAX_SNAPSHOTS` | 10 | `MAX_SNAPSHOTS` |
| `MAX_CONTEXT_TOKENS` | 24000 | `MAX_CONTEXT_TOKENS` |
| `LLM_TIMEOUT` | 180s | `LLM_TIMEOUT` |
| `MAX_TOKENS` | 4096 | `MAX_TOKENS` |
| `VALIDATE_VOLUME_THRESHOLD` | 0.01 | `VALIDATE_VOLUME_THRESHOLD` |
| `VALIDATE_DIMENSION_THRESHOLD` | 0.001 | `VALIDATE_DIMENSION_THRESHOLD` |

支持所有 OpenAI 兼容提供商（SiliconFlow、OpenAI、DeepSeek、ZhipuAI、Qwen、Moonshot、本地 Ollama）。

## 语言

项目双语：README 和 ROADMAP 以中文为主、英文为辅。代码注释和 docstrings 中英混杂。`panel.py` 中的 UI 面向字符串为英文。

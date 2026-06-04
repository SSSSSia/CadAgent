# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指导。

## 项目概述

CadAgent 是一个 FreeCAD 工作台插件，通过 LLM Agent（ReAct 循环）根据自然语言描述生成和修改 3D 机械模型。它在 FreeCAD 中以 PySide6 Dock 面板运行，与任何 OpenAI 兼容的 LLM API 通信，并将生成的 CadQuery 风格 Python 代码交由 FreeCAD Part API 执行。**零外部 Python 依赖** — 所有 HTTP 请求使用 `urllib`，无需安装 CadQuery。

### 代码生成策略：CadQuery 风格 + FreeCAD 后端

LLM 生成 **CadQuery 风格的链式 API 代码**（`cq.Workplane("XY").box(L,W,H).cut(hole)`），通过内置的 `cq` 模块（运行时翻译层）在 FreeCAD 沙箱中直接执行。`cq.Workplane` 的每个方法内部调用 FreeCAD Part API，实现"LLM 写 CQ 语法，FreeCAD 执行几何"的混合方案。所有 FreeCAD 基础设施（文档模型、视口、快照、导出）继续工作不变。

## 运行测试

```bash
# 全部测试（这些模块不需要 FreeCAD 环境）
pytest tests/

# 单个测试文件
pytest tests/test_react_parser.py

# 单个测试函数
pytest tests/test_token_budget.py::test_trim_preserves_system_prompt
```

测试使用 `importlib.util.spec_from_file_location` 加载导入了 FreeCAD 的模块，从而完全避免 FreeCAD 依赖。部分测试（如 `test_parametric`）在测试文件中复制被测函数以避免导入 FreeCAD 依赖模块。为新模块编写测试时应遵循相同模式。

当前测试文件：`test_react_parser`、`test_token_budget`、`test_chat_renderer`、`test_config`、`test_session`、`test_code_fixes`、`test_geometry_analyzer`、`test_agent_loop`、`test_tool_dispatch`、`test_parametric`、`test_multi_doc_tools`、`test_snapshot`、`test_text_utils`、`test_vision_client`、`test_cad_helpers`、`test_quality`、`test_tool_quality_integration`、`test_import_naming`、`test_prompts`、`test_cq_workplane`（共 560 个测试）。

## 架构

### Agent 循环（双层拆分）

Agent 循环的核心逻辑拆分为两层：

1. **`agent/loop.py`（`AgentLoop`）** — 纯逻辑状态机，返回 `LoopAction` 指令。无 Qt、无 FreeCAD 依赖。拥有迭代计数、模式（auto/tool_calling/react）、停止标志、计时。不拥有线程或 UI。包含错误去重：连续相同错误自动附加 WARNING 提示 LLM 改变策略。

2. **`ui/panel.py`（`AgentPanel` + `_LlmCallThread`）** — 线程编排层。解读 `LoopAction` 并执行：启动后台 QThread 流式调用 LLM → 主线程执行工具（`exec()` 执行 CQ/FreeCAD 代码）→ 再次调用 LLM。

数据流：
```
用户输入 → AgentPanel._on_send()
  → 收集文档上下文（doc_analyzer）
  → AgentLoop.start() → LoopAction(CALL_LLM)
  → _LlmCallThread（后台） → call_llm_streaming()
  → streamDone 信号 → AgentLoop.handle_stream_done() → LoopAction
    → EXECUTE_TOOLS: _execute_tools() → dispatch_tool() → AgentLoop.handle_tool_results() → 循环
    → FINISH: _finish()
```

### CadQuery 风格代码生成（`agent/cq.py`）

`agent/cq.py` 提供 `Workplane` 类，实现 CadQuery 风格的链式 API，每个方法内部直接调用 FreeCAD Part API：

```python
# LLM 生成这样的代码:
body = (cq.Workplane("XY").circle(40).circle(35).extrude(90))
handle = cq.Workplane("XY").torus(25, 6).cut(cq.Workplane("XY").box(60, 26, 14))
body = body.union(handle)
cq_show(body, "Cup")
```

**翻译映射**：
| CQ 方法 | 内部 FreeCAD API | 说明 |
|---------|-----------------|------|
| `.box(L,W,H)` | `Part.makeBox(L,W,H)` + 居中偏移 | CQ 默认居中，FC 从角开始 |
| `.cylinder(H,R)` | `Part.makeCylinder(R,H)` + Z偏移 | **注意参数顺序**：CQ 是 (H,R)，FC 是 (R,H) |
| `.cone(r1,r2,H)` | `Part.makeCone(r1,r2,H)` + 偏移 | r1=底, r2=顶 |
| `.sphere(R)` | `Part.makeSphere(R)` | |
| `.torus(major,minor)` | `Part.makeTorus(major,minor)` | |
| `.circle(R).extrude(H)` | `Part.makeCylinder(R,H)` | 2D→3D |
| `.circle(R1).circle(R2).extrude(H)` | `make_hollow_cylinder(R1,R2,H)` | 同心圆→空心 |
| `.rect(L,W).extrude(H)` | `Part.makeBox(L,W,H)` | 矩形→立方体 |
| `.cut(other)` | `safe_cut(self, other)` | 自动提取 Solid |
| `.union(other)` | `safe_fuse(self, other)` | 自动提取 Solid |
| `.translate((x,y,z))` | `shape.copy()` + `.translate()` | **返回新对象**（非 in-place） |
| `.rotate(center,axis,angle)` | `shape.copy()` + `.rotate()` | 返回新对象 |

`cq_show(result, "Label")` 将 Workplane 或 shape 添加到 FreeCAD 文档并显示。

### 双模式 LLM 调用

在首次 LLM 响应时，`AgentLoop` 自动检测模型能力：
- **Tool Calling 模式**：模型在 API 响应中返回原生 `tool_calls` → 直接使用
- **ReAct XML 模式**：模型在文本中返回 `<tool name="...">...</tool>` 标签 → 由 `react_parser.py` 解析 → 转换为相同的内部格式

如果首次调用 `finish_reason == "stop"`、无 `tool_calls` 但含 `<tool>` 标签，则切换到 ReAct 模式并重新下发系统提示。ReAct 模式下工具结果以 user 消息发送（而非 `role="tool"`），因为模型不理解该角色。

### 工具注册与分发

`agent/tool_dispatch.py` 实现注册式路由：工具在 `agent/tools.py` 文件末尾通过 `register_tool(name, fn)` 调用注册，`dispatch_tool(name, args_json)` 查表调用。纯 Python，无 FreeCAD 依赖。

### 工具列表（5 个工具）

| 工具名 | 功能 |
|--------|------|
| `execute_code` | 执行 CadQuery 风格 Python 代码，含语法验证→执行→错误提示流水线。`cq` 模块预注入沙箱。支持可选 `document` 参数指定目标文档。执行后返回文档几何分析和拓扑警告。 |
| `undo_last` | 撤销上次 `execute_code`（从快照栈恢复） |
| `export_step` | 导出为 STEP/IGES 文件 |
| `capture_view` | 截取 FreeCAD 3D 视口截图，发送给视觉模型分析。用于建模后视觉验证。需要配置视觉模型（可选功能）。 |
| `analyze_image` | 分析用户上传的图片（参考图纸、草图、照片），提取尺寸和设计特征。需要配置视觉模型（可选功能）。 |

> **注**：项目从 12 工具精简到 3 工具（commit `ac10f22`），后新增 2 个视觉工具。几何分析功能已整合到 `execute_code` 的返回值中。

### 参数化设计

`agent/tools.py` 中的参数化模块通过模块级变量管理状态：
- `_PARAM_STORE`：存储 `UPPER_CASE = number` 形式的参数定义
- `_EXEC_NAMESPACE`：跨 `execute_code` 调用持久化的命名空间，LLM 可引用前次迭代定义的变量（包括 `Workplane` 对象和 FreeCAD 形状对象）
- `_PARAM_PATTERN`：匹配参数定义的正则表达式
- `ChatSession` 含 `parameters` 字段，支持会话级参数持久化

> **注**：`update_parameter` 和 `list_parameters` 工具已随工具精简被移除，但参数提取逻辑仍保留（`_extract_parameters`）。

### 面板拆分（`ui/panel.py`）

`AgentPanel` 使用四个 mixin 将逻辑分散到各文件：
- `ui/panel_ui.py`（`_PanelUIMixin`）：控件创建、布局、样式。提供 `_get_colors()` 供所有 mixin 获取主题色。包含图片上传📎按钮。
- `ui/panel_stream.py`（`_PanelStreamMixin`）：聊天气泡渲染、流式显示，通过 QTimer 80ms 批量更新
- `ui/panel_session.py`（`_PanelSessionMixin`）：会话列表、切换和历史恢复
- `ui/panel_status.py`（`_PanelStatusMixin`）：响应式状态栏，含耗时计时、迭代计数和工具名显示。状态：idle → thinking → executing_tool → stopping。

所有 mixin 通过 `self`（`AgentPanel` 实例）共享状态。

### 模块职责

| 模块 | 职责 |
|------|------|
| `InitGui.py` | FreeCAD 工作台注册。方法体中**必须使用局部导入**，因为 FreeCAD 通过 `exec()` 加载此文件。 |
| `agent/loop.py` | 纯逻辑状态机（`AgentLoop`），返回 `LoopAction` 指令。无 Qt/FreeCAD 依赖。 |
| `agent/controller.py` | 共享状态容器（session + result + mode），供 UI 驱动的 Agent 循环使用。本身不是循环。 |
| `agent/cq.py` | **CadQuery 风格链式 API**（`Workplane` 类），运行时翻译层。每个方法内部调用 FreeCAD Part API。提供 `.box()/.cylinder(H,R)/.circle().extrude()/.cut()/.union()/.translate()` 等 ~20 个方法。`cq_show()` 将结果添加到 FreeCAD 文档。零外部依赖（不安装 CadQuery）。 |
| `agent/cad_helpers.py` | 稳定的 CAD 辅助函数（`extract_solid`、`safe_fuse`、`safe_cut`、`make_hollow_cylinder`、`make_ring`、`make_box_handle`、`make_arc_handle`、`ensure_doc`、`cq_show`），注入 `execute_code` 命名空间供 LLM 生成的代码使用。 |
| `agent/tools.py` | 5 个工具实现（`_tool_execute_code`、`_tool_undo_last`、`_tool_export_step`、`_tool_capture_view`、`_tool_analyze_image`），在文件末尾通过 `register_tool(name, fn)` 注册。沙箱注入 `cq`、`Workplane`、`cq_show` 及现有 FreeCAD 模块。`execute_code` 执行 validate→exec→quality gate→hint 流水线。含 auto-fix 重试。 |
| `agent/tool_dispatch.py` | 纯路由：`register_tool()` 注册、`dispatch_tool()` 按名称查表调用。无 FreeCAD 依赖。 |
| `agent/tool_defs.py` | OpenAI function calling API 的 JSON Schema 定义（5 个工具）。`execute_code` 描述为 CadQuery 风格。 |
| `agent/code_fixes.py` | 代码验证与错误提示：`pre_validate_code()`（compile 检查）、`error_hint()`（含 CQ 特有错误模式：import cadquery、cylinder 参数顺序、pending extrude 为空、translate tuple 格式）。无 FreeCAD 导入。 |
| `agent/prompts.py` | 系统提示词：`AGENT_SYSTEM_PROMPT` 和 `REACT_SYSTEM_PROMPT` 均为 **CadQuery 风格**，指导 LLM 使用 `cq.Workplane` 链式 API。含 `{context}` 占位符。代码示例：杯子、法兰圆柱。遗留提示词（NEW/MODIFY/DERIVE/VARIANT）也已更新为 CQ 风格。 |
| `agent/react_parser.py` | 从 LLM 文本输出中解析 `<tool name="...">...</tool>` XML 标签，转为标准 tool_calls 格式。无 FreeCAD 依赖。 |
| `core/llm_client.py` | 三个入口：`call_llm_with_tools()`（非流式）、`call_llm_streaming()`（SSE 生成器）、`generate_freecad_code()`（遗留单次）。 |
| `core/vision_client.py` | 视觉模型 API 客户端。纯 urllib，无外部依赖。未配置时返回错误提示。 |
| `core/session.py` | `ChatSession` — 有序消息列表。支持序列化/反序列化。`session_store.py` 持久化到 `sessions/`。 |
| `core/doc_analyzer.py` | 从 FreeCAD 文档提取几何信息。依赖 `geometry_analyzer.py`。 |
| `core/quality.py` | CAD 质量门控：两层设计（纯分析 + FreeCAD 集成）。 |
| `core/geometry_analyzer.py` | 纯数据结构几何分析，无 FreeCAD 导入。 |
| `core/text_utils.py` | 文本工具：`strip_markdown()`。 |
| `core/snapshot.py` | 基于 `.FCStd` 文件的撤销栈。 |
| `core/token_budget.py` | Token 估算与消息裁剪。 |
| `core/logger.py` | 双通道日志。 |
| `ui/chat_renderer.py` | Markdown → HTML 渲染。 |
| `ui/theme.py` | 亮/暗模式主题配色。 |
| `ui/panel_status.py` | 响应式状态栏。 |
| `ui/settings_dialog.py` | 设置对话框（提供商预设、API 配置、Agent 参数、连接测试）。 |

## 关键约束

- **FreeCAD `exec()` 作用域陷阱**：`InitGui.py` 通过 `exec()` 加载。顶层名称（函数、类）在方法体中**不可访问**。所有方法体必须使用局部导入。

- **主线程要求**：所有 FreeCAD API 调用（`doc.recompute()`、形状操作、GUI 更新）必须在主线程执行。Agent 循环通过在 `QThread` 中运行 LLM 调用、在信号处理函数（主线程）中执行工具来实现这一点。

- **仅标准库**：FreeCAD 自带 Python，不保证安装了第三方包。HTTP 使用 `urllib`，不能用 `requests`、`tiktoken`。

- **路径要求**：文件夹必须命名为 `CadAgent` 并放在 FreeCAD 的 `Mod/` 目录下。`sys.path` 在 `InitGui.py` 中手动修补。

- **CQ 模块不是真正的 CadQuery**：`agent/cq.py` 是自己实现的薄包装层（~320 行），不依赖第三方 `cadquery` 包。API 语法参考 CadQuery 但不完全一致。

### Exec 沙箱与代码验证流水线

`agent/tools.py` 中的 `execute_code` 工具通过安全流水线运行 LLM 生成的代码：

1. `strip_markdown(code)` — 移除 Markdown 围栏
2. `_resolve_doc(doc_name)` — 解析目标文档（支持多文档）
3. `pre_validate_code(code)` — `compile()` 检查，在执行前拒绝语法错误
4. 自动创建文档：若无活动文档且代码引用 `doc.` 或含 `cq_show(`，自动插入 `newDocument()`
5. `take_snapshot()` — 执行前创建快照（支持撤销）
6. `exec(code, namespace)` — 在受限沙箱中执行：
   - `SAFE_BUILTINS` 白名单（不含 `os`、`sys`、`subprocess`、`open`、`eval`、`exec`）
   - 预注入命名空间：`FreeCAD`、`FreeCADGui`、`Part`、`math`、`doc`
   - **CQ 模块**：`cq`（含 `Workplane`）、`Workplane`、`cq_show`
   - CAD helper 函数：`extract_solid`、`safe_fuse`、`safe_cut`、`make_hollow_cylinder`、`make_ring`、`make_box_handle`、`make_arc_handle`、`ensure_doc`、`cq_show`
   - `_BUILTIN_NAMES` 保护注入名称不被 `_save_user_vars` 覆盖
   - 从 `_EXEC_NAMESPACE` 注入前次迭代的变量（含 `Workplane` 对象和 FreeCAD 形状对象）
7. 成功时：调用 `analyze_document()` 返回几何分析和拓扑警告
8. 参数提取：`_extract_parameters(code)` 提取 `UPPER_CASE = number` 参数定义
9. 出错时：`error_hint(exception, code)` 生成可操作提示（含 CQ 特有模式）

### Quality Gate（质量门控）

与之前一致，不受 CQ 切换影响：
1. `execute_code` 结果跟踪：解析 `OK:`/`FAIL:`/`ERROR:` 前缀
2. `_check_quality_gate()`：在 FINISH 前检查
3. 质量检查由 `core/quality.py` 在执行后自动调用

### Auto-fix 重试

与之前一致，不受 CQ 切换影响：
1. `restore_latest_snapshot()` 恢复快照
2. `_clean_stale_namespace_vars()` 清除失效引用（含 `Workplane` 对象检测）
3. 用修复后的代码重新执行
4. 重试仅一次

## 配置

API 凭据和模型设置在 `.env` 文件中（从 `.env.example` 复制）。由 `core/config.py` 在导入时加载。可通过设置对话框（`ui/settings_dialog.py`）在运行时配置，Apply 时调用 `config.reload()`。

### 配置重载模式

`core/config.py` 导出模块级常量。下游模块必须使用 `import core.config as _config` 并通过 `_config.CONSTANT` 访问（而非 `from core.config import CONSTANT`），以确保重载后读取最新值。

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

### 视觉模型配置（可选）

视觉模型使用独立的 API 配置，可与主 LLM 使用不同的提供商/模型。通过 `vision_enabled()` 检查是否已配置。未配置时视觉工具返回错误提示。

## 视觉系统

与之前一致，不受 CQ 切换影响。

## 语言

项目双语：README 和 ROADMAP 以中文为主、英文为辅。代码注释和 docstrings 中英混杂。`panel.py` 中的 UI 面向字符串为英文。

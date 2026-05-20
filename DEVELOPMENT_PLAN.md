# AI CAD Agent 开发任务书

> 项目路径：`D:\Download\FreeCAD\Mod\AiSonarDesign\`
> 模型：GLM-5.1 on SiliconFlow（已验证支持 Tool Calling）
> 框架：FreeCAD Mod 插件 + PySide6 + urllib（标准库）
> 日期：2026-05-20

---

## 当前进度总览

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 0 | Tool Calling 可行性验证 | 已完成 |
| Phase 1 | MVP Agent 循环 + 对话 UI + 多轮记忆 | 已完成（有 bug 待修） |
| Phase 2 | 会话持久化 + Token 管理 + 增强工具 | 未开始 |
| Phase 3 | 流式响应 + 撤销/回退 + 导出 | 未开始 |
| Phase 4 | 视觉检查 + 高级交互 | 未开始 |

### 已有文件清单（12 个源文件）

```
AiSonarDesign/
├── Init.py              (1行)   空文件，FreeCAD Mod 入口标识
├── InitGui.py           (75行)  Workbench 注册 + sys.path + Dock Panel 加载
├── AgentPanel.py        (514行) 聊天式 Dock Panel UI + 状态机 Agent 循环
├── agent_controller.py  (364行) Agent 核心逻辑 + System Prompt + ReAct 解析
├── agent_tools.py       (175行) 工具实现（execute_code / analyze_geometry / validate_design）
├── tool_definitions.py  (76行)  工具的 JSON Schema 定义
├── llm_engine.py        (273行) LLM API 调用（含旧版单次 generate_freecad_code）
├── session_manager.py   (110行) ChatSession 类（内存中的对话管理）
├── doc_analyzer.py      (85行)  文档几何分析（包围盒/体积/圆柱特征）
├── config.json          (5行)   API 配置（api_base_url / api_key / model_name）
├── config.example.json  (5行)   配置模板
└── log.md               (33行)  关键问题日志（4 个已解决问题）
```

---

## Phase 1 收尾（Bug 修复）

### 任务 1.1：修复 QTextBrowser 渲染问题（已部分修复）

**状态**：已应用 8 处编辑，需在 FreeCAD 中验证

**已做的修改**：
- `_append_user_msg()` / `_append_agent_msg()`：`<div>` → `<table>` 容器
- `_markdown_to_html()`：`background:` → `background-color:`、移除 `border-radius`、简化 `<hr>`
- 新增 step 6b：清理 block 元素间的 `<br>`

**验证步骤**：
1. 重启 FreeCAD，切换到 AI CAD Agent 工作台
2. 发送"你好"，检查 Agent 回复是否在统一的绿色背景气泡内
3. 发送"设计一个法兰筒体 OD 200mm"，检查工具调用日志和最终回复的排版
4. 检查列表项、代码块、表格是否正常渲染

**如果仍有问题**：根据具体截图进一步调整 CSS。

---

## Phase 2：会话持久化 + Token 管理 + 增强工具

### 任务 2.1：新建 `session_store.py` — 会话磁盘持久化

**目标**：会话保存到磁盘，FreeCAD 重启后可恢复历史对话。

**存储位置**：`<FreeCAD用户数据目录>/AiCadAgent/sessions/`
- 路径获取：`FreeCAD.getUserAppDataDir()` 返回类似 `C:/Users/Administrator/AppData/Roaming/FreeCAD/`
- 完整路径：`FreeCAD.getUserAppDataDir() + "/AiCadAgent/sessions/"`

**需要实现的类和函数**：

```python
# session_store.py

class SessionStore:
    """管理会话文件的磁盘读写。"""

    def __init__(self):
        """初始化存储目录。如果目录不存在则创建。"""
        # base_dir = os.path.join(FreeCAD.getUserAppDataDir(), "AiCadAgent", "sessions")
        # os.makedirs(base_dir, exist_ok=True)

    def save(self, session: ChatSession) -> str:
        """保存会话到 JSON 文件。
        文件名格式：{session_id}.json
        返回文件路径。"""

    def load(self, session_id: str) -> ChatSession | None:
        """按 session_id 加载会话。返回 ChatSession 或 None。"""

    def list_sessions(self) -> list[dict]:
        """列出所有已保存的会话，返回摘要列表。
        每项包含：session_id, created_at, summary, message_count
        按创建时间倒序排列。"""

    def delete(self, session_id: str) -> bool:
        """删除指定会话文件。"""

    def save_current_on_close(self, session: ChatSession):
        """FreeCAD 关闭时自动保存当前会话。"""
```

**文件格式**（每个 JSON 文件）：
```json
{
  "session_id": "a1b2c3d4e5f6",
  "created_at": "2026-05-20T14:30:00",
  "summary": "创建了法兰筒体 OD 200mm，含 12 个螺栓孔...",
  "document_state": "Current document: 'Design', objects:\n- 'Housing' ...",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "设计一个法兰筒体"},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "call_xxx", "content": "SUCCESS..."},
    ...
  ]
}
```

**集成点**（修改 `AgentPanel.py`）：
- `_on_send()`：发送前自动保存当前会话（如果已有会话）
- `_finish()`：Agent 完成时保存会话
- `_on_new_session()`：新建会话前保存当前会话
- `__init__()`：初始化 `SessionStore` 实例

**依赖**：`session_manager.py` 的 `ChatSession.to_dict()` / `ChatSession.from_dict()`（已实现）

---

### 任务 2.2：UI 增加历史会话列表

**目标**：在 Agent Panel 中增加一个下拉列表，用户可以查看和恢复历史会话。

**UI 布局变更**（在 `AgentPanel.py` 的 `_setup_ui()` 中）：

```
┌──────────────────────────────────────┐
│ AI CAD Agent                  [≡][×] │
├──────────────────────────────────────┤
│ [▼ 历史会话: 法兰筒体 05-20 14:30  ] │  ← 新增：QComboBox
├──────────────────────────────────────┤
│                                      │
│ （对话记录区域，不变）                │
│                                      │
├──────────────────────────────────────┤
│ [输入框]  [发送]                      │
│ [停止]  [新会话]                      │
│ Status: ...                          │
└──────────────────────────────────────┘
```

**实现细节**：

1. 在 `_setup_ui()` 中，`chat_display` 上方添加一个 `QComboBox`：
   ```python
   self.session_combo = QtWidgets.QComboBox()
   self.session_combo.addItem("当前会话")
   self.session_combo.currentIndexChanged.connect(self._on_session_selected)
   main_layout.addWidget(self.session_combo)
   ```

2. 新增方法 `_refresh_session_list()`：
   - 调用 `SessionStore.list_sessions()` 获取会话列表
   - 填充 `session_combo`，每项显示：`{summary 前 30 字} | {created_at 日期}`
   - 第一项始终是"当前会话"

3. 新增方法 `_on_session_selected(index)`：
   - `index == 0`：不操作（当前会话）
   - `index > 0`：加载对应 `session_id` 的会话
   - 恢复 `self._session` 为加载的 ChatSession
   - 恢复对话记录显示（从 messages 重建 HTML）
   - 切换会话前保存当前会话

4. 新增方法 `_restore_chat_display(session)`：
   - 遍历 `session.messages`，根据 `role` 调用 `_append_user_msg` / `_append_agent_msg` / `_append_tool_msg`
   - 跳过 `system` 和 `tool` 消息（仅显示 user/assistant 关键消息）

**注意事项**：
- 切换会话时，如果 Agent 正在运行，应该先停止
- 恢复历史会话后，用户可以继续在该会话中输入（Agent 会看到之前的上下文）

---

### 任务 2.3：新建 `token_budget.py` — Token 预算管理

**目标**：防止对话历史过长导致 API 超限或成本过高。

**背景**：8 轮 Agent 循环可能产生 20+ 条消息（每轮有 assistant + tool + tool_result），每次都全量发送给 API。GLM-5.1 的 context window 约 32K tokens，工具执行的输出（文档状态文本、traceback）可能很长。

**需要实现的函数**：

```python
# token_budget.py

MAX_CONTEXT_TOKENS = 24000  # 留 8K 给输出和系统 prompt

def estimate_tokens(text: str) -> int:
    """粗估 token 数。
    规则：英文约 4 字符/token，中文约 1.5 字符/token。
    这是一个粗估，不需要精确。"""

def trim_messages(messages: list[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> list[dict]:
    """裁剪消息列表，使其不超过 token 预算。

    裁剪策略（从旧到新）：
    1. 保留第一条消息（system prompt）— 永不裁剪
    2. 保留最后 6 条消息（最近的交互）— 永不裁剪
    3. 中间的 tool_result 消息：截断到 200 字符
    4. 中间的 assistant 消息：截断 content 到 300 字符
    5. 如果仍超预算：删除中间的 tool + tool_result 对
    6. 不删除 user 消息（用户的原始指令很重要）

    返回裁剪后的消息列表（不修改原列表）。
    """

def summarize_old_messages(messages: list[dict]) -> str:
    """将一批旧消息压缩为一条摘要。
    格式：'之前的设计历史：执行了 3 轮代码，创建了法兰筒体，添加了螺栓孔...'
    用这条摘要替换原来的多条消息。"""
```

**集成点**（修改 `AgentPanel.py` 的 `_call_llm()`）：
```python
def _call_llm(self):
    # ... 现有逻辑 ...
    messages = self._controller.session.get_messages()
    # 新增：裁剪消息
    from token_budget import trim_messages
    messages = trim_messages(messages)
    # 传给 LLM
    self._llm_thread = _LlmCallThread(messages, tools)
```

**验证步骤**：
1. 发送多轮指令，观察日志中消息数量增长
2. 检查裁剪后消息数是否被控制住
3. 确认 system prompt 和最近的交互不被裁剪

---

### 任务 2.4：增强 `doc_analyzer.py` — 更多几何属性

**目标**：为 Agent 提供更丰富的几何信息，提高设计成功率。

**当前输出**：
```
Current document: 'Design', objects:
- 'Housing' (type: Part::Feature)
  Bounding box: X[0~200] Y[0~200] Z[0~380]
  Overall: 200.0 x 200.0 x 380.0 mm
  Volume: 12345678.9 mm3
  Detected cylindrical features:
    - Cylinder R=100.0mm, center=(0,0,0), axis=(0,0,1.00)
```

**需要新增的属性**：
- 面数（Faces）、边数（Edges）、顶点数（Vertexes）
- 质心坐标（`shape.CenterOfMass`）
- 形状类型检测：是否为纯圆柱体、纯长方体、组合体
- 平面特征检测：检测大的平面（法兰面、底面等）

**修改 `_describe_shape()` 函数**：
```python
def _describe_shape(shape) -> str:
    lines = []
    # ... 现有的 bounding box, volume, cylinders ...

    # 新增：拓扑统计
    lines.append(f"  Faces: {len(shape.Faces)}, Edges: {len(shape.Edges)}, Vertices: {len(shape.Vertexes)}")

    # 新增：质心
    com = shape.CenterOfMass
    lines.append(f"  Center of mass: ({com.x:.1f}, {com.y:.1f}, {com.z:.1f})")

    # 新增：形状类型推断
    shape_type = _infer_shape_type(shape)
    if shape_type:
        lines.append(f"  Inferred type: {shape_type}")

    return lines
```

**新增辅助函数 `_infer_shape_type()`**：
- 如果只有一个 Solid 且只有一个圆柱面 → "Solid cylinder"
- 如果只有一个 Solid 且所有面都是平面 → "Box"
- 如果有多个 Solid → "Multi-solid assembly"
- 如果面数 > 20 → "Complex boolean result"

---

### 任务 2.5：Agent System Prompt 优化

**目标**：根据实际测试中 Agent 的表现优化 System Prompt。

**当前问题**（根据测试观察）：
1. Agent 有时会重复相同的错误代码
2. Agent 在复杂设计中不善于分步执行
3. Agent 的代码有时会忘记 `doc.recompute()`

**优化方向**（修改 `agent_controller.py` 中的 `AGENT_SYSTEM_PROMPT`）：

1. 增加错误案例示例：
   ```
   COMMON MISTAKES — DO NOT repeat:
   - cut()/fuse() returns NEW shape, must assign: result = a.cut(b)
   - translate() modifies IN-PLACE, returns None: shape.translate(v) not shape = shape.translate(v)
   - OCCError: try smaller tolerances or different boolean order
   - Always check shape.isValid() after boolean ops
   ```

2. 增加分步指导：
   ```
   For complex designs, break into steps:
   Step 1: Create main body
   Step 2: Add secondary features
   Step 3: Subtract holes/cuts
   Call execute_code once per step, then analyze_geometry to verify.
   ```

3. 强化 `doc.recompute()` 约束

**验证方式**：
- 用之前失败的设计案例重新测试
- 比较优化前后的成功率

---

## Phase 3：流式响应 + 撤销 + 导出

### 任务 3.1：流式响应（Streaming）

**目标**：Agent 思考过程逐字显示，而不是等全部完成后才显示。

**API 支持**：SiliconFlow 的 API 支持 `stream: true` 参数，返回 SSE (Server-Sent Events)。

**实现方案**：

1. 修改 `call_llm_with_tools()` 支持流式模式：
   ```python
   def call_llm_streaming(messages, tools=None, temperature=0.1):
       """流式调用 API，yield 每个 chunk。"""
       payload = {..., "stream": True}
       req = urllib.request.Request(...)
       with urllib.request.urlopen(req, timeout=180) as resp:
           for line in resp:
               line = line.decode("utf-8").strip()
               if not line.startswith("data: "):
                   continue
               data = line[6:]
               if data == "[DONE]":
                   break
               chunk = json.loads(data)
               yield chunk
   ```

2. 修改 `_LlmCallThread`：
   - 改为流式接收
   - 通过 Signal 实时发射增量文本
   - AgentPanel 接收后追加到 chat_display

3. UI 新增信号：
   ```python
   class _LlmCallThread(QtCore.QThread):
       chunkReady = QtCore.Signal(str)   # 新增：增量文本
       responseReady = QtCore.Signal(dict)
       error = QtCore.Signal(str)
   ```

4. UI 处理：
   - `_on_chunk(text)`：实时追加文本到当前 agent 消息气泡
   - 需要追踪"当前正在生成的消息"，动态更新

**挑战**：
- 流式模式下的 tool_calls 需要累积拼接参数
- QTextBrowser 的实时追加可能有性能问题
- ReAct 模式下需要完整内容才能解析 `<tool>` 标签

---

### 任务 3.2：执行前快照 + 撤销

**目标**：Agent 执行代码前保存文档状态，用户可以撤销 Agent 的操作。

**实现方案**：

1. 在 `agent_tools.py` 的 `_tool_execute_code()` 中，执行前保存快照：
   ```python
   def _snapshot_document(doc) -> str:
       """保存文档快照到临时文件，返回快照路径。"""
       import tempfile
       path = os.path.join(tempfile.gettempdir(), f"ai_agent_snap_{doc.Name}.FCStd")
       doc.saveAs(path)
       return path
   ```

2. 新增工具 `undo_last`：
   ```python
   def _tool_undo_last(args_json):
       """撤销上一步操作，恢复到快照状态。"""
       # 关闭当前文档，打开快照文件
   ```

3. 在 `tool_definitions.py` 中注册新工具

4. UI 新增撤销按钮

**注意事项**：
- `doc.saveAs()` 会改变文档的文件路径，需要用 `doc.FileName` 追踪
- 快照文件应定期清理（超过 10 个时删除最旧的）

---

### 任务 3.3：导出工具（STEP / STL）

**目标**：Agent 可以导出设计为 STEP 或 STL 格式。

**新增工具**：

```python
# agent_tools.py

def _tool_export_model(args_json: str) -> str:
    """导出当前模型为 STEP 或 STL 文件。"""
    args = json.loads(args_json)
    fmt = args.get("format", "step")  # "step" | "stl"
    path = args.get("path", "")       # 输出路径

    doc = FreeCAD.ActiveDocument
    if not doc:
        return "ERROR: No active document."

    if not path:
        # 默认保存到桌面
        path = os.path.join(os.path.expanduser("~"), "Desktop", f"{doc.Name}.{fmt}")

    import Import  # FreeCAD 内置的 STEP 导出模块
    import Mesh    # FreeCAD 内置的 STL 导出模块

    if fmt == "step":
        Import.export(doc.Objects, path)
    elif fmt == "stl":
        mesh_obj = Mesh.Mesh([o.Shape.tessellate(0.1) for o in doc.Objects if hasattr(o, 'Shape')])
        mesh_obj.write(path)

    return f"SUCCESS: Exported to {path}"
```

**在 `tool_definitions.py` 中注册**：
```python
{
    "type": "function",
    "function": {
        "name": "export_model",
        "description": "Export current design as STEP or STL file",
        "parameters": {
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["step", "stl"]},
                "path": {"type": "string", "description": "Output file path (optional)"}
            },
            "required": ["format"]
        }
    }
}
```

---

## Phase 4：高级功能（未来）

### 任务 4.1：Visual Inspect 工具

**依赖**：需要多模态模型支持（GPT-4V / Claude Vision 等）

**目标**：Agent 可以截图当前 3D 视图并分析。

**实现方案**：
```python
def _tool_visual_inspect(args_json):
    """截取 FreeCAD 3D 视图并调用多模态模型分析。"""
    view = Gui.activeDocument().activeView()
    # QScreen grab → save as PNG → base64 encode → call vision API
```

**当前限制**：GLM-5.1 不支持图片输入。需要后续切换到支持视觉的模型。

---

### 任务 4.2：参数化设计模板

**目标**：常用零件（法兰、筒体、支架等）预置参数化模板，Agent 基于模板生成。

**实现方案**：
- `templates/` 目录存放 JSON 模板定义
- 每个模板包含：参数列表、代码骨架、约束条件
- Agent 先选择匹配的模板，再填入参数

---

### 任务 4.3：多文档协作

**目标**：Agent 同时操作多个 FreeCAD 文档（如装配体）。

---

## 项目重命名（随时可做）

**当前**：目录名 `AiSonarDesign`，类名 `AiCadAgentWorkbench`

**目标**：目录名 `AiCadAgent`，统一命名

**需要修改的地方**：
1. 重命名目录：`AiSonarDesign/` → `AiCadAgent/`
2. `InitGui.py` 第 10-14 行：路径中的 `AiSonarDesign` → `AiCadAgent`
3. `config.json` 无需改（不含插件名）

**注意**：必须在 FreeCAD 未运行时操作，否则文件被锁定。

---

## 依赖关系图

```
Phase 1 收尾
  └→ 无依赖，可独立验证

Phase 2
  ├→ 2.1 session_store.py（无依赖）
  ├→ 2.2 UI 历史会话（依赖 2.1）
  ├→ 2.3 token_budget.py（无依赖）
  ├→ 2.4 doc_analyzer 增强（无依赖）
  └→ 2.5 Prompt 优化（无依赖）

  建议顺序：2.1 → 2.2 → 2.3 → 2.4 → 2.5

Phase 3
  ├→ 3.1 流式响应（依赖 Phase 2.3 token 管理）
  ├→ 3.2 撤销/回退（无依赖）
  └→ 3.3 导出工具（无依赖）

Phase 4
  └→ 4.1 视觉检查（依赖多模态模型）
```

---

## 开发优先级建议

```
高优先（核心体验）：
  1. Phase 1 收尾 — 验证 UI 渲染修复
  2. 任务 2.1 — session_store.py 会话持久化
  3. 任务 2.2 — UI 历史会话列表

中优先（质量提升）：
  4. 任务 2.5 — Prompt 优化（提高设计成功率）
  5. 任务 2.3 — token_budget.py（防止 API 超限）
  6. 任务 2.4 — doc_analyzer 增强

低优先（锦上添花）：
  7. 任务 3.3 — 导出 STEP/STL
  8. 任务 3.2 — 撤销/回退
  9. 任务 3.1 — 流式响应
  10. Phase 4 — 高级功能
```

---

## 测试用例

### 基础 Agent 测试

| 测试 | 输入 | 预期 |
|------|------|------|
| 简单圆柱 | "创建一个 R=50 H=100 的圆柱体" | 1 轮完成，1 个圆柱体 |
| 法兰筒体 | "设计法兰筒体 OD 200mm，法兰 R=125" | 2-4 轮完成，含筒体+法兰+螺栓孔 |
| 错误自纠 | 故意给模糊描述 | Agent 应自动分析+修正 |
| 多轮对话 | 先"创建圆柱" → 再"加一个孔" | 第二轮应理解第一轮的结果 |

### 会话持久化测试

| 测试 | 操作 | 预期 |
|------|------|------|
| 自动保存 | Agent 完成设计后关闭 FreeCAD | 会话文件已写入磁盘 |
| 恢复会话 | 重新打开 FreeCAD，选择历史会话 | 对话记录完整恢复 |
| 继续对话 | 恢复会话后输入新指令 | Agent 理解历史上下文 |
| 会话列表 | 创建 3 个会话 | 下拉列表显示 3 个条目 |

### Token 管理测试

| 测试 | 操作 | 预期 |
|------|------|------|
| 短对话 | 2 轮简单对话 | 不裁剪 |
| 长对话 | 8 轮复杂设计 | 中间消息被裁剪，最近消息保留 |
| System Prompt | 任何情况 | system prompt 不被裁剪 |

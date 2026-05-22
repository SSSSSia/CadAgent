# CadAgent 改进计划

> 基于对当前代码库（~2,400 行，27 个 Python 文件）的全面审查，梳理出现存问题、功能缺失和架构改进方向。
> ROADMAP.md 中 Phase 5.1（集中配置）、5.2（消除重复）、5.3（错误处理）、5.5（UI 拆分）已完成，本文档在此基础上展开。

---

## 一、现状评估

### 已完成

| ROADMAP 条目 | 状态 | 说明 |
|-------------|------|------|
| 5.1 集中配置管理 | ✅ | 所有常量收归 `core/config.py`，支持环境变量覆盖 |
| 5.2 消除代码重复 | ✅ | `strip_markdown` 统一、`_make_request` 抽取 |
| 5.3 错误处理改进 | ✅ | 引入 `core/logger.py`，替换裸 `except` |
| 5.4 单元测试 | ✅ | 5 个测试文件覆盖核心模块（react_parser、token_budget、chat_renderer、config、session） |
| 5.5 UI 拆分 | ✅ | panel.py 拆为 4 个文件（panel.py + panel_ui.py + panel_stream.py + panel_session.py） |

### 未完成

| ROADMAP 条目 | 状态 | 说明 |
|-------------|------|------|
| 6.1 设置面板 | ❌ | 仍需手动编辑 .env |
| 6.2 代码高亮 | ❌ | 纯 `<pre>` 块 |
| 6.3 工作台图标 | ⚠️ | 已有 SVG 资源，InitGui.py 已支持加载，但图标设计待确认 |
| 6.4 进度可视化 | ❌ | 仅显示 "Agent thinking..." |
| 7.x ~ 9.x | ❌ | 智能体增强、视觉智能、工程化均未启动 |

---

## 二、代码质量问题

### BUG-1：Agent 循环缺少并发保护

**严重程度**：高
**位置**：`ui/panel.py:_on_send()`

`_on_send()` 没有检查 `_llm_thread.isRunning()`。虽然 `_set_running(True)` 会禁用 Send 按钮，但 Qt 信号处理不是原子操作——快速操作仍可能突破保护。

**方案**：
```python
def _on_send(self):
    if self._llm_thread and self._llm_thread.isRunning():
        self._append_system_msg("Agent is still running. Please wait.")
        return
    # ... 原有逻辑
```

---

### BUG-2：LLM SSE 流截断时静默丢失数据

**严重程度**：高
**位置**：`core/llm_client.py:104-116`、`ui/panel.py:_LlmCallThread.run()`

当网络中断或服务端提前关闭 SSE 连接时：
- `call_llm_streaming()` 生成器静默结束，不报错
- `_LlmCallThread` 收到的 `tool_calls` 可能 arguments 不完整（JSON 截断）
- 后续 `json.loads(args)` 在 `dispatch_tool` 中抛异常

**方案**：
1. 在 `_LlmCallThread.run()` 中检测不完整的 `tool_calls`（arguments 不是合法 JSON）
2. 截断时 `self.error.emit("Stream interrupted: incomplete tool_calls")`
3. `call_llm_streaming()` 在非 `[DONE]` 结束时记录警告

```python
# _LlmCallThread.run() 末尾增加
for tc in tool_calls:
    try:
        json.loads(tc["function"]["arguments"])
    except json.JSONDecodeError:
        self.error.emit("Stream interrupted: incomplete tool call arguments")
        return
```

---

### BUG-3：会话切换后无法继续 Agent 对话

**严重程度**：中
**位置**：`ui/panel_session.py:_on_session_selected()`

切换到历史会话后 `self._controller = None`，且没有恢复 `_mode` 和 `_iteration`。用户看到历史记录，但发送新消息时 `_on_send()` 会创建新的 `AgentController`，导致上下文断裂。

**方案**：
- 切换会话时重建 `AgentController`，复用已加载的 session
- 将 `_mode` 持久化到 `ChatSession` 中（添加 `last_mode` 字段）
- 恢复会话时恢复 mode，避免每次都重新检测

---

### BUG-4：InitGui.py 路径计算重复 3 次

**严重程度**：低
**位置**：`InitGui.py:10-15`、`InitGui.py:31-36`、`InitGui.py:43-48`

相同的路径查找逻辑（`getUserAppDataDir` → fallback `getHomePath`）在模块级、`__init__`、`Initialize` 中各写了一遍。

**方案**：提取为模块级函数：
```python
def _cadagent_dir():
    d = os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "CadAgent")
    if not os.path.isdir(d):
        d = os.path.normpath(os.path.join(FreeCAD.getHomePath(), "Mod", "CadAgent"))
    return d
```

---

### CODE-1：`exec()` 无沙箱限制

**严重程度**：中
**位置**：`agent/tools.py:58`

`exec(code, namespace)` 中 `__builtins__` 完全开放，LLM 幻觉或恶意 prompt 可能执行 `os.system()`、`shutil.rmtree()` 等危险操作。

**方案**：构建受限 `__builtins__` 白名单：
```python
SAFE_BUILTINS = {
    "print": print, "range": range, "len": len, "int": int,
    "float": float, "str": str, "list": list, "dict": dict,
    "abs": abs, "min": min, "max": max, "round": round,
    "enumerate": enumerate, "zip": zip, "True": True, "False": False,
    "None": None, "isinstance": isinstance, "type": type,
}
namespace = {
    "FreeCAD": FreeCAD, "Part": Part, "math": math, "Gui": Gui,
    "__builtins__": SAFE_BUILTINS,
}
```

需要在 prompt 中明确告知 Agent 可用的内建函数，避免合法代码被误拦。

---

### CODE-2：`session_store.py` 未使用统一日志

**严重程度**：低
**位置**：`core/session_store.py:32-38`

`_print_warning()` 是独立的日志函数，项目已有 `core/logger.py` 提供统一的 `log_warning`。

**方案**：直接替换为 `from core.logger import log_warning`，删除 `_print_warning` 函数。

---

### CODE-3：快照磁盘残留无清理

**严重程度**：低
**位置**：`core/snapshot.py`

`_snapshot_stack` 是内存变量，FreeCAD 异常退出后栈清空，但 `.FCStd` 文件仍留在磁盘。下次启动时没有清理旧快照的机制，可能逐渐积累。

**方案**：在 `_get_snapshot_dir()` 或 `take_snapshot()` 首次调用时，清理超过 24 小时的孤立快照文件：
```python
def _cleanup_orphan_snapshots():
    snap_dir = _get_snapshot_dir()
    if not os.path.isdir(snap_dir):
        return
    now = time.time()
    for f in os.listdir(snap_dir):
        path = os.path.join(snap_dir, f)
        if not f.endswith(".FCStd"):
            continue
        try:
            if now - os.path.getmtime(path) > 86400:  # 24h
                os.remove(path)
        except OSError:
            pass
```

---

### CODE-4：`chat_renderer.py` 不支持 Markdown 链接

**严重程度**：低
**位置**：`ui/chat_renderer.py`

`[text](url)` 格式没有被解析。LLM 输出中的链接显示为原始文本。

**方案**：在步骤 5（bold/code 之后）增加链接解析：
```python
text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
```

---

## 三、网络健壮性

### NET-1：LLM API 请求无重试

**严重程度**：高
**位置**：`core/llm_client.py`

`urllib.request.urlopen()` 在超时、5xx 错误、网络抖动时直接抛异常，整个 Agent 循环终止。用户需要重新发送请求，之前的迭代上下文虽然保存在 session 中，但当前执行已中断。

**方案**：在 `call_llm_streaming()` 和 `call_llm_with_tools()` 中加入重试逻辑：

```python
from core.config import LLM_TIMEOUT
MAX_RETRIES = 2
RETRY_DELAY = 2  # seconds

def _request_with_retry(request, max_retries=MAX_RETRIES):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(request, timeout=LLM_TIMEOUT)
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = e
            if attempt < max_retries:
                import time
                time.sleep(RETRY_DELAY * (attempt + 1))
    raise last_error
```

重试配置加入 `core/config.py`：
```python
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))
LLM_RETRY_DELAY = int(os.environ.get("LLM_RETRY_DELAY", "2"))
```

---

### NET-2：SSE 流没有 keep-alive 和超时检测

**严重程度**：中
**位置**：`core/llm_client.py:103-116`

当前 `for raw_line in resp:` 会一直阻塞等待服务端数据。如果服务端挂起（半开连接），客户端永远阻塞，Agent 无法被停止。

**方案**：
- 设置 socket 超时：`resp.fp._sock.settimeout(LLM_TIMEOUT)`
- 或在 `_LlmCallThread.run()` 中使用 `isInterruptionRequested()` 定期检查（当前已有，但被 `for raw_line in resp` 阻塞时无法生效）

---

## 四、用户体验改进

### UX-1：多行文本输入

**严重程度**：高
**位置**：`ui/panel_ui.py:65`

当前使用 `QLineEdit`（单行），复杂设计描述（如 "设计一个法兰筒体，外径 200mm，法兰半径 125mm，高度 400mm，带 12 个螺栓孔"）输入不便。

**方案**：替换为 `QTextEdit` + 快捷键过滤：
- Enter 发送（与当前行为一致）
- Shift+Enter 换行
- 自适应高度（1~5 行）

```python
class _ChatInput(QtWidgets.QTextEdit):
    """Multi-line input: Enter sends, Shift+Enter newline."""
    sendRequested = QtCore.Signal()

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)  # insert newline
            else:
                self.sendRequested.emit()
        else:
            super().keyPressEvent(event)
```

---

### UX-2：删除会话功能

**严重程度**：中
**位置**：`ui/panel_session.py`

`SessionStore.delete()` 已实现，但 UI 无入口。旧会话逐渐积累，下拉列表越来越长。

**方案**：在会话下拉框旁添加删除按钮，或在下拉项上右键菜单。删除前弹出确认对话框。

```python
self.btn_delete_session = QtWidgets.QPushButton("Delete")
self.btn_delete_session.setStyleSheet("padding:5px 12px")
self.btn_delete_session.setToolTip("Delete selected session")
self.btn_delete_session.clicked.connect(self._on_delete_session)
```

---

### UX-3：工具结果可展开详情

**严重程度**：中
**位置**：`ui/panel_stream.py:_append_tool_msg()`

工具调用结果只显示前 200 字符（`tool_result[:200]`）。当代码执行失败时，用户在 UI 中看不到完整的错误堆栈和文档状态信息。

**方案**：在工具消息气泡下方添加"展开详情"按钮，点击后显示完整结果：
```python
def _append_tool_msg(self, iteration, name, desc, preview, is_error, full_result=""):
    # ... 现有预览显示 ...
    if len(full_result) > 200:
        # 添加可折叠的详情区域
        detail_id = f"tool_detail_{iteration}_{id(self)}"
        self.chat_display.append(
            f'<div id="{detail_id}" style="display:none; margin:2px 0 2px 20px;'
            f'font-size:11px; color:#666; white-space:pre-wrap;">{esc(full_result)}</div>'
            f'<a href="toggle:{detail_id}" style="margin-left:20px;font-size:11px;">'
            f'Show details</a>'
        )
```

---

### UX-4：Agent reasoning/thinking 内容显示

**严重程度**：中
**位置**：`ui/panel.py:_LlmCallThread.run()`

GLM-5.1 等推理模型在 SSE 响应中返回 `reasoning_content` 字段，当前被完全忽略。用户看不到 Agent 的思考过程，降低了透明度和信任感。

**方案**：
1. 在 `_LlmCallThread.run()` 中捕获 `delta.get("reasoning_content")`
2. 新增 `reasoningReady` 信号
3. 在 UI 中以折叠的灰色区域显示思考过程

```python
# _LlmCallThread 增加
reasoningReady = QtCore.Signal(str)

# run() 中
rc = delta.get("reasoning_content")
if rc:
    self.reasoningReady.emit(rc)

# AgentPanel.__init__ 中连接
self._llm_thread.reasoningReady.connect(self._on_reasoning_chunk)
```

---

### UX-5：暗色主题适配

**严重程度**：低
**位置**：`ui/panel_ui.py`、`ui/panel_stream.py`

所有颜色硬编码（`#e8f0fe`、`#f0faf4`、`#4a90d9` 等），在 FreeCAD 暗色主题下对比度差、文字可能不可读。

**方案**：读取 FreeCAD 的主题色，动态生成样式表：
```python
def _get_theme_colors(self):
    palette = QtWidgets.QApplication.palette()
    bg = palette.window().color().name()        # "#ffffff" or "#2d2d2d"
    text = palette.windowText().color().name()   # "#000000" or "#ffffff"
    return {"bg": bg, "text": text, ...}
```

或使用 QPalette 角色（`QPalette.Base`、`QPalette.Text`）代替硬编码颜色。

---

### UX-6：快捷键支持

**严重程度**：低

当前只能鼠标操作。应支持的快捷键：
- `Ctrl+Enter` / `Enter` — 发送
- `Ctrl+Shift+Z` — 撤销快照
- `Ctrl+N` — 新建会话
- `Escape` — 停止 Agent

---

## 五、架构改进

### ARCH-1：Agent 循环从 UI 层解耦

**严重程度**：中（影响可测试性）
**位置**：`ui/panel.py`

当前 Agent 状态机（_on_send → _call_llm → _handle_llm_response → _execute_tools → 循环）完全嵌入在 `AgentPanel` QDockWidget 中。这导致：
- Agent 逻辑无法脱离 UI 测试
- 难以复用到非 GUI 场景（如 CLI、批量模式）
- panel.py 仍然承担过多职责

**方案**：将状态机提取到 `agent/loop.py`：
```python
# agent/loop.py
class AgentLoop:
    """Headless agent loop — no UI dependency."""

    def __init__(self, session, on_chunk=None, on_tool_call=None, on_finish=None):
        self.session = session
        self.on_chunk = on_chunk        # callable(text)
        self.on_tool_call = on_tool_call  # callable(name, args, result)
        self.on_finish = on_finish      # callable(summary, success)

    def start(self, user_input, context=""):
        """Kick off the agent loop. Runs LLM calls synchronously (blocking)."""
        ...

    def run_async(self, user_input, context=""):
        """Run in a background thread, emit callbacks on events."""
        ...
```

UI 层只负责连接回调：
```python
# panel.py 简化为
self._loop = AgentLoop(session,
    on_chunk=self._on_stream_chunk,
    on_tool_call=self._on_tool_result,
    on_finish=self._finish)
```

---

### ARCH-2：Token 估算精度提升

**严重程度**：低
**位置**：`core/token_budget.py`

当前估算（英文 4 字符/token，CJK 1.5 字符/token）与实际 tokenizer 偏差大，尤其是：
- 代码片段（大量符号，实际 ~2-3 字符/token）
- 特殊字符（Unicode、emoji）
- JSON 字符串（转义字符膨胀）

**方案**：分类型改进估算：
```python
def estimate_tokens(text: str) -> int:
    if not text:
        return 0

    cjk = 0
    code_chars = 0   # 符号、数字、括号等
    other = 0

    for ch in text:
        cp = ord(ch)
        if _is_cjk(cp):
            cjk += 1
        elif ch in '()[]{}=<>+-*/&|^~%#@!;:,.\'"\\':
            code_chars += 1
        else:
            other += 1

    # 代码符号 ~2.5 chars/token，普通英文 ~4 chars/token
    return max(1, int(cjk / 1.5) + int(code_chars / 2.5) + int(other / 4))
```

---

### ARCH-3：`snapshot.py` 全局状态封装

**严重程度**：低
**位置**：`core/snapshot.py`

`_snapshot_counter` 和 `_snapshot_stack` 是模块级全局变量，在 FreeCAD 重新加载工作台或多文档场景下状态不一致。

**方案**：封装为类：
```python
class SnapshotManager:
    def __init__(self, max_snapshots=MAX_SNAPSHOTS):
        self._counter = 0
        self._stack = []
        self._max = max_snapshots

    def take(self): ...
    def restore_latest(self): ...
    def has_snapshot(self): ...
    def cleanup_all(self): ...

# 单例
_snapshot_mgr = SnapshotManager()
```

---

## 六、功能扩展

### FEAT-1：重试/重新生成上一次请求

**严重程度**：中

Agent 失败后用户只能新建会话或手动重新描述。缺少"重新生成"按钮。

**方案**：在控制栏添加 "Retry" 按钮：
- 记录最后一次 user message
- 点击后清除最后一条 assistant response，重新发送相同的 user message
- 与 "New Session" 并列

---

### FEAT-2：导出设计历史为代码文件

**严重程度**：低

用户无法直接获取 Agent 生成的最终 Python 代码。需要从聊天记录中手动复制。

**方案**：在 Agent 完成（`_finish`）后，提取 session 中所有 `execute_code` 工具调用的代码，按顺序合并，生成一个独立的 `.py` 文件。添加"Export Code"按钮。

---

### FEAT-3：Agent 执行耗时统计

**严重程度**：低

用户无法评估 Agent 性能。在状态栏或完成消息中显示总耗时、LLM 调用次数、平均每次迭代时间。

**方案**：
```python
# _on_send 中记录开始时间
self._start_time = time.time()

# _finish 中计算耗时
elapsed = time.time() - self._start_time
avg_iter = elapsed / max(self._iteration, 1)
self.status_label.setText(
    f"Done | {self._iteration} iters | {elapsed:.1f}s total | {avg_iter:.1f}s/iter"
)
```

---

## 七、测试覆盖扩展

### TEST-1：现有测试补充

当前 5 个测试文件覆盖了纯函数模块，以下场景需要补充：

| 文件 | 缺失测试 |
|------|----------|
| `test_token_budget.py` | 边界情况：纯 CJK 长文本、纯代码文本、单条超长消息 |
| `test_chat_renderer.py` | 嵌套列表、多层代码块、Markdown 链接（如果实现 CODE-4） |
| `test_react_parser.py` | 嵌套 `<tool>` 标签、HTML 混合、超长参数 |
| `test_config.py` | 损坏的 .env 文件（缺少值、非法 UTF-8） |

### TEST-2：新增测试目标

| 模块 | 测试方式 | 测试内容 |
|------|----------|----------|
| `agent/tools.py` | Mock FreeCAD | `dispatch_tool` 路由、未知工具名、非法 JSON 参数 |
| `core/snapshot.py` | Mock 文件系统 | 快照栈 LIFO、上限清理、文件不存在时的恢复 |
| `core/doc_analyzer.py` | Mock FreeCAD shape | `_infer_shape_type` 各种几何组合、圆柱面去重 |

---

## 八、优先级排序

### P0 — 必须修复（影响核心功能稳定性）

| 编号 | 任务 | 预估工作量 | 收益 |
|------|------|-----------|------|
| BUG-1 | Agent 循环并发保护 | 0.5h | 防止双击发送导致状态混乱 |
| BUG-2 | SSE 流截断检测 | 1h | 防止截断的 tool_calls 导致崩溃 |
| NET-1 | LLM API 重试机制 | 1.5h | 网络抖动不再终止 Agent 循环 |
| UX-1 | 多行文本输入 | 2h | 基本的输入体验改善 |

### P1 — 应该改进（影响日常使用体验）

| 编号 | 任务 | 预估工作量 | 收益 |
|------|------|-----------|------|
| BUG-3 | 会话切换恢复 Agent 状态 | 2h | 历史会话可继续对话 |
| CODE-1 | exec() 沙箱限制 | 1.5h | 安全性基本保障 |
| UX-2 | 删除会话 UI | 1h | 会话管理完整性 |
| UX-4 | Reasoning 内容显示 | 2h | Agent 思维过程透明化 |
| NET-2 | SSE 流超时检测 | 1h | 防止服务端挂起导致无限等待 |
| TEST-1 | 现有测试补充 | 2h | 提高回归保护 |

### P2 — 建议改进（提升代码质量和可维护性）

| 编号 | 任务 | 预估工作量 | 收益 |
|------|------|-----------|------|
| ARCH-1 | Agent 循环解耦 | 4h | 可测试性 + 可复用性 |
| UX-3 | 工具结果可展开 | 2h | 调试体验改善 |
| FEAT-1 | 重试/重新生成 | 1.5h | 减少重复输入 |
| FEAT-3 | 执行耗时统计 | 0.5h | 性能可观测 |
| BUG-4 | InitGui 路径去重 | 0.5h | 代码整洁 |
| CODE-2 | session_store 统一日志 | 0.5h | 代码一致性 |
| CODE-3 | 快照磁盘清理 | 1h | 磁盘空间管理 |
| ARCH-3 | SnapshotManager 封装 | 1h | 状态管理规范化 |

### P3 — 锦上添花（有精力再做）

| 编号 | 任务 | 预估工作量 | 收益 |
|------|------|-----------|------|
| UX-5 | 暗色主题适配 | 2h | 暗色主题用户体验 |
| UX-6 | 快捷键支持 | 1h | 高级用户效率 |
| CODE-4 | Markdown 链接渲染 | 0.5h | 链接可点击 |
| ARCH-2 | Token 估算精度 | 1h | 减少 API 截断/浪费 |
| FEAT-2 | 导出设计代码 | 2h | 代码复用 |
| TEST-2 | 扩展测试覆盖 | 3h | 更全面的回归保护 |

---

## 九、实施建议

1. **P0 批次**（1 天内完成）：BUG-1 → BUG-2 → NET-1 → UX-1，这 4 项是核心稳定性和基本体验
2. **P1 批次**（2-3 天）：按 BUG-3 → UX-2 → UX-4 → CODE-1 → NET-2 → TEST-1 顺序推进
3. **P2/P3 按需**：根据用户反馈和实际痛点选择性实施

每个批次完成后建议更新此文档，标记已完成项并记录实施中发现的额外问题。

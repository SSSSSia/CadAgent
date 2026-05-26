# CadAgent 深度排查报告

> 日期: 2026-05-26
> 问题: DeepSeek V3.2 生成模型质量不如早期 GLM 5.1
> 根因: 功能蠕变 (feature creep) 导致 agent 循环退化 + 3 个致命管线 bug

---

## 1. 根因分析

### 1.1 [致命] auto-fix 修改了代码但 LLM 看不到修改结果

**文件**: `agent/tools.py:288-295`, `agent/code_fixes.py:26-120`

`auto_fix_code()` 会静默修改 LLM 生成的代码（如去掉 translate 赋值、加回 doc.recompute()），但返回给 LLM 的结果只说 `"Auto-fix: Removed assignment from translate()"` — **没有给出修改后的代码**。

`error_hint()` 的 auto-retry 同理：自动修复执行成功后，LLM 只看到 `"SUCCESS (auto-corrected): ..."` 和提示文本，看不到修正后的代码。

**影响**: LLM 反复犯 translate 赋值、布尔运算赋值等错误，每次都被 auto-fix 静默修正，但永远学不会。这是最大的迭代浪费来源。

### 1.2 [致命] ReAct parser 无法解析多行代码

**文件**: `agent/react_parser.py:49,58,66`

`_normalize_args()` 中 `json.loads()` 使用默认 `strict=True`。当模型在 ReAct 模式下生成包含换行符的 Python 代码时（这是必然的），JSON 解析因控制字符失败，走到 last resort `json.dumps({"input": raw_text})`。`execute_code` 收到 `{"input": "..."}` 而非 `{"code": "..."}`，导致 KeyError。

**影响**: ReAct 模式下每一次包含多行代码的工具调用都会静默失败。LLM 收到无法理解的 KeyError，无法从中学习。

### 1.3 [致命] "先出方案" 指令导致 agent 第一轮就终止

**文件**: `agent/prompts.py:21-22, 72-73`

WORKFLOW 第 1 步要求 "Output a design plan as plain text (no tool call)"。配合 `loop.py:188-210` 的自动检测，当 DeepSeek V3.2（指令遵从性强）照做时，`finish_reason == "stop"` 且无 `<tool>` 标签 → agent 直接 FINISH，返回计划文本而非模型。

**影响**: Agent 在第一次 LLM 调用后就终止，永远不执行任何建模代码。GLM 5.1 可能忽略了该指令直接调用工具，但 DeepSeek V3.2 严格执行。

### 1.4 [致命] 未发送 tool_choice 参数

**文件**: `core/llm_client.py:61, 125`

`call_llm_streaming()` 和 `call_llm_with_tools()` 都未设置 `tool_choice`。模型不确定是否应该使用工具，尤其配合 1.3 的"不要调用工具"指令，模型更倾向纯文本回复。

**影响**: 即使模型支持 tool calling，也可能选择不使用，导致 agent 无法进入工具调用循环。

### 1.5 [严重] execute_code 返回结果过于冗长

**文件**: `agent/tools.py:365-386`

每次 `execute_code` 都返回完整的文档几何分析（可能 900+ 字符），即使几何没怎么变。10 次迭代的会话仅工具结果就消耗约 9,000 字符 (~2,250 tokens) 上下文空间。

### 1.6 [严重] 系统提示词过于庞大

**文件**: `agent/prompts.py:11-163`

当前 `AGENT_SYSTEM_PROMPT` 约 8,500 字符 (~2,000+ tokens)，包含大量大多数任务用不到的内容：
- ASSEMBLY DESIGN MODE 整段
- CURVED SURFACE API 详细示例（loft、BSpline、revolution）
- PARAMETRIC DESIGN 整段
- COMMON MISTAKES 和 CRITICAL RULES 大量重叠

原始版本只有 ~80 行。现在 7 倍膨胀。

### 1.7 [严重] Token 截断过于激进

**文件**: `core/token_budget.py:89, 93`

工具结果截断到 200 字符、助手内容截断到 300 字符。错误输出含 traceback + hint，200 字符只够显示错误类型，丢失关键诊断信息。6+ 轮迭代后模型基本失明。

### 1.8 [中等] auto_fix_code() Fix 9 会破坏合法代码

**文件**: `agent/code_fixes.py:113-118`

`shape.Placement = FreeCAD.Placement(...)` 对于 DocumentObject 是完全合法的，但 Fix 9 的变量名白名单 `{'obj', 'body', 'part', 'shape', 'box', 'cyl', 'hole'}` 太窄。描述性变量名（`cap`、`plate`、`flange` 等）的合法 Placement 赋值会被静默删除。

### 1.9 [中等] auto_fix_code() Fix 6 有逻辑缺陷

**文件**: `agent/code_fixes.py:76-88`

判断"是否已有赋值"用 `'=' in preceding` 检查整行前缀，过于简单，可能导致误判。

### 1.10 [中等] 错误去重过于激进

**文件**: `agent/loop.py:250-260`

40 字符子串匹配会误报不同的 NameError 为"重复错误"，附加 WARNING 让 LLM 错误地改变策略。

### 1.11 [低] Token 预算摘要语言不匹配

**文件**: `core/token_budget.py:141-169`

历史摘要使用中文（`"之前的设计历史：..."`），但系统提示词是英文。

### 1.12 [低] 工具数量过多 + 死代码注册

12 个工具中，`list_materials`、`screenshot`、`list_parameters` 在绝大多数 CAD 建模任务中不会被调用，增加了 LLM 的决策负担。且 9 个隐藏工具仍注册在 dispatch 中，可被意外调用。

### 1.13 [低] Temperature 不可配置

Temperature 硬编码为 0.1，无法按模型调整。

---

## 2. 已执行的修复

### Phase 1: 修复关键缺陷 (commit `e71cd9b`)

#### 让 LLM 看到 auto-fix 的修改 → 对应 1.1

**文件**: `agent/tools.py`

- `auto_fix_code()` 修改代码后，现在在返回结果中包含完整的修正后代码
- `error_hint()` auto-retry 成功时，也包含修正后的完整代码

#### 修复 auto_fix_code() Bug → 对应 1.8, 1.9

**文件**: `agent/code_fixes.py`

- **Fix 6**: 改用正则 `r'\s*\w+\s*=\s*$'` 检测当前行是否有变量赋值
- **Fix 9**: 改为智能检测 DocumentObject 的 Placement 赋值

#### 精简 execute_code 返回结果 → 对应 1.5

**文件**: `agent/tools.py`

- 移除成功/错误路径中的 `Document state` 完整分析
- 估计每次迭代节省 ~900 字符

### Phase 2: 精简系统提示词 (commit `e71cd9b`) → 对应 1.6

**文件**: `agent/prompts.py`

AGENT_SYSTEM_PROMPT 从 ~163 行精简到 ~45 行：

| 移除内容 | 原因 |
|---------|------|
| ASSEMBLY DESIGN MODE 整段 | 大多数任务不需要 |
| CURVED SURFACE API 详细示例 | 移到工具按需提供 |
| PARAMETRIC DESIGN 整段 | 简化为一句话提示 |
| COMMON MISTAKES 6 条 | 与 CRITICAL RULES 合并 |
| GEOMETRIC QUALITY 详细规则 | 简化为 CRITICAL RULES 中的几条 |
| BOOLEAN OPERATION PATTERN 整段 | 合并到 CRITICAL RULES |
| 详细工具列表 12 段 | 简化为一行工具名列表 |

### Phase 3: 激进精简工具与管线 → 对应 1.12, 1.5, 1.10, 1.11

**文件**: `agent/tool_defs.py` — TOOL_DEFINITIONS 从 12 个缩减到 3 个核心工具

**文件**: `agent/tools.py` — 移除后验证管线（`_post_exec_validate`、`_detect_orphan_shapes`、`_check_solid_topology`、`_compute_delta`）

**文件**: `agent/loop.py` — 错误去重改为精确前缀匹配，缓冲区从 3 增到 5

**文件**: `core/token_budget.py` — 历史摘要从中文改为英文

### Phase 4: 修复致命管线 bug → 对应 1.2, 1.3, 1.4, 1.7, 1.8, 1.12, 1.13

#### 修复 ReAct parser 多行代码解析 → 对应 1.2

**文件**: `agent/react_parser.py`

3 处 `json.loads(args_raw)` 全部改为 `json.loads(args_raw, strict=False)`，允许 JSON 字符串中包含换行符。

#### 修复 agent 第一轮终止 → 对应 1.3

**文件**: `agent/prompts.py`

WORKFLOW 第 1 步从 "Output a design plan as plain text (no tool call)" 改为 "Read requirements and start building immediately using execute_code"。

#### 添加 tool_choice 参数 → 对应 1.4

**文件**: `core/llm_client.py`

当 `tools` 非空时添加 `payload["tool_choice"] = "auto"`，确保模型知道应该使用工具。

#### 提升截断阈值 → 对应 1.7

**文件**: `core/token_budget.py`

工具结果截断从 200 → 500 字符，助手内容从 300 → 500 字符。

#### 修复 Fix 9 Placement 误删 → 对应 1.8

**文件**: `agent/code_fixes.py`

去掉变量名白名单，改为只检查值是否包含 `FreeCAD.Placement` 或 `Placement(`。

#### Temperature 可配置化 → 对应 1.13

**文件**: `core/config.py`, `core/llm_client.py`

新增 `TEMPERATURE` 环境变量和配置项，3 处硬编码改为读取配置。

#### 清理隐藏工具注册 → 对应 1.12

**文件**: `agent/tools.py`

注释掉 9 个隐藏工具的 `register_tool()` 调用，保留实现代码。

---

## 3. 变更文件总清单

| 文件 | Phase | 修改内容 |
|------|-------|----------|
| `agent/react_parser.py` | 4 | 3 处 json.loads 加 strict=False |
| `agent/prompts.py` | 2,3,4 | 精简提示词 + 删除"先出方案"指令 |
| `agent/code_fixes.py` | 1,4 | Fix 6 正则 + Fix 9 改为基于值检测 |
| `agent/tool_defs.py` | 3 | 从 12 个缩减到 3 个核心工具 |
| `agent/tools.py` | 1,3,4 | 移除 Document state + 后验证管线 + 隐藏工具取消注册 |
| `agent/loop.py` | 3 | 错误去重改为精确前缀匹配 |
| `core/llm_client.py` | 4 | 加 tool_choice="auto" + temperature 可配 |
| `core/token_budget.py` | 3,4 | 摘要改英文 + 截断阈值提升到 500 |
| `core/config.py` | 4 | 增加 TEMPERATURE 配置 |
| `tests/test_code_fixes.py` | 1 | 更新 Fix 9 测试 |
| `tests/test_multi_doc_tools.py` | 3,4 | 重写为 3 工具测试 + 更新 workflow 断言 |
| `tests/test_token_budget.py` | 3 | 更新摘要测试为英文 |

所有阶段: **275 个测试全部通过**。

---

## 4. 根因→修复对照表

| 根因 | 严重度 | Phase | 修复状态 |
|------|--------|-------|----------|
| 1.1 auto-fix 静默修改，LLM 看不到 | 致命 | 1 | ✅ 已修复 |
| 1.2 ReAct parser 无法解析多行代码 | 致命 | 4 | ✅ 已修复 |
| 1.3 "先出方案"导致第一轮终止 | 致命 | 4 | ✅ 已修复 |
| 1.4 未发送 tool_choice | 致命 | 4 | ✅ 已修复 |
| 1.5 execute_code 返回过于冗长 | 严重 | 1,3 | ✅ 已修复 |
| 1.6 系统提示词过于庞大 | 严重 | 2,3 | ✅ 已修复 |
| 1.7 Token 截断过于激进 | 严重 | 4 | ✅ 已修复 |
| 1.8 Fix 9 Placement 误删 | 中等 | 1,4 | ✅ 已修复 |
| 1.9 Fix 6 逻辑缺陷 | 中等 | 1 | ✅ 已修复 |
| 1.10 错误去重过于激进 | 中等 | 3 | ✅ 已修复 |
| 1.11 摘要语言不匹配 | 低 | 3 | ✅ 已修复 |
| 1.12 工具过多 + 死代码注册 | 低 | 3,4 | ✅ 已修复 |
| 1.13 Temperature 不可配置 | 低 | 4 | ✅ 已修复 |

---

## 5. 验证建议

在 FreeCAD 中测试以下场景：
1. **创建一个杯子**（空心圆柱 + 把手）：验证简化后的管线不丢失关键功能
2. **创建一个法兰盘**（多布尔运算）：验证布尔运算赋值学习
3. **对比 Token 消耗**：修改前后用相同任务比较 context token 使用量
4. **对比迭代次数**：修改前后用相同任务比较完成所需迭代数

# CadAgent 深度排查报告

> 日期: 2026-05-26
> 问题: DeepSeek V3.2 生成模型质量不如早期 GLM 5.1
> 根因: 功能蠕变 (feature creep) 导致 agent 循环退化

---

## 1. 根因分析

### 1.1 [致命] auto-fix 修改了代码但 LLM 看不到修改结果

**文件**: `agent/tools.py:288-295`, `agent/code_fixes.py:26-120`

`auto_fix_code()` 会静默修改 LLM 生成的代码（如去掉 translate 赋值、加回 doc.recompute()），但返回给 LLM 的结果只说 `"Auto-fix: Removed assignment from translate()"` — **没有给出修改后的代码**。

`error_hint()` 的 auto-retry 同理：自动修复执行成功后，LLM 只看到 `"SUCCESS (auto-corrected): ..."` 和提示文本，看不到修正后的代码。

**影响**: LLM 反复犯 translate 赋值、布尔运算赋值等错误，每次都被 auto-fix 静默修正，但永远学不会。这是最大的迭代浪费来源。

### 1.2 [严重] execute_code 返回结果过于冗长

**文件**: `agent/tools.py:365-386`

每次 `execute_code` 都返回完整的文档几何分析（可能 900+ 字符），即使几何没怎么变。10 次迭代的会话仅工具结果就消耗约 9,000 字符 (~2,250 tokens) 上下文空间。

### 1.3 [严重] 系统提示词过于庞大

**文件**: `agent/prompts.py:11-163`

当前 `AGENT_SYSTEM_PROMPT` 约 8,500 字符 (~2,000+ tokens)，包含大量大多数任务用不到的内容：
- ASSEMBLY DESIGN MODE 整段
- CURVED SURFACE API 详细示例（loft、BSpline、revolution）
- PARAMETRIC DESIGN 整段
- COMMON MISTAKES 和 CRITICAL RULES 大量重叠

原始版本只有 ~80 行。现在 7 倍膨胀。

### 1.4 [中等] auto_fix_code() Fix 9 会破坏合法代码

**文件**: `agent/code_fixes.py:113-118`

`shape.Placement = FreeCAD.Placement(...)` 对于 DocumentObject 是完全合法的，但旧版 Fix 9 会删除所有 `.Placement = ...` 行。

### 1.5 [中等] auto_fix_code() Fix 6 有逻辑缺陷

**文件**: `agent/code_fixes.py:76-88`

判断"是否已有赋值"用 `'=' in preceding` 检查整行前缀，过于简单，可能导致误判。

### 1.6 [中等] 错误去重过于激进

**文件**: `agent/loop.py:250-260`

40 字符子串匹配会误报不同的 NameError 为"重复错误"，附加 WARNING 让 LLM 错误地改变策略。

### 1.7 [低] Token 预算摘要语言不匹配

**文件**: `core/token_budget.py:141-169`

历史摘要使用中文（`"之前的设计历史：..."`），但系统提示词是英文。

### 1.8 [低] 工具数量过多

12 个工具中，`list_materials`、`screenshot`、`list_parameters` 在绝大多数 CAD 建模任务中不会被调用，增加了 LLM 的决策负担。

---

## 2. 已执行的修复 (Phase 1 + Phase 2)

### Phase 1: 修复关键缺陷

#### 1.1 让 LLM 看到 auto-fix 的修改

**文件**: `agent/tools.py`

- `auto_fix_code()` 修改代码后，现在在返回结果中包含完整的修正后代码
- `error_hint()` auto-retry 成功时，也包含修正后的完整代码

**修改前**:
```
Note: Auto-fixes applied:
  - Removed assignment from translate() (modifies in-place, returns None)
```

**修改后**:
```
Note: Auto-fixes applied:
  - Removed assignment from translate() (modifies in-place, returns None)
Corrected code:
  shape.translate(Vector(0,0,10))
  body = body.cut(hole)
  ...
```

#### 1.2 修复 auto_fix_code() Bug

**文件**: `agent/code_fixes.py`

- **Fix 9**: 改为智能检测 DocumentObject 的 Placement 赋值（保留合法的 `obj.Placement = FreeCAD.Placement(...)`），只移除疑似 Part.Shape 的非法 Placement 操作
- **Fix 6**: 改用正则 `r'\s*\w+\s*=\s*$'` 检测当前行是否有变量赋值，而非简单搜索 `=`

#### 1.3 精简 execute_code 返回结果

**文件**: `agent/tools.py`

- 移除成功路径中的 `Document state:\n{post_state}` 完整分析
- 移除 auto-retry 成功路径中的 `Document state`
- 移除错误路径中的 `Document state after error`
- LLM 需要几何信息时，应显式调用 `analyze_geometry` 工具
- 估计每次迭代节省 ~900 字符，10 次迭代节省 ~2,250 tokens

### Phase 2: 精简系统提示词

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

REACT_SYSTEM_PROMPT 同步精简，保持结构一致。

**估计节省**: ~4,000 字符 (~1,000 tokens) 系统提示空间，释放给对话上下文。

### 测试结果

275 个测试全部通过（更新了 3 个因行为变更而需要修改的测试）。

---

## 3. 后续改进建议 (Phase 3-4)

### Phase 3: 改进错误处理

#### 3.1 修复错误去重逻辑

**文件**: `agent/loop.py:250-260`

当前 40 字符子串匹配过于激进。建议改为：
- 签名长度从 60 → 120 字符
- 匹配方式从 `in`（子串）改为 `==`（精确匹配前 80 字符）
- 只对完全相同的错误发出 WARNING

```python
# 当前
err_sig = ex.result[:60]
if any(err_sig[:40] in prev for prev in self._recent_errors):

# 建议
err_sig = ex.result[:120]
if any(err_sig[:80] == prev[:80] for prev in self._recent_errors):
```

#### 3.2 修复 Token 预算摘要语言

**文件**: `core/token_budget.py:141-169`

将中文摘要改为英文：
```python
return ("Design history: " + ", ".join(parts)) if parts else "Design history: no prior actions"
```

### Phase 4: 工具精简

不是删除工具代码，而是从活跃工具列表中移除不常用工具：

1. `list_materials` → 移到系统提示中的静态参考
2. `screenshot` → 仅在 LLM 需要视觉反馈时暴露
3. `list_parameters` → 合并到 `update_parameter` 的返回结果

`TOOL_DEFINITIONS` 从 12 个减少到 ~8-9 个，减少 token 消耗和 LLM 决策负担。

---

## 4. 变更文件清单

| 文件 | 修改内容 |
|------|----------|
| `agent/code_fixes.py` | 修复 Fix 9 (Placement 智能检测) 和 Fix 6 (赋值正则) |
| `agent/tools.py` | auto-fix 可见化; 移除 Document state 返回 |
| `agent/prompts.py` | 精简 AGENT_SYSTEM_PROMPT 和 REACT_SYSTEM_PROMPT |
| `tests/test_code_fixes.py` | 更新 Fix 9 测试以匹配新行为 |
| `tests/test_multi_doc_tools.py` | 更新 assembly mode 测试以匹配精简后的提示词 |

---

## 5. 验证建议

在 FreeCAD 中测试以下场景：
1. **创建一个杯子**（空心圆柱 + 把手）：验证 auto-fix 可见性，LLM 应能学习 translate 赋值错误
2. **创建一个法兰盘**（多布尔运算）：验证布尔运算赋值学习
3. **修改现有设计**：验证变量持久性
4. **对比 Token 消耗**：修改前后用相同任务比较 context token 使用量
5. **对比迭代次数**：修改前后用相同任务比较完成所需迭代数

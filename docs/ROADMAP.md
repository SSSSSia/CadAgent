# CadAgent 后续开发计划

## 项目现状

CadAgent 是一个基于 LLM Agent 的 FreeCAD 工作台插件，实现了 ReAct 智能体循环、多轮对话、流式输出、文档快照撤销等功能。当前代码模块化结构清晰（agent/、core/、ui/），零外部依赖。270 个自动化测试全部通过。

### 当前能力

| 模块 | 能力 |
|------|------|
| agent/ | 纯逻辑状态机 AgentLoop、Tool Calling + XML 双模式自动检测、弱模型提示词自动切换、错误去重、12 个工具（execute_code / analyze_geometry / validate_design / undo_last / export_step / measure_distance / list_materials / screenshot / list_documents / create_assembly / update_parameter / list_parameters） |
| core/ | OpenAI 兼容 API 客户端（流式）、会话持久化、文档几何分析（圆锥/球面/螺旋/孔阵列/对称性/壁厚）、快照撤销、Token 预算管理、参数化设计 |
| ui/ | 聊天式 Dock 面板（4 个 mixin 拆分）、Markdown + 代码高亮渲染、会话历史管理、响应式状态栏（耗时/迭代/工具名）、亮/暗主题、设置对话框（7 个提供商预设） |

### 已完成的改进

- **270 个自动化测试**：覆盖 react_parser、token_budget、chat_renderer、config、session、code_fixes、geometry_analyzer、agent_loop、tool_dispatch、parametric、multi_doc 等
- **架构解耦**：AgentLoop 纯逻辑状态机与 UI 线程编排分离；工具注册式路由（tool_dispatch）；几何分析数据层与 FreeCAD 层分离（geometry_analyzer）
- **弱模型兼容**：代码预检（compile）、9 种自动修复（translate 赋值/布尔赋值/缺少 recompute/裸 makeXxx/大小写/赋值 addObj/多参数布尔/Placement/markdown 残留）、按异常类型生成可操作提示
- **模型能力检测**：ModelProfile 通过正则匹配模型名自动判断使用完整/弱提示词
- **执行后验证**：形状有效性检查、零体积检测、退化包围盒检测、孤立形状检测
- **配置集中管理**：所有常量集中在 config.py，支持环境变量覆盖，运行时 reload
- **执行增强**：文档为空时自动创建文档、错误去重（连续相同错误附加 WARNING）
- **编号选择识别**：agent 列出编号选项后，用户输入数字会自动对应到选项

---

## 开发阶段

---

### Phase 8：视觉智能

**目标**：让 Agent 能"看到"自己的设计结果，实现视觉自检。

#### 8.1 视口截图 + VLM 分析

**方案**：
- `screenshot` 工具截取当前 FreeCAD 3D 视口（已实现截图保存）
- 将截图发送给多模态 LLM（GPT-4o、GLM-5V 等）
- VLM 分析图片并与用户需求对比，给出改进建议
- Agent 根据 VLM 反馈继续迭代

技术要点：
- FreeCAD 的 `View.activeView().saveImage()` 可导出 PNG
- 需要配置 VLM 模型（可与主模型不同）
- 图片需要压缩以控制 Token 开销

涉及文件：
- `agent/tools.py` — `screenshot` 工具增加图片 base64 编码
- `core/llm_client.py` — 增加多模态 API 调用
- `core/config.py` — 增加 VLM_MODEL_NAME 配置
- `agent/prompts.py` — 增加视觉分析提示词

#### 8.2 交互式标注

**方案**：用户可以在 3D 视口上点击标注问题区域（"这里的圆角不对"），Agent 根据坐标分析并修改。

---

### Phase 9：工程化与生态

**目标**：让项目可以被其他开发者贡献和复用。

#### 9.1 打包与分发

- 编写 `setup.py` 或 `pyproject.toml`，支持 pip 安装
- FreeCAD Addon Manager 兼容（`package.xml` 元数据）
- GitHub Actions CI：自动化测试 + 代码检查

#### 9.2 国际化

- UI 字符串提取到 `resources/translations/` 目录
- 使用 Qt 的 `QTranslator` 机制加载语言包
- 初始支持：中文、英文

#### 9.3 文档与贡献指南

- `CONTRIBUTING.md` — 代码规范、PR 流程、开发环境搭建
- API 文档 — 用 docstring + Sphinx 生成
- 架构说明文档 — ADR（Architecture Decision Records）

---

## 优先级排序

| 优先级 | Phase | 任务 | 状态 |
|--------|-------|------|------|
| P1 | 6.1 | 设置面板 | ✅ 已完成 |
| P1 | 6.4 | Agent 执行进度可视化 | ✅ 已完成 |
| P2 | 6.2 | 代码高亮显示 | ✅ 已完成 |
| P2 | 7.1 | 增强几何分析 | ✅ 已完成 |
| P2 | 7.2 | 新增工具（export_step 等 4 个） | ✅ 已完成 |
| P3 | 6.3 | 工作台图标 | 待做 |
| P3 | 7.3 | 多文档 / 装配支持 | ✅ 已完成 |
| P3 | 7.4 | 参数化设计 | ✅ 已完成 |
| P4 | 8.1 | 视口截图 + VLM 分析 | 待做 |
| P4 | 8.2 | 交互式标注 | 待做 |
| P4 | 9.x | 工程化与生态 | 待做 |

---

## 技术决策记录

### 为什么用 urllib 而不是 requests？

FreeCAD 内置 Python 不保证安装了第三方包。使用标准库 `urllib` 确保零依赖安装。代价是缺少连接池和自动重试，后续可在 config 中增加重试参数自行实现。

### 为什么 Token 估算不用 tiktoken？

tiktoken 是 OpenAI 专用的 BPE tokenizer，对不同模型（DeepSeek、GLM、Qwen）估算不准确。当前的中英混合字符估算法虽然粗糙，但对所有模型一致。Phase 7 可考虑按模型切换估算策略。

### 为什么快照用 .FCStd 文件而不是内存？

FreeCAD 文档操作（`saveAs`/`open`）是最可靠的完整状态保存方式。尝试过序列化 Python 对象来保存状态，但 FreeCAD 的 C++ 底层对象无法可靠序列化。.FCStd 文件虽然慢（~100ms），但保证 100% 还原。

### 为什么 AgentLoop 和 UI 分离？

AgentLoop（`agent/loop.py`）是纯逻辑状态机，返回 `LoopAction` 指令。UI 层（`ui/panel.py`）解读指令并执行线程调度。分离后：
- AgentLoop 可独立测试（无需 Qt/FreeCAD）
- 状态机逻辑不受 UI 细节干扰
- 未来可替换 UI 框架或接入 CLI 模式

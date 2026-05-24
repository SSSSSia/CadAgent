# CadAgent — FreeCAD CAD Agent 工作台

[English](README_EN.md)

基于 LLM Agent 的 FreeCAD 工作台插件，通过自然语言描述生成和修改 3D 机械模型。

## 功能特性

- **ReAct 智能体循环** — LLM 推理 → 生成 FreeCAD Python 代码 → 执行 → 分析结果 → 自纠错，多轮迭代直到设计完成
- **自然语言设计** — 用中文或英文描述零件，Agent 自动规划并生成 3D 模型
- **12 个 Agent 工具** — 代码执行、几何分析、设计验证、撤销、STEP 导出、距离测量、材料查询、截图、多文档管理、装配、参数化设计
- **参数化设计** — 定义命名参数（如 `OD = 200`），修改参数自动重新生成模型
- **多文档装配** — 在多个文档中分别创建零件，自动组合为装配体
- **增强几何分析** — 检测圆柱、圆锥、球面、螺旋面、孔阵列、对称性、壁厚等特征
- **弱模型兼容** — 自动检测模型能力，为弱模型提供简化提示词和代码自动修复
- **设计验证** — 自动检查模型有效性（零体积、退化包围盒、孤立形状等）
- **错误自纠正** — 代码执行失败时，Agent 查看错误堆栈并自动修正重试；连续相同错误自动提示换策略
- **流式输出** — 实时显示 Agent 思考和代码生成过程
- **撤销/回滚** — 每次代码执行前自动创建文档快照，支持无限撤销
- **会话管理** — 多轮对话历史持久化，支持跨 FreeCAD 会话恢复
- **双模式支持** — 自动适配 Tool Calling 和 ReAct XML 两种 LLM 调用模式
- **Token 预算管理** — 自动裁剪历史消息，防止超出 API 上下文长度限制
- **设置面板** — GUI 配置 API、模型和 Agent 参数，支持 7 个提供商预设和连接测试

## 架构

```
Agent 循环 (ReAct):
  用户输入 → LLM 推理 → 调用工具 → 观察结果 → 再次推理 → ... → 完成

可用工具 (12):
  execute_code       — 执行 FreeCAD Python 代码，创建/修改几何体
  analyze_geometry   — 提取当前文档的几何信息（包围盒、体积、特征）
  validate_design    — 验证当前模型的有效性
  undo_last          — 撤销上次代码执行，恢复文档快照
  export_step        — 导出为 STEP/IGES 文件
  measure_distance   — 测量几何元素间的距离或角度
  list_materials     — 列出工程材料属性（密度、屈服强度、弹性模量）
  screenshot         — 截取 3D 视口为 PNG 图片
  list_documents     — 列出所有打开的 FreeCAD 文档
  create_assembly    — 从多个文档复制零件创建装配体
  update_parameter   — 更新设计参数并重新执行
  list_parameters    — 列出当前设计参数
```

## 安装

1. 将本项目文件夹重命名为 `CadAgent`，复制到 FreeCAD 的 `Mod/` 目录：
   - **Windows**: `%APPDATA%\FreeCAD\Mod\` 或 `<FreeCAD安装目录>\Mod\`
   - **Linux**: `~/.FreeCAD/Mod/`
   - **macOS**: `~/Library/Preferences/FreeCAD/Mod/`

   最终路径示例：`.../Mod/CadAgent/InitGui.py`

2. 复制 `.env.example` 为 `.env` 并填写 API 配置：
   ```bash
   cp .env.example .env
   ```
   编辑 `.env`，填入你使用的模型厂商信息（详见 `.env.example` 中的示例）：
   ```env
   API_BASE_URL=https://api.siliconflow.cn/v1
   API_KEY=sk-your-api-key-here
   MODEL_NAME=Pro/zai-org/GLM-5.1
   ```
   支持所有兼容 OpenAI 接口格式的模型服务，包括但不限于：SiliconFlow、OpenAI、DeepSeek、智谱 AI、Qwen、Moonshot、本地 Ollama 等。

   也可以在 FreeCAD 中通过 **CadAgent Settings** 菜单或面板中的 **Settings** 按钮进行 GUI 配置，支持提供商预设一键切换和连接测试。

3. 重启 FreeCAD，从工作台下拉菜单选择 **CadAgent**。

## 使用方法

1. 切换到 **CadAgent** 工作台 — 右侧自动打开对话面板
2. 在输入框中描述你要设计的零件，例如：
   - "设计一个法兰筒体，外径 200mm，法兰半径 125mm，高度 400mm，带 12 个螺栓孔"
   - "创建一个 100x50x30 的 L 型支架"
3. 点击 **发送** — Agent 将自动推理、生成代码并迭代执行
4. 3D 模型在视口中实时生成；Agent 可能进行多轮优化和修正
5. 可随时点击 **停止** 中断 Agent 循环
6. 点击 **Settings** 按钮或菜单栏 **CadAgent Settings** 可随时修改 API 配置和 Agent 参数

## 环境要求

- FreeCAD >= 1.0（含 PySide6）
- 任何兼容 OpenAI Chat Completions API 的 LLM 服务（需支持 function calling 以获得最佳体验）

## 文件结构

```
CadAgent/
├── Init.py               # FreeCAD 模块入口标识
├── InitGui.py            # 工作台注册与面板加载
├── agent/
│   ├── __init__.py
│   ├── controller.py     # Agent 控制器（会话状态、运行结果）
│   ├── loop.py           # 纯逻辑状态机（AgentLoop），返回 LoopAction 指令
│   ├── model_profile.py  # 模型能力检测（弱模型/强模型提示词切换）
│   ├── prompts.py        # 系统提示词（Tool Calling + ReAct + 弱模型变体）
│   ├── react_parser.py   # ReAct XML 标签解析器
│   ├── tool_defs.py      # 工具 JSON Schema 定义（LLM function calling）
│   ├── tool_dispatch.py  # 注册式工具路由分发
│   ├── tools.py          # 12 个工具实现（含参数化设计、多文档、装配）
│   └── code_fixes.py     # 弱模型兼容：代码预检、9 种自动修复、错误提示
├── core/
│   ├── __init__.py
│   ├── config.py         # 环境配置与 .env 加载、运行时 reload
│   ├── llm_client.py     # LLM API 客户端（OpenAI 兼容 + 流式输出）
│   ├── logger.py         # 双通道日志（FreeCAD Console + 文件）
│   ├── session.py        # ChatSession 会话管理（含参数表和参数化代码）
│   ├── session_store.py  # 会话磁盘持久化
│   ├── doc_analyzer.py   # 文档几何分析（FreeCAD 层）
│   ├── geometry_analyzer.py # 纯数据几何分析（圆锥/球面/螺旋/孔阵列/对称性/壁厚）
│   ├── text_utils.py     # 文本处理工具
│   ├── snapshot.py       # 文档快照系统（撤销/回滚）
│   └── token_budget.py   # Token 预算管理
├── ui/
│   ├── __init__.py
│   ├── panel.py          # 聊天式 Dock 面板（mixin 组合 + 线程编排）
│   ├── panel_ui.py       # 面板 UI 构建（布局、控件、样式）
│   ├── panel_stream.py   # 流式输出渲染（聊天气泡、80ms 批量更新）
│   ├── panel_session.py  # 会话列表管理（切换、历史恢复）
│   ├── panel_status.py   # 响应式状态栏（耗时、迭代计数、工具名显示）
│   ├── chat_renderer.py  # Markdown → HTML 渲染（含代码高亮）
│   ├── theme.py          # 亮/暗模式主题配色
│   └── settings_dialog.py # 设置对话框（7 个提供商预设、连接测试）
├── tests/                # 270 个单元测试（不依赖 FreeCAD）
├── .env.example          # API 配置模板
├── .gitignore
├── LICENSE
├── README.md             # 中文文档
└── README_EN.md          # English documentation
```

## 技术细节

- **双层架构**：AgentLoop 纯逻辑状态机与 UI 线程编排分离，可独立测试
- **线程安全**：LLM API 调用在后台 QThread 中执行，FreeCAD API 操作（工具执行）通过 Signal/Slot 回到主线程
- **纯标准库**：HTTP 请求使用 `urllib`，无外部 Python 包依赖
- **兼容性**：自动检测模型是否支持 Tool Calling，不支持时回退到 ReAct XML 标签模式；自动检测模型能力切换完整/简化提示词
- **270 个自动化测试**：覆盖核心模块（react_parser、token_budget、chat_renderer、config、session、code_fixes、agent_loop、tool_dispatch、parametric 等）

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。

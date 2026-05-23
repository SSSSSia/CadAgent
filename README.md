# CadAgent — FreeCAD CAD Agent 工作台

[English](README_EN.md)

基于 LLM Agent 的 FreeCAD 工作台插件，通过自然语言描述生成和修改 3D 机械模型。

## 功能特性

- **ReAct 智能体循环** — LLM 推理 → 生成 FreeCAD Python 代码 → 执行 → 分析结果 → 自纠错，多轮迭代直到设计完成
- **自然语言设计** — 用中文或英文描述零件，Agent 自动规划并生成 3D 模型
- **几何分析** — Agent 自动检测包围盒、体积、圆柱特征等几何信息
- **设计验证** — 自动检查模型有效性（零体积、退化包围盒等）
- **错误自纠正** — 代码执行失败时，Agent 查看错误堆栈并自动修正重试
- **流式输出** — 实时显示 Agent 思考和代码生成过程
- **撤销/回滚** — 每次代码执行前自动创建文档快照，支持无限撤销
- **会话管理** — 多轮对话历史持久化，支持跨 FreeCAD 会话恢复
- **双模式支持** — 自动适配 Tool Calling 和 ReAct XML 两种 LLM 调用模式
- **Token 预算管理** — 自动裁剪历史消息，防止超出 API 上下文长度限制
- **设置面板** — GUI 配置 API、模型和 Agent 参数，支持提供商预设和连接测试，无需手动编辑配置文件

## 架构

```
Agent 循环 (ReAct):
  用户输入 → LLM 推理 → 调用工具 → 观察结果 → 再次推理 → ... → 完成

可用工具:
  execute_code      — 执行 FreeCAD Python 代码，创建/修改几何体
  analyze_geometry  — 提取当前文档的几何信息（包围盒、体积、特征）
  validate_design   — 验证当前模型的有效性
  undo_last         — 撤销上次代码执行，恢复文档快照
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
   支持所有兼容 OpenAI 接口格式的模型服务，包括但不限于：SiliconFlow、OpenAI、DeepSeek、智谱 AI、本地 Ollama 等。

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
│   ├── loop.py           # Agent 循环（推理 → 工具调用 → 观察 → 迭代）
│   ├── prompts.py        # 系统提示词（Agent 模式 + 单次模式）
│   ├── react_parser.py   # ReAct XML 标签解析器
│   ├── tool_defs.py      # 工具 JSON Schema 定义（LLM function calling）
│   ├── tool_dispatch.py  # 工具路由分发
│   ├── tools.py          # 工具实现（execute_code / analyze_geometry / validate_design / undo_last）
│   └── code_fixes.py     # 弱模型兼容：代码预检、自动修复、错误提示
├── core/
│   ├── __init__.py
│   ├── config.py         # 环境配置与 .env 加载、运行时 reload
│   ├── llm_client.py     # LLM API 客户端（OpenAI 兼容 + 流式输出）
│   ├── logger.py         # 双通道日志（FreeCAD Console + 文件）
│   ├── session.py        # ChatSession 会话管理
│   ├── session_store.py  # 会话磁盘持久化
│   ├── doc_analyzer.py   # 文档几何分析（包围盒、体积、圆柱特征）
│   ├── geometry_analyzer.py # 几何信息格式化输出
│   ├── text_utils.py     # 文本处理工具
│   ├── snapshot.py       # 文档快照系统（撤销/回滚）
│   └── token_budget.py   # Token 预算管理
├── ui/
│   ├── __init__.py
│   ├── panel.py          # 聊天式 Dock 面板（mixin 组合）
│   ├── panel_ui.py       # 面板 UI 构建（布局、控件、样式）
│   ├── panel_stream.py   # 流式输出渲染（聊天气泡、80ms 批量更新）
│   ├── panel_session.py  # 会话列表管理（切换、历史恢复）
│   ├── panel_status.py   # 响应式状态栏（耗时、迭代计数、工具名显示）
│   ├── chat_renderer.py  # Markdown → HTML 渲染
│   ├── theme.py          # 亮/暗模式主题配色
│   └── settings_dialog.py # 设置对话框（API 配置、模型预设、连接测试）
├── tests/                # 单元测试（不依赖 FreeCAD）
├── .env.example          # API 配置模板
├── .gitignore
├── LICENSE
├── README.md             # 中文文档
└── README_EN.md          # English documentation
```

## 技术细节

- **线程安全**：LLM API 调用在后台 QThread 中执行，FreeCAD API 操作（工具执行）通过 Signal/Slot 回到主线程
- **纯标准库**：HTTP 请求使用 `urllib`，无外部 Python 包依赖
- **兼容性**：自动检测模型是否支持 Tool Calling，不支持时回退到 ReAct XML 标签模式

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。

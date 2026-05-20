# CadAgent — FreeCAD AI CAD Agent 工作台

基于 LLM Agent 的 FreeCAD 工作台，通过自然语言描述生成和修改 3D 机械模型。

## 功能特性

- **Agent 模式** — 多轮 ReAct 智能体循环：LLM 推理 → 生成 FreeCAD Python 代码 → 执行 → 分析结果 → 自纠错
- **自然语言设计** — 用文字描述零件，自动生成 3D 模型
- **几何分析** — Agent 自动检测包围盒、体积、圆柱特征等几何信息
- **错误自纠正** — 代码执行失败时，Agent 查看错误堆栈并自动修正重试
- **会话管理** — 内存中的多轮对话历史，支持上下文连续设计

## 架构

```
Agent 循环 (ReAct):
  用户输入 → LLM 推理 → 调用工具 → 观察结果 → 再次推理 → ...

可用工具:
  - execute_code     — 执行 FreeCAD Python 代码，创建/修改几何体
  - analyze_geometry — 提取当前文档的几何信息
  - validate_design  — 验证当前模型
```

## 安装

1. 将 `CadAgent` 文件夹复制到 FreeCAD 的 `Mod/` 目录：
   - **Windows**: `%APPDATA%/FreeCAD/Mod/` 或 `<FreeCAD安装目录>/Mod/`
   - **Linux**: `~/.FreeCAD/Mod/`
   - **macOS**: `~/Library/Preferences/FreeCAD/Mod/`

2. 复制 `.env.example` 为 `.env` 并填写你的 API 密钥：
   ```bash
   cp .env.example .env
   ```
   编辑 `.env`：
   ```env
   API_BASE_URL=https://api.siliconflow.cn/v1
   API_KEY=sk-your-api-key-here
   MODEL_NAME=Pro/zai-org/GLM-5.1
   ```

3. 重启 FreeCAD，从工作台下拉菜单选择 **AI CAD Agent** 工作台。

## 使用方法

1. 切换到 **AI CAD Agent** 工作台 — 右侧自动打开对话面板
2. 输入零件描述（如 "设计一个法兰筒体 OD 200mm，法兰 R=125"）
3. 点击 **发送** — Agent 将自动推理、生成代码并迭代执行
4. 3D 模型在视口中生成；Agent 可能进行多轮优化

## 环境要求

- FreeCAD >= 1.0（含 PySide6）
- 配置的 LLM 服务的有效 API 密钥（默认：SiliconFlow GLM-5.1）

## 文件结构

```
CadAgent/
├── Init.py              # FreeCAD 模块入口标识
├── InitGui.py           # 工作台注册与面板加载
├── AgentPanel.py        # 聊天式 Dock 面板 UI + 状态机 Agent 循环
├── agent_controller.py  # Agent 核心逻辑：系统提示词、ReAct 解析、工具调度
├── agent_tools.py       # 工具实现（execute_code / analyze_geometry / validate_design）
├── tool_definitions.py  # 工具 JSON Schema 定义（LLM function calling）
├── llm_engine.py        # LLM API 集成（OpenAI 兼容接口 + tool calling）
├── session_manager.py   # ChatSession 会话管理类
├── doc_analyzer.py      # 文档几何分析（包围盒、体积、圆柱特征）
├── .env.example         # API 配置模板
├── .env                 # 用户配置（已 gitignore，从模板复制）
├── log.md               # 关键开发笔记与已解决问题
├── DEVELOPMENT_PLAN.md  # 开发路线图（Phase 1–4）
├── .gitignore
├── LICENSE
└── README.md
```

## 开发

详见 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) 了解完整的开发路线图和任务规划。

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。

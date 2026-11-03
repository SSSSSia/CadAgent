"""User-visible strings for the panel and dialogs (S9-C).

Two flat tables, English and Chinese. ``CADAGENT_LANG`` (``en`` / ``zh``)
wins. Otherwise the FreeCAD language preference is used. QTranslator stays
out until the string set is worth a toolchain.
"""
from __future__ import annotations

import os

_EN = {
    "ready": "Ready",
    "send": "Send",
    "stop": "Stop",
    "undo": "Undo",
    "new": "New",
    "delete": "Delete",
    "placeholder": "Describe the part you want to design...",
    "attach_tip": "Attach image for vision analysis",
    "undo_tip": "Undo last agent operation (restore document snapshot)",
    "params_tip": (
        "Edit parameters and rebuild the model deterministically "
        "(no LLM call; previous state stays undoable)"
    ),
    "delete_session_tip": "Delete selected session",
    "settings_tip": "Configure CadAgent API and parameters",
    "params_label_tip": (
        "Named parameters extracted from executed code. They are injected "
        "into later turns' context — to change one, tell the Agent the "
        "new value."
    ),
    "welcome": "CadAgent ready. Describe a part and I'll create it in FreeCAD.",
    "current_session": "(current session)",
    "no_summary": "No summary",
    "new_session_title": "New Session",
    "new_session_body": (
        "Start a new session? The current conversation is saved "
        "and remains in the session list."
    ),
    "new_session_started": "New session started. Describe a part to begin.",
    "cannot_switch": "Cannot switch session while the agent is running.",
    "load_failed": "Failed to load session.",
    "session_loaded": "Session loaded | {turns} turns | {msgs} messages",
    "history_restored": "Session loaded. History restored.",
    "cannot_delete_running": "Agent is running. Cannot delete session.",
    "delete_title": "Delete Session",
    "delete_body": "Permanently delete this session?\n\n{name}",
    "delete_failed": "Failed to delete session.",
    "session_deleted": "Session deleted. New session started.",
    "queued": "Queued — sent to the model at the next step.",
    "select_image": "Select Image",
    "image_filter": "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)",
    "attached": "Attached image: {name}",
    "nothing_to_undo": "Nothing to undo — no snapshots available.",
    "cannot_undo_running": "Cannot undo while agent is running.",
    "undo_ok": "Undo successful. {count} snapshot(s) remaining.",
    "undo_failed": "Undo failed: {detail}",
    "cannot_rebuild_running": (
        "Cannot rebuild while the agent is running — wait for it to finish."
    ),
    "rebuild_ok": "Model rebuilt with new parameters. Use Undo to roll back.",
    "stopped_by_user": "Stopped by user. Partial output above is kept.",
    "status_done": "Done  {elapsed}  {iters} iters  Turn {turns}",
    "status_failed": "Failed  {elapsed}  {iters} iters  Turn {turns}",
    "status_interrupted": "Interrupted  {elapsed}  {iters} iters  Turn {turns}",
    "status_thinking": "Thinking... {elapsed}{iters}",
    "status_executing_desc": "Executing {tool} \"{desc}\"  {elapsed}{iters}",
    "status_executing": "Executing {label}...  {elapsed}{iters}",
    "status_stopping": "Stopping... {elapsed}",
    "tokens": "Tokens: {used} / {budget}{tag}",
    "tool_execute_code": "Running code",
    "tool_undo_last": "Undoing",
    "tool_capture_view": "Capturing viewport",
    "tool_analyze_image": "Analyzing image",
    "tool_export_step": "Exporting",
    "params_title": "Parameters",
    "params_no_history": (
        "No rebuildable code history in this session yet — parameters "
        "are still injected into the Agent's context."
    ),
    "params_none": (
        "This run did not declare named dimensions, so there is nothing to edit. "
        "They appear here when the code assigns them at the start of a line, "
        "for example OD = 80."
    ),
    "param_col": "Parameter",
    "value_col": "Value",
    "params_hint": (
        "Rebuild replays this session's modeling code with the new values "
        "(no LLM call). The previous state stays undoable."
    ),
    "rebuild": "Rebuild",
    "cancel": "Cancel",
    "invalid_value_title": "Invalid value",
    "invalid_value_body": (
        "'{raw}' is not a number. Parameter {name} must be "
        "an integer or decimal value."
    ),
    "settings_title": "CadAgent Settings",
    "tab_main": "Main LLM",
    "tab_vision": "Vision Model",
    "apply": "Apply",
    "api_group": "API Configuration",
    "provider": "Provider:",
    "api_url": "API Base URL:",
    "api_key": "API Key:",
    "model_name": "Model Name:",
    "max_tokens": "Max Tokens:",
    "max_tokens_tip": "Maximum output tokens per LLM request",
    "max_iters": "Max Iterations:",
    "max_iters_tip": "Maximum agent loop iterations",
    "show": "Show",
    "hide": "Hide",
    "test_connection": "Test Connection",
    "vision_enable": "Enable Vision Model",
    "vision_enable_tip": (
        "Enable vision tools (capture_view, analyze_image) for visual verification"
    ),
    "vision_group": "Vision Model Configuration",
    "vision_same": "Use same API as main model",
    "vision_same_tip": (
        "Auto-fill Vision API URL and Key from the main API configuration"
    ),
    "vision_max_tokens_tip": "Maximum output tokens per vision API request",
    "temperature": "Temperature:",
    "temperature_tip": "Temperature for vision model responses",
    "test_vision": "Test Vision API",
    "test_running": "A connection test is still running. Please wait for it to finish.",
    "testing": "Testing...",
    "test_ok": "Connection successful!\n\nModel: {model}",
    "test_fail": "Connection failed: {detail}",
    "url_empty": "API Base URL is empty.",
    "vision_url_empty": "Vision API Base URL is empty.",
    "validation": "Validation",
    "url_required": "API Base URL cannot be empty.",
    "key_required": "API Key cannot be empty.",
    "model_required": "Model Name cannot be empty.",
    "vision_incomplete": (
        "Vision Model is enabled but fields are incomplete.\n"
        "Fill all Vision fields or disable Vision Model."
    ),
}

_ZH = {
    "ready": "就绪",
    "send": "发送",
    "stop": "停止",
    "undo": "撤销",
    "new": "新建",
    "delete": "删除",
    "placeholder": "描述你要设计的零件…",
    "attach_tip": "附加图片，供视觉分析",
    "undo_tip": "撤销上一次建模（恢复文档快照）",
    "params_tip": "编辑参数并确定性重建模型（不调用 LLM，之前的状态可以撤销）",
    "delete_session_tip": "删除选中的会话",
    "settings_tip": "配置 CadAgent 的 API 和参数",
    "params_label_tip": "从已执行代码里提取的命名参数，会注入后续对话。要改数值，直接告诉 Agent。",
    "welcome": "CadAgent 已就绪。描述一个零件，我会在 FreeCAD 里建出来。",
    "current_session": "（当前会话）",
    "no_summary": "无摘要",
    "new_session_title": "新建会话",
    "new_session_body": "开始新会话？当前对话已保存，仍留在会话列表里。",
    "new_session_started": "已开始新会话。描述一个零件即可开始。",
    "cannot_switch": "Agent 正在运行，不能切换会话。",
    "load_failed": "加载会话失败。",
    "session_loaded": "已加载会话 | {turns} 轮 | {msgs} 条消息",
    "history_restored": "会话已加载，历史已恢复。",
    "cannot_delete_running": "Agent 正在运行，不能删除会话。",
    "delete_title": "删除会话",
    "delete_body": "永久删除这个会话？\n\n{name}",
    "delete_failed": "删除会话失败。",
    "session_deleted": "会话已删除，已开始新会话。",
    "queued": "已排队，将在下一步发给模型。",
    "select_image": "选择图片",
    "image_filter": "图片 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)",
    "attached": "已附加图片：{name}",
    "nothing_to_undo": "没有可撤销的快照。",
    "cannot_undo_running": "Agent 正在运行，不能撤销。",
    "undo_ok": "撤销成功。还剩 {count} 个快照。",
    "undo_failed": "撤销失败：{detail}",
    "cannot_rebuild_running": "Agent 正在运行，请等它结束后再重建。",
    "rebuild_ok": "已用新参数重建模型。可以用撤销回退。",
    "stopped_by_user": "已停止。上面保留了已经收到的内容。",
    "status_done": "完成  {elapsed}  {iters} 轮  第 {turns} 回合",
    "status_failed": "失败  {elapsed}  {iters} 轮  第 {turns} 回合",
    "status_interrupted": "已中断  {elapsed}  {iters} 轮  第 {turns} 回合",
    "status_thinking": "思考中… {elapsed}{iters}",
    "status_executing_desc": "正在执行 {tool}「{desc}」  {elapsed}{iters}",
    "status_executing": "正在{label}…  {elapsed}{iters}",
    "status_stopping": "正在停止… {elapsed}",
    "tokens": "Tokens: {used} / {budget}{tag}",
    "tool_execute_code": "运行代码",
    "tool_undo_last": "撤销",
    "tool_capture_view": "截取视口",
    "tool_analyze_image": "分析图片",
    "tool_export_step": "导出",
    "params_title": "参数",
    "params_no_history": "本会话还没有可重放的代码。参数仍会注入 Agent 的上下文。",
    "params_none": "这次建模没有写出可改的尺寸。需要在代码行首写成 OD = 80 这样的赋值，参数才会出现在这里。",
    "param_col": "参数",
    "value_col": "数值",
    "params_hint": "重建会用新数值重放本会话的建模代码（不调用 LLM）。之前的状态可以撤销。",
    "rebuild": "重建",
    "cancel": "取消",
    "invalid_value_title": "数值无效",
    "invalid_value_body": "「{raw}」不是数字。参数 {name} 必须是整数或小数。",
    "settings_title": "CadAgent 设置",
    "tab_main": "主模型",
    "tab_vision": "视觉模型",
    "apply": "应用",
    "api_group": "API 配置",
    "provider": "提供商：",
    "api_url": "API 地址：",
    "api_key": "API 密钥：",
    "model_name": "模型名称：",
    "max_tokens": "最大 Tokens：",
    "max_tokens_tip": "每次 LLM 请求的最大输出 token",
    "max_iters": "最大迭代：",
    "max_iters_tip": "Agent 循环的最大轮数",
    "show": "显示",
    "hide": "隐藏",
    "test_connection": "测试连接",
    "vision_enable": "启用视觉模型",
    "vision_enable_tip": "启用视觉工具（capture_view、analyze_image）做视觉核对",
    "vision_group": "视觉模型配置",
    "vision_same": "使用与主模型相同的 API",
    "vision_same_tip": "用主 API 的地址和密钥自动填写视觉 API",
    "vision_max_tokens_tip": "每次视觉请求的最大输出 token",
    "temperature": "温度：",
    "temperature_tip": "视觉模型回复的温度",
    "test_vision": "测试视觉 API",
    "test_running": "连接测试还在进行，请等它结束。",
    "testing": "测试中…",
    "test_ok": "连接成功。\n\n模型：{model}",
    "test_fail": "连接失败：{detail}",
    "url_empty": "API 地址为空。",
    "vision_url_empty": "视觉 API 地址为空。",
    "validation": "校验",
    "url_required": "API 地址不能为空。",
    "key_required": "API 密钥不能为空。",
    "model_required": "模型名称不能为空。",
    "vision_incomplete": "已启用视觉模型，但字段不完整。\n请填全视觉字段，或关闭视觉模型。",
}


def current_lang() -> str:
    """``en`` or ``zh``. Environment override, then FreeCAD, then LANG."""
    override = os.environ.get("CADAGENT_LANG", "").strip().lower()
    if override:
        if override.startswith("zh") or override in ("cn", "chinese"):
            return "zh"
        return "en"
    freecad_lang = _freecad_language().lower().replace("-", "_")
    if freecad_lang.startswith("zh") or "chinese" in freecad_lang:
        return "zh"
    if os.environ.get("LANG", "").lower().startswith("zh"):
        return "zh"
    return "en"


def _freecad_language() -> str:
    try:
        import FreeCAD
        prefs = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General")
        return prefs.GetString("Language") or ""
    except Exception:
        return ""


def t(key: str, **kwargs) -> str:
    """Look up a user-visible string. Missing keys fall back to English."""
    lang = current_lang()
    text = (_ZH if lang == "zh" else _EN).get(key) or _EN.get(key) or key
    if kwargs:
        return text.format(**kwargs)
    return text

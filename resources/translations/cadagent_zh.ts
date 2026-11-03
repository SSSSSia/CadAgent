<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_CN">
<context>
<name>CadAgent</name>
<message>
<source>Ready</source>
<translation>就绪</translation>
<!-- key:ready -->
</message>
<message>
<source>Send</source>
<translation>发送</translation>
<!-- key:send -->
</message>
<message>
<source>Stop</source>
<translation>停止</translation>
<!-- key:stop -->
</message>
<message>
<source>Undo</source>
<translation>撤销</translation>
<!-- key:undo -->
</message>
<message>
<source>New</source>
<translation>新建</translation>
<!-- key:new -->
</message>
<message>
<source>Delete</source>
<translation>删除</translation>
<!-- key:delete -->
</message>
<message>
<source>Describe the part you want to design...</source>
<translation>描述你要设计的零件…</translation>
<!-- key:placeholder -->
</message>
<message>
<source>Attach image for vision analysis</source>
<translation>附加图片，供视觉分析</translation>
<!-- key:attach_tip -->
</message>
<message>
<source>Undo last agent operation (restore document snapshot)</source>
<translation>撤销上一次建模（恢复文档快照）</translation>
<!-- key:undo_tip -->
</message>
<message>
<source>Edit parameters and rebuild the model deterministically (no LLM call; previous state stays undoable)</source>
<translation>编辑参数并确定性重建模型（不调用 LLM，之前的状态可以撤销）</translation>
<!-- key:params_tip -->
</message>
<message>
<source>Mark</source>
<translation>标注</translation>
<!-- key:mark -->
</message>
<message>
<source>Insert the selected face or point into the message</source>
<translation>把当前选中的面或点写进输入框</translation>
<!-- key:mark_tip -->
</message>
<message>
<source>Click a face or edge in the 3D view first, then Mark.</source>
<translation>先在三维视图里点一个面或边，再点标注。</translation>
<!-- key:mark_empty -->
</message>
<message>
<source>Delete selected session</source>
<translation>删除选中的会话</translation>
<!-- key:delete_session_tip -->
</message>
<message>
<source>Configure CadAgent API and parameters</source>
<translation>配置 CadAgent 的 API 和参数</translation>
<!-- key:settings_tip -->
</message>
<message>
<source>Named parameters extracted from executed code. They are injected into later turns' context — to change one, tell the Agent the new value.</source>
<translation>从已执行代码里提取的命名参数，会注入后续对话。要改数值，直接告诉 Agent。</translation>
<!-- key:params_label_tip -->
</message>
<message>
<source>CadAgent ready. Describe a part and I'll create it in FreeCAD.</source>
<translation>CadAgent 已就绪。描述一个零件，我会在 FreeCAD 里建出来。</translation>
<!-- key:welcome -->
</message>
<message>
<source>(current session)</source>
<translation>（当前会话）</translation>
<!-- key:current_session -->
</message>
<message>
<source>No summary</source>
<translation>无摘要</translation>
<!-- key:no_summary -->
</message>
<message>
<source>New Session</source>
<translation>新建会话</translation>
<!-- key:new_session_title -->
</message>
<message>
<source>Start a new session? The current conversation is saved and remains in the session list.</source>
<translation>开始新会话？当前对话已保存，仍留在会话列表里。</translation>
<!-- key:new_session_body -->
</message>
<message>
<source>New session started. Describe a part to begin.</source>
<translation>已开始新会话。描述一个零件即可开始。</translation>
<!-- key:new_session_started -->
</message>
<message>
<source>Cannot switch session while the agent is running.</source>
<translation>Agent 正在运行，不能切换会话。</translation>
<!-- key:cannot_switch -->
</message>
<message>
<source>Failed to load session.</source>
<translation>加载会话失败。</translation>
<!-- key:load_failed -->
</message>
<message>
<source>Session loaded | {turns} turns | {msgs} messages</source>
<translation>已加载会话 | {turns} 轮 | {msgs} 条消息</translation>
<!-- key:session_loaded -->
</message>
<message>
<source>Session loaded. History restored.</source>
<translation>会话已加载，历史已恢复。</translation>
<!-- key:history_restored -->
</message>
<message>
<source>Agent is running. Cannot delete session.</source>
<translation>Agent 正在运行，不能删除会话。</translation>
<!-- key:cannot_delete_running -->
</message>
<message>
<source>Delete Session</source>
<translation>删除会话</translation>
<!-- key:delete_title -->
</message>
<message>
<source>Permanently delete this session?

{name}</source>
<translation>永久删除这个会话？

{name}</translation>
<!-- key:delete_body -->
</message>
<message>
<source>Failed to delete session.</source>
<translation>删除会话失败。</translation>
<!-- key:delete_failed -->
</message>
<message>
<source>Session deleted. New session started.</source>
<translation>会话已删除，已开始新会话。</translation>
<!-- key:session_deleted -->
</message>
<message>
<source>Queued — sent to the model at the next step.</source>
<translation>已排队，将在下一步发给模型。</translation>
<!-- key:queued -->
</message>
<message>
<source>Select Image</source>
<translation>选择图片</translation>
<!-- key:select_image -->
</message>
<message>
<source>Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)</source>
<translation>图片 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)</translation>
<!-- key:image_filter -->
</message>
<message>
<source>Attached image: {name}</source>
<translation>已附加图片：{name}</translation>
<!-- key:attached -->
</message>
<message>
<source>Nothing to undo — no snapshots available.</source>
<translation>没有可撤销的快照。</translation>
<!-- key:nothing_to_undo -->
</message>
<message>
<source>Cannot undo while agent is running.</source>
<translation>Agent 正在运行，不能撤销。</translation>
<!-- key:cannot_undo_running -->
</message>
<message>
<source>Undo successful. {count} snapshot(s) remaining.</source>
<translation>撤销成功。还剩 {count} 个快照。</translation>
<!-- key:undo_ok -->
</message>
<message>
<source>Undo failed: {detail}</source>
<translation>撤销失败：{detail}</translation>
<!-- key:undo_failed -->
</message>
<message>
<source>Cannot rebuild while the agent is running — wait for it to finish.</source>
<translation>Agent 正在运行，请等它结束后再重建。</translation>
<!-- key:cannot_rebuild_running -->
</message>
<message>
<source>Model rebuilt with new parameters. Use Undo to roll back.</source>
<translation>已用新参数重建模型。可以用撤销回退。</translation>
<!-- key:rebuild_ok -->
</message>
<message>
<source>Stopped by user. Partial output above is kept.</source>
<translation>已停止。上面保留了已经收到的内容。</translation>
<!-- key:stopped_by_user -->
</message>
<message>
<source>Done  {elapsed}  {iters} iters  Turn {turns}</source>
<translation>完成  {elapsed}  {iters} 轮  第 {turns} 回合</translation>
<!-- key:status_done -->
</message>
<message>
<source>Failed  {elapsed}  {iters} iters  Turn {turns}</source>
<translation>失败  {elapsed}  {iters} 轮  第 {turns} 回合</translation>
<!-- key:status_failed -->
</message>
<message>
<source>Interrupted  {elapsed}  {iters} iters  Turn {turns}</source>
<translation>已中断  {elapsed}  {iters} 轮  第 {turns} 回合</translation>
<!-- key:status_interrupted -->
</message>
<message>
<source>Thinking... {elapsed}{iters}</source>
<translation>思考中… {elapsed}{iters}</translation>
<!-- key:status_thinking -->
</message>
<message>
<source>Executing {tool} "{desc}"  {elapsed}{iters}</source>
<translation>正在执行 {tool}「{desc}」  {elapsed}{iters}</translation>
<!-- key:status_executing_desc -->
</message>
<message>
<source>Executing {label}...  {elapsed}{iters}</source>
<translation>正在{label}…  {elapsed}{iters}</translation>
<!-- key:status_executing -->
</message>
<message>
<source>Stopping... {elapsed}</source>
<translation>正在停止… {elapsed}</translation>
<!-- key:status_stopping -->
</message>
<message>
<source>Tokens: {used} / {budget}{tag}</source>
<translation>Tokens: {used} / {budget}{tag}</translation>
<!-- key:tokens -->
</message>
<message>
<source>Running code</source>
<translation>运行代码</translation>
<!-- key:tool_execute_code -->
</message>
<message>
<source>Undoing</source>
<translation>撤销</translation>
<!-- key:tool_undo_last -->
</message>
<message>
<source>Capturing viewport</source>
<translation>截取视口</translation>
<!-- key:tool_capture_view -->
</message>
<message>
<source>Analyzing image</source>
<translation>分析图片</translation>
<!-- key:tool_analyze_image -->
</message>
<message>
<source>Exporting</source>
<translation>导出</translation>
<!-- key:tool_export_step -->
</message>
<message>
<source>Parameters</source>
<translation>参数</translation>
<!-- key:params_title -->
</message>
<message>
<source>No rebuildable code history in this session yet — parameters are still injected into the Agent's context.</source>
<translation>本会话还没有可重放的代码。参数仍会注入 Agent 的上下文。</translation>
<!-- key:params_no_history -->
</message>
<message>
<source>This run did not declare named dimensions, so there is nothing to edit. They appear here when the code assigns them at the start of a line, for example OD = 80.</source>
<translation>这次建模没有写出可改的尺寸。需要在代码行首写成 OD = 80 这样的赋值，参数才会出现在这里。</translation>
<!-- key:params_none -->
</message>
<message>
<source>Parameter</source>
<translation>参数</translation>
<!-- key:param_col -->
</message>
<message>
<source>Value</source>
<translation>数值</translation>
<!-- key:value_col -->
</message>
<message>
<source>Rebuild replays this session's modeling code with the new values (no LLM call). The previous state stays undoable.</source>
<translation>重建会用新数值重放本会话的建模代码（不调用 LLM）。之前的状态可以撤销。</translation>
<!-- key:params_hint -->
</message>
<message>
<source>Rebuild</source>
<translation>重建</translation>
<!-- key:rebuild -->
</message>
<message>
<source>Cancel</source>
<translation>取消</translation>
<!-- key:cancel -->
</message>
<message>
<source>Invalid value</source>
<translation>数值无效</translation>
<!-- key:invalid_value_title -->
</message>
<message>
<source>'{raw}' is not a number. Parameter {name} must be an integer or decimal value.</source>
<translation>「{raw}」不是数字。参数 {name} 必须是整数或小数。</translation>
<!-- key:invalid_value_body -->
</message>
<message>
<source>CadAgent Settings</source>
<translation>CadAgent 设置</translation>
<!-- key:settings_title -->
</message>
<message>
<source>Main LLM</source>
<translation>主模型</translation>
<!-- key:tab_main -->
</message>
<message>
<source>Vision Model</source>
<translation>视觉模型</translation>
<!-- key:tab_vision -->
</message>
<message>
<source>Apply</source>
<translation>应用</translation>
<!-- key:apply -->
</message>
<message>
<source>API Configuration</source>
<translation>API 配置</translation>
<!-- key:api_group -->
</message>
<message>
<source>Provider:</source>
<translation>提供商：</translation>
<!-- key:provider -->
</message>
<message>
<source>API Base URL:</source>
<translation>API 地址：</translation>
<!-- key:api_url -->
</message>
<message>
<source>API Key:</source>
<translation>API 密钥：</translation>
<!-- key:api_key -->
</message>
<message>
<source>Model Name:</source>
<translation>模型名称：</translation>
<!-- key:model_name -->
</message>
<message>
<source>Max Tokens:</source>
<translation>最大 Tokens：</translation>
<!-- key:max_tokens -->
</message>
<message>
<source>Maximum output tokens per LLM request</source>
<translation>每次 LLM 请求的最大输出 token</translation>
<!-- key:max_tokens_tip -->
</message>
<message>
<source>Max Iterations:</source>
<translation>最大迭代：</translation>
<!-- key:max_iters -->
</message>
<message>
<source>Maximum agent loop iterations</source>
<translation>Agent 循环的最大轮数</translation>
<!-- key:max_iters_tip -->
</message>
<message>
<source>Show</source>
<translation>显示</translation>
<!-- key:show -->
</message>
<message>
<source>Hide</source>
<translation>隐藏</translation>
<!-- key:hide -->
</message>
<message>
<source>Test Connection</source>
<translation>测试连接</translation>
<!-- key:test_connection -->
</message>
<message>
<source>Enable Vision Model</source>
<translation>启用视觉模型</translation>
<!-- key:vision_enable -->
</message>
<message>
<source>Enable vision tools (capture_view, analyze_image) for visual verification</source>
<translation>启用视觉工具（capture_view、analyze_image）做视觉核对</translation>
<!-- key:vision_enable_tip -->
</message>
<message>
<source>Vision Model Configuration</source>
<translation>视觉模型配置</translation>
<!-- key:vision_group -->
</message>
<message>
<source>Use same API as main model</source>
<translation>使用与主模型相同的 API</translation>
<!-- key:vision_same -->
</message>
<message>
<source>Auto-fill Vision API URL and Key from the main API configuration</source>
<translation>用主 API 的地址和密钥自动填写视觉 API</translation>
<!-- key:vision_same_tip -->
</message>
<message>
<source>Maximum output tokens per vision API request</source>
<translation>每次视觉请求的最大输出 token</translation>
<!-- key:vision_max_tokens_tip -->
</message>
<message>
<source>Temperature:</source>
<translation>温度：</translation>
<!-- key:temperature -->
</message>
<message>
<source>Temperature for vision model responses</source>
<translation>视觉模型回复的温度</translation>
<!-- key:temperature_tip -->
</message>
<message>
<source>Test Vision API</source>
<translation>测试视觉 API</translation>
<!-- key:test_vision -->
</message>
<message>
<source>A connection test is still running. Please wait for it to finish.</source>
<translation>连接测试还在进行，请等它结束。</translation>
<!-- key:test_running -->
</message>
<message>
<source>Testing...</source>
<translation>测试中…</translation>
<!-- key:testing -->
</message>
<message>
<source>Connection successful!

Model: {model}</source>
<translation>连接成功。

模型：{model}</translation>
<!-- key:test_ok -->
</message>
<message>
<source>Connection failed: {detail}</source>
<translation>连接失败：{detail}</translation>
<!-- key:test_fail -->
</message>
<message>
<source>API Base URL is empty.</source>
<translation>API 地址为空。</translation>
<!-- key:url_empty -->
</message>
<message>
<source>Vision API Base URL is empty.</source>
<translation>视觉 API 地址为空。</translation>
<!-- key:vision_url_empty -->
</message>
<message>
<source>Validation</source>
<translation>校验</translation>
<!-- key:validation -->
</message>
<message>
<source>API Base URL cannot be empty.</source>
<translation>API 地址不能为空。</translation>
<!-- key:url_required -->
</message>
<message>
<source>API Key cannot be empty.</source>
<translation>API 密钥不能为空。</translation>
<!-- key:key_required -->
</message>
<message>
<source>Model Name cannot be empty.</source>
<translation>模型名称不能为空。</translation>
<!-- key:model_required -->
</message>
<message>
<source>Vision Model is enabled but fields are incomplete.
Fill all Vision fields or disable Vision Model.</source>
<translation>已启用视觉模型，但字段不完整。
请填全视觉字段，或关闭视觉模型。</translation>
<!-- key:vision_incomplete -->
</message>
</context>
</TS>

# AI CAD Agent 关键问题日志

---

## 1. FreeCAD exec() 作用域问题

FreeCAD 通过 `exec()` 而非 `import` 加载插件脚本。导致 `__file__` 不可用、同文件定义的类/函数在方法体内部不可见、`sys.path` 缺少插件目录。

解决：手动计算插件路径加入 `sys.path`，方法体内部使用局部 import。

---

## 2. Qt 跨线程崩溃

Agent 循环在后台 QThread 中执行 FreeCAD `exec()` 代码，触发 `Cannot create children for a parent that is in a different thread`。FreeCAD 文档操作会间接触发 Qt GUI 信号，必须在主线程执行。

解决：改为状态机模式 — 后台线程只做 LLM API 调用，工具执行通过 Signal/Slot 回到主线程。

---

## 3. LLM Tool Calling 可行性验证

Agent 架构依赖 function calling，不确定 GLM-5.1 是否支持。不支持则架构需推翻。

验证：写独立脚本测试 API 的 `tools` 参数和 `tool_calls` 响应。结果：GLM-5.1 完整支持，且返回 `reasoning_content`（推理模型）。

---

## 4. Agent 自纠错机制

LLM 单次生成 FreeCAD 代码成功率约 50%，常见错误：布尔运算 OCCError、translate/cut 语义混淆、对象查找返回 None。

解决：Agent 模式下 LLM 看到 exec 的错误 traceback，自动分析原因并修正重试。这是 Agent 与单次调用的核心区别。

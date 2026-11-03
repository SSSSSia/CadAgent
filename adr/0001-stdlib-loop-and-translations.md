# 标准库、循环与界面文案是分开的

CadAgent 跑在 FreeCAD 自带的 Python 里。这个决定约束了下面三件事。

## HTTP 用 urllib

FreeCAD 不保证能装 `requests`。LLM 和视觉请求都走 `urllib`。停止按钮关掉套接字，而不是依赖第三方的取消令牌。

## AgentLoop 不碰界面

`agent/loop.py` 返回 `CallLlmAction`、`ExecuteToolsAction` 或 `FinishAction`。面板只按种类读自己的字段。这样循环可以在没有 Qt 的 pytest 里跑完，几何调用留在主线程。

## 文案用字符串表加 TS 文件

界面句子不多，运行时不能假设装了 Qt Linguist。`ui/strings.py` 仍是键，中文句子放在 `resources/translations/cadagent_zh.ts`。面板直接读这份 XML。`QTranslator` 只在有人用 `lrelease` 生成 `.qm` 时安装，不是启动的前提。

# 参与 CadAgent

CadAgent 是 FreeCAD 的一个工作台目录，不是用 pip 装进解释器的库。FreeCAD 通过 `Mod/CadAgent/InitGui.py` 加载它。

## 环境

1. 安装 FreeCAD 1.1 或更新的版本。
2. 把本仓库放到 FreeCAD 的 `Mod/CadAgent`（用户目录或安装目录都可以）。文件夹名必须是 `CadAgent`。
3. 也可以用 Addon Manager 安装：仓库根目录的 `package.xml` 是元数据。
4. 复制 `.env.example` 为 `.env`，填入 OpenAI 兼容接口。不要提交 `.env`。

运行时只使用 Python 标准库和 FreeCAD 自带的模块。不要往工作台里加第三方依赖。

## 检查

在仓库根目录，用系统 Python（不需要 FreeCAD）：

```bash
python -m ruff check .
python -m pytest tests/ -q --tb=line
```

真机行为用 FreeCAD 自带的解释器：

```bash
<FreeCAD>/bin/python.exe scripts/verify_freecad_behavior.py
```

## 代码

- `agent/loop.py` 不导入 Qt 或 FreeCAD。界面在 `ui/`，几何在主线程执行。
- `InitGui.py` 由 FreeCAD `exec()` 加载。方法体里要用局部导入，不能依赖文件顶层的名字。
- 配置常量通过 `import core.config as _config` 读取，这样设置对话框 `reload()` 之后能拿到新值。
- 用户可见的句子放在 `ui/strings.py` 的英中两张表里。改完后重新生成 `resources/translations/cadagent_zh.ts`（见下）。面板读这份 TS。旁边如果有 `lrelease` 编出来的 `cadagent_zh.qm`，启动时会再装一个 `QTranslator`；没有 `.qm` 也不影响面板。

```bash
python -c "from ui.catalog import build_ts, ts_path; from ui.strings import _EN, _ZH; open(ts_path(), 'w', encoding='utf-8').write(build_ts(_EN, _ZH))"
```

## 拉取请求

一个改动一个主题。说明为什么改，以及 `pytest` 的结果。真机脚本如果跑过，写上通过或没跑。不要提交 `.env`、会话记录和 `__pycache__`。

## 文档

公开行为写在模块 docstring 里。`docs/` 是本地计划，不进 git。架构取舍见 `adr/`。

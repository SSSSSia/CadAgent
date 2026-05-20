import os
import sys

import FreeCAD
import FreeCADGui as Gui

# FreeCAD 通过 exec() 加载 InitGui.py，此时 __file__ 不可用，Python 也不知道本插件
# 的其他模块（AiDesignPanel 等）在哪里。必须手动定位插件目录并加入 sys.path，
# 否则后续的 from AiDesignPanel import ... 会报 ModuleNotFoundError。
_mod_dir = os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "AiSonarDesign")
if not os.path.isdir(_mod_dir):
    # 用户目录下没有则回退到 FreeCAD 安装目录
    _mod_dir = os.path.normpath(os.path.join(FreeCAD.getHomePath(), "Mod", "AiSonarDesign"))
if _mod_dir not in sys.path:
    sys.path.insert(0, _mod_dir)


# FreeCAD exec() 作用域陷阱：InitGui.py 被 exec() 加载时，文件内定义的顶层名称
# （函数、类）在其方法体中不可作为全局变量使用。方法体只能访问：
#   1. FreeCAD 预注入的名称（FreeCAD, Gui, Workbench 等）
#   2. self 及其属性
#   3. 方法体内局部 import 的模块
# 因此下方所有方法体内部都使用局部 import 来引入依赖。
class AiCadAgentWorkbench(Workbench):
    MenuText = "AI CAD Agent"
    ToolTip = "AI-powered CAD design agent"
    Icon = ""

    def Initialize(self):
        """首次切换到此工作台时调用，注册工具栏按钮。"""
        self.appendToolbar("AI Agent", ["AiCad_ShowPanel"])

    def Activated(self):
        """每次切换到此工作台时调用，创建并显示 Agent panel。"""
        from PySide6 import QtCore
        from AgentPanel import AgentPanel
        if not hasattr(Gui, '_ai_panel') or Gui._ai_panel is None:
            Gui._ai_panel = AgentPanel()
            Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, Gui._ai_panel)
        Gui._ai_panel.show()
        Gui._ai_panel.raise_()

    def Deactivated(self):
        """切换离开此工作台时调用。"""
        pass


# FreeCAD Command 协议：需要实现 GetResources / Activated / IsActive 三个方法。
# 工具栏按钮点击时触发 Activated。
class _ShowPanelCmd:
    def GetResources(self):
        return {
            "MenuText": "AI CAD Agent",
            "ToolTip": "Open the AI CAD agent panel",
        }

    def Activated(self):
        from PySide6 import QtCore
        from AgentPanel import AgentPanel
        if not hasattr(Gui, '_ai_panel') or Gui._ai_panel is None:
            Gui._ai_panel = AgentPanel()
            Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, Gui._ai_panel)
        Gui._ai_panel.show()
        Gui._ai_panel.raise_()

    def IsActive(self):
        return True


# 注册命令和工作台到 FreeCAD GUI 系统，必须在文件末尾执行。
# addCommand 的第一个参数是命令 ID，与工作台 Initialize 中引用的一致。
Gui.addCommand("AiCad_ShowPanel", _ShowPanelCmd())
Gui.addWorkbench(AiCadAgentWorkbench())

FreeCAD.Console.PrintMessage("AiCadAgent workbench loaded.\n")

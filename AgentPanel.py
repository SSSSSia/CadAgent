"""
AgentPanel — chat-style dock panel for the AI CAD Agent.

Thread safety model:
  - LLM API calls run in a background QThread (slow, network I/O)
  - Tool execution (exec(), FreeCAD API) runs in the main thread
  - State machine alternates between: call_llm (background) -> execute_tools (main) -> repeat
"""
from __future__ import annotations

import FreeCAD
import FreeCADGui as Gui

from PySide6 import QtCore, QtWidgets

from agent_controller import AgentController
from session_manager import ChatSession
from doc_analyzer import analyze_document


class _LlmCallThread(QtCore.QThread):
    """Background thread: ONLY calls the LLM API. No FreeCAD operations."""
    responseReady = QtCore.Signal(dict)
    error = QtCore.Signal(str)

    def __init__(self, messages, tools, parent=None):
        super().__init__(parent)
        self.messages = messages
        self.tools = tools

    def run(self):
        try:
            from agent_controller import call_llm_with_tools
            data = call_llm_with_tools(self.messages, tools=self.tools)
            self.responseReady.emit(data)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class AgentPanel(QtWidgets.QDockWidget):
    """Chat-style dock panel for AI CAD Agent."""

    MAX_ITERATIONS = 8

    def __init__(self, parent=None):
        super().__init__("AI CAD Agent", parent)
        self._session = ChatSession()
        self._controller = None
        self._iteration = 0
        self._stopped = False
        self._llm_thread = None
        self._setup_ui()

    # ---- UI construction ----

    def _setup_ui(self):
        self.setMinimumWidth(380)
        self.setMinimumHeight(480)
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable
        )

        container = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(container)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        # --- Chat history ---
        self.chat_display = QtWidgets.QTextBrowser()
        self.chat_display.setOpenExternalLinks(False)
        self.chat_display.setStyleSheet(
            "QTextBrowser {"
            "  font-family: 'Segoe UI', sans-serif;"
            "  font-size: 13px;"
            "  background: #ffffff;"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 8px;"
            "}"
        )
        main_layout.addWidget(self.chat_display, 1)

        # --- Input area ---
        input_row = QtWidgets.QHBoxLayout()
        self.text_input = QtWidgets.QLineEdit()
        self.text_input.setPlaceholderText("Describe the part you want to design...")
        self.text_input.returnPressed.connect(self._on_send)
        input_row.addWidget(self.text_input, 1)

        self.btn_send = QtWidgets.QPushButton("Send")
        self.btn_send.setStyleSheet(
            "QPushButton{background:#4a90d9;color:white;padding:6px 16px;"
            "border-radius:3px;font-weight:bold}"
            "QPushButton:hover{background:#357abd}"
            "QPushButton:disabled{background:#aaa}"
        )
        self.btn_send.clicked.connect(self._on_send)
        input_row.addWidget(self.btn_send)
        main_layout.addLayout(input_row)

        # --- Control buttons ---
        ctrl_row = QtWidgets.QHBoxLayout()

        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setStyleSheet("padding:5px 12px")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        ctrl_row.addWidget(self.btn_stop)

        self.btn_new_session = QtWidgets.QPushButton("New Session")
        self.btn_new_session.setStyleSheet("padding:5px 12px")
        self.btn_new_session.clicked.connect(self._on_new_session)
        ctrl_row.addWidget(self.btn_new_session)

        ctrl_row.addStretch()
        main_layout.addLayout(ctrl_row)

        # --- Status bar ---
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("color:#666; font-size:11px;")
        main_layout.addWidget(self.status_label)

        self._append_system_msg(
            "AI CAD Agent ready. Describe a part and I'll create it in FreeCAD."
        )

        container.setLayout(main_layout)
        self.setWidget(container)

    # ---- Chat display helpers ----

    def _append_user_msg(self, text):
        self.chat_display.append(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:#e8f0fe; padding:8px 12px;">'
            f'<b style="color:#1a5276;">You:</b> {self._esc(text)}'
            f'</td></tr></table>'
        )
        self._scroll_bottom()

    def _append_agent_msg(self, text):
        html = self._markdown_to_html(text)
        self.chat_display.append(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:#f0faf4; padding:10px 12px; border-left:3px solid #0d904f;">'
            f'<b style="color:#0d904f;">Agent:</b><br>'
            f'{html}'
            f'</td></tr></table>'
        )
        self._scroll_bottom()

    def _append_tool_msg(self, iteration, name, desc, preview, is_error):
        icon = '<span style="color:#d32f2f;">&#10007;</span>' if is_error else '<span style="color:#2e7d32;">&#10003;</span>'
        label = f"[{iteration}] {name}"
        if desc:
            label += f" — {desc}"
        self.chat_display.append(
            f'<div style="margin:2px 0 2px 20px;font-size:12px;color:#888;">'
            f'{icon} {self._esc(label)}</div>'
        )
        self._scroll_bottom()

    def _append_system_msg(self, text):
        self.chat_display.append(
            f'<div style="margin:4px 0; color:#888; font-style:italic; '
            f'font-size:12px; text-align:center;">{self._esc(text)}</div>'
        )
        self._scroll_bottom()

    def _scroll_bottom(self):
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _esc(t):
        return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>")

    @staticmethod
    def _markdown_to_html(md_text):
        import re
        ph = []

        # 1. Extract code blocks → placeholders
        def _code(m):
            c = m.group(1).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            ph.append(
                '<pre style="background-color:#f4f4f4; padding:6px;'
                f'font-size:12px; margin:4px 0;">{c}</pre>')
            return f'\x01PH{len(ph)-1}\x01'
        text = re.sub(r'```[\w]*\n?(.*?)```', _code, md_text, flags=re.DOTALL)

        # 2. Extract tables → placeholders
        def _tbl(m):
            rows = []
            for ln in m.group(0).strip().split('\n'):
                ln = ln.strip()
                if not ln.startswith('|') or not ln.endswith('|'):
                    continue
                cells = [c.strip() for c in ln.split('|')[1:-1]]
                if all(set(c) <= {'-', ':', ' '} for c in cells):
                    continue
                rows.append([re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', c) for c in cells])
            if not rows:
                return ''
            h = '<table border="1" cellpadding="4" cellspacing="0" style="margin:4px 0; font-size:13px;">'
            for i, cells in enumerate(rows):
                tag = 'th' if i == 0 else 'td'
                h += '<tr>'
                for c in cells:
                    bg = 'background-color:#f0f4f8; font-weight:bold;' if tag == 'th' else ''
                    h += f'<{tag} style="padding:4px 8px; text-align:left; {bg}">{c}</{tag}>'
                h += '</tr>'
            ph.append(h + '</table>')
            return f'\x01PH{len(ph)-1}\x01'
        text = re.sub(r'(?:^\|.+\|[ \t]*$\n?)+', _tbl, text, flags=re.MULTILINE)

        # 3. Escape remaining HTML
        text = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

        # 4. Headers, lists, hr — line by line
        lines = text.split('\n')
        out, in_list, ltag = [], False, None
        for line in lines:
            s = line.strip()
            hm = re.match(r'^(#{1,3}) (.+)$', s)
            if hm:
                if in_list:
                    out.append(f'</{ltag}>')
                    in_list = False
                lv = min(len(hm.group(1)) + 1, 4)
                out.append(f'<h{lv} style="margin:8px 0 4px;">{hm.group(2)}</h{lv}>')
                continue
            if re.match(r'^---+$', s):
                if in_list:
                    out.append(f'</{ltag}>')
                    in_list = False
                out.append('<hr>')
                continue
            ol = re.match(r'^(\d+)\.\s+(.+)$', s)
            if ol:
                if not in_list or ltag != 'ol':
                    if in_list:
                        out.append(f'</{ltag}>')
                    out.append('<ol style="margin:4px 0 4px 20px;">')
                    in_list = True; ltag = 'ol'
                out.append(f'<li>{ol.group(2)}</li>')
                continue
            ul = re.match(r'^[-*]\s+(.+)$', s)
            if ul:
                if not in_list or ltag != 'ul':
                    if in_list:
                        out.append(f'</{ltag}>')
                    out.append('<ul style="margin:4px 0 4px 20px;">')
                    in_list = True; ltag = 'ul'
                out.append(f'<li>{ul.group(1)}</li>')
                continue
            if in_list:
                out.append(f'</{ltag}>')
                in_list = False
            out.append(line)
        if in_list:
            out.append(f'</{ltag}>')
        text = '\n'.join(out)

        # 5. Bold, inline code
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'`([^`]+)`', r'<code style="background-color:#f0f0f0; padding:1px 4px;">\1</code>', text)

        # 6. Newlines → <br>
        text = text.replace("\n", "<br>")

        # 6b. Remove spurious <br> around block elements (from step 4 line joins)
        for blk in ('ul', '/ul', 'ol', '/ol', 'li', '/li', 'hr', 'pre', 'table', '/table'):
            text = text.replace(f'<br><{blk}>', f'<{blk}>')

        # 7. Restore placeholders
        for i, blk in enumerate(ph):
            text = text.replace(f'\x01PH{i}\x01', blk)
        return text

    # ---- State machine: send -> call LLM (bg) -> execute tools (main) -> repeat ----

    def _set_running(self, running):
        self.btn_send.setEnabled(not running)
        self.text_input.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        if not running:
            self.text_input.setFocus()

    def _on_send(self):
        text = self.text_input.text().strip()
        if not text:
            return

        self._append_user_msg(text)
        self.text_input.clear()
        self._set_running(True)

        # Gather document context (main thread — safe)
        context = ""
        doc = FreeCAD.ActiveDocument
        if doc:
            try:
                context = analyze_document(doc)
            except Exception:
                pass

        # Initialize controller
        self._controller = AgentController(self._session)
        self._iteration = 0
        self._stopped = False
        self._mode = "auto"  # "auto" | "tool_calling" | "react"
        self._context = context

        # Add user message to session
        self._controller.session.add_user_message(text)

        # Set system prompt — start with tool calling version
        from agent_controller import AGENT_SYSTEM_PROMPT
        system_content = AGENT_SYSTEM_PROMPT.format(
            context=f"\nCURRENT DOCUMENT CONTEXT:\n{context}" if context else ""
        )
        self._controller.session.set_system_prompt(system_content)

        self.status_label.setText("Agent thinking...")
        self.status_label.setStyleSheet("color:#d4a017; font-size:11px;")

        # Start first LLM call
        self._call_llm()

    def _call_llm(self):
        """Kick off a background LLM API call."""
        if self._stopped or self._iteration >= self.MAX_ITERATIONS:
            self._finish("Agent stopped." if self._stopped else "Max iterations reached.", False)
            return

        self._iteration += 1

        # In react mode, don't send tools parameter (model doesn't support it)
        tools = self._get_tools() if self._mode != "react" else None

        self._llm_thread = _LlmCallThread(
            self._controller.session.get_messages(),
            tools,
        )
        self._llm_thread.responseReady.connect(self._on_llm_response)
        self._llm_thread.error.connect(self._on_llm_error)
        self._llm_thread.start()

    @staticmethod
    def _get_tools():
        from tool_definitions import TOOL_DEFINITIONS
        return TOOL_DEFINITIONS

    def _on_llm_response(self, data):
        """Handle LLM response — runs in main thread via signal."""
        from agent_controller import parse_react_tool_calls, REACT_SYSTEM_PROMPT

        choice = data["choices"][0]
        assistant_msg = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")
        content = assistant_msg.get("content", "")

        self._controller.session.add_assistant_message(assistant_msg)

        # --- Mode auto-detection (first iteration) ---
        if self._mode == "auto" and finish_reason == "stop" and self._iteration == 1:
            parsed = parse_react_tool_calls(content)
            if parsed:
                # Model doesn't support tool calling, switch to ReAct
                self._mode = "react"
                self._append_system_msg("Model does not support tool calling, switched to ReAct mode.")
                # Switch system prompt
                react_prompt = REACT_SYSTEM_PROMPT.format(
                    context=f"\nCURRENT DOCUMENT CONTEXT:\n{self._context}" if self._context else ""
                )
                self._controller.session.set_system_prompt(react_prompt)
                # Execute the parsed tool calls
                self._execute_tools(parsed)
                return
            else:
                # Model returned a final answer directly
                self._mode = "tool_calling"
                self._finish(content, True)
                return

        # --- Tool calling mode (native API) ---
        if finish_reason == "tool_calls":
            self._mode = "tool_calling"
            tool_calls = assistant_msg.get("tool_calls", [])
            self._execute_tools(tool_calls)
            return

        # --- ReAct mode: check for <tool> tags in text ---
        if self._mode == "react":
            parsed = parse_react_tool_calls(content)
            if parsed:
                self._execute_tools(parsed)
                return
            # No tool tags — model is done
            self._finish(content, True)
            return

        # --- finish_reason == "stop" with no tool tags — agent done ---
        self._finish(content, True)

    def _on_llm_error(self, msg):
        self._finish(f"API error: {msg}", False)

    def _execute_tools(self, tool_calls):
        """Execute tools in the MAIN thread (safe for FreeCAD)."""
        import json
        from agent_tools import dispatch_tool

        for tc in tool_calls:
            if self._stopped:
                break

            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", "{}")
            tool_id = tc.get("id", "")

            desc = ""
            if tool_name == "execute_code":
                try:
                    desc = json.loads(tool_args).get("description", "")
                except Exception:
                    pass

            # Execute tool in main thread (FreeCAD safe)
            tool_result = dispatch_tool(tool_name, tool_args)

            # ReAct mode: use user message for tool results (model doesn't understand role="tool")
            if self._mode == "react":
                self._controller.session.add_user_message(
                    f"[Tool Result for {tool_name}]:\n{tool_result}"
                )
            else:
                self._controller.session.add_tool_result(tool_id, tool_result)

            is_error = tool_result.startswith("ERROR")
            self._append_tool_msg(
                self._iteration, tool_name, desc,
                tool_result[:200], is_error,
            )
            if is_error:
                self._controller.result.errors.append(
                    f"[Iter {self._iteration}] {tool_name}: {tool_result[:100]}"
                )
            self._controller.result.tool_calls_log.append({
                "iteration": self._iteration,
                "name": tool_name,
                "description": desc,
                "result_preview": tool_result[:200],
                "is_error": is_error,
            })

        # Tools done — next iteration
        self.status_label.setText(f"Agent thinking... (iteration {self._iteration + 1}/{self.MAX_ITERATIONS})")
        self._call_llm()

    def _finish(self, summary, success):
        """Agent loop complete — show results."""
        self._append_agent_msg(summary)

        if success:
            self._controller.result.success = True
            self._controller.result.summary = summary
            self._controller.session.update_summary(summary)

            # Snapshot document state + fit view
            try:
                doc = FreeCAD.ActiveDocument
                if doc:
                    self._controller.session.update_document_state(analyze_document(doc))
            except Exception:
                pass
            try:
                view = Gui.activeDocument().activeView()
                view.viewIsometric()
                view.fitAll()
            except Exception:
                pass

        turns = self._controller.session.user_turn_count()
        iters = self._iteration
        if success:
            self.status_label.setText(f"Done | {iters} iterations | Turn {turns}")
            self.status_label.setStyleSheet("color:#0d904f; font-size:11px;")
        else:
            self.status_label.setText(f"Failed | {iters} iterations | Turn {turns}")
            self.status_label.setStyleSheet("color:#d32f2f; font-size:11px;")

        self._set_running(False)

    def _on_stop(self):
        self._stopped = True
        self.status_label.setText("Stopping...")

    def _on_new_session(self):
        self._stopped = True
        if self._llm_thread and self._llm_thread.isRunning():
            self._llm_thread.quit()
            self._llm_thread.wait(1000)
        self._session = ChatSession()
        self._controller = None
        self.chat_display.clear()
        self._append_system_msg("New session started. Describe a part to begin.")
        self.status_label.setText("Ready")
        self.status_label.setStyleSheet("color:#666; font-size:11px;")
        self._set_running(False)

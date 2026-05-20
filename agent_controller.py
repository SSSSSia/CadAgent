"""
Agent controller — the core agentic loop.

Orchestrates the ReAct-style loop: call LLM with tools → execute tools → feed
results back → repeat until the agent signals completion or max iterations reached.
"""
from __future__ import annotations

import json
import re
import urllib.request

from llm_engine import API_BASE_URL, API_KEY, MODEL_NAME, _strip_markdown
from tool_definitions import TOOL_DEFINITIONS
from agent_tools import dispatch_tool
from session_manager import ChatSession
from doc_analyzer import analyze_document

import FreeCAD

MAX_ITERATIONS = 8

# ---------------------------------------------------------------------------
# Text ReAct parser — 从 LLM 自由文本中提取 <tool> 标签
# ---------------------------------------------------------------------------

_TOOL_TAG_RE = re.compile(
    r'<tool\s+name=["\'](\w+)["\']>\s*(.*?)\s*</tool>',
    re.DOTALL,
)


def parse_react_tool_calls(text: str) -> list[dict]:
    """Parse <tool name="xxx">...</tool> tags from LLM text output.

    Returns list of synthetic tool_call dicts matching the OpenAI format:
        [{"id": "react_N", "function": {"name": "...", "arguments": "..."}}]
    """
    calls = []
    for i, m in enumerate(_TOOL_TAG_RE.finditer(text)):
        name = m.group(1)
        args_raw = m.group(2).strip()
        # ensure arguments is valid JSON
        try:
            json.loads(args_raw)
        except (json.JSONDecodeError, ValueError):
            # wrap plain text as {"input": ...} for tools that accept simple args
            if not args_raw or args_raw in ("{}", ""):
                args_raw = "{}"
            else:
                args_raw = json.dumps({"input": args_raw})
        calls.append({
            "id": f"react_{i}",
            "function": {"name": name, "arguments": args_raw},
        })
    return calls

# ---------------------------------------------------------------------------
# Agent system prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """\
You are an expert FreeCAD CAD agent. You create and refine 3D mechanical parts \
using FreeCAD's Python API. You work iteratively: write code, execute it, \
analyze results, and refine until the design meets requirements.

AVAILABLE TOOLS:
- execute_code: Run FreeCAD Python code. Modules pre-imported: FreeCAD, Part, math, Gui.
- analyze_geometry: Inspect current document geometry.
- validate_design: Check design against requirements.

WORKFLOW:
1. Read the user's design requirements carefully.
2. Plan your approach (what primitives, what boolean ops, what order).
3. Write and execute code via execute_code.
4. After execution, call analyze_geometry to verify the result.
5. If errors occur or design doesn't match, fix the code and retry.
6. Call validate_design for final check.
7. When satisfied, respond with a summary (no tool call) to signal completion.

RULES:
- Pre-imported modules: FreeCAD, Part, math, FreeCADGui (as Gui)
- Create doc: doc = FreeCAD.newDocument("Design")
- Add shapes: obj = doc.addObject("Part::Feature", "Name"); obj.Shape = shape
- Boolean: a.cut(b)/a.fuse(b)/a.common(b) return NEW shapes
- Translate: shape.translate(FreeCAD.Vector(x,y,z)) modifies IN-PLACE
- All dimensions in mm. No fillet or chamfer.
- End each code block with doc.recompute()
- Keep each code block focused on one logical step
- If code fails, read the error carefully, understand it, fix the specific issue, retry
- Do NOT repeat the same mistake

Part API Quick Reference:
- Part.makeBox(x,y,z)      box from origin +X +Y +Z
- Part.makeCylinder(r,h)    along Z axis, from 0 to h
- Part.makeCone(r1,r2,h)
- Part.makeSphere(r)
- Part.makeTorus(r1,r2)
- shape.translate(FreeCAD.Vector(x,y,z))   IN-PLACE
- a.cut(b)                  NEW shape A minus B
- a.fuse(b)                 NEW shape A union B
- a.common(b)               NEW shape intersection
- FreeCAD.Vector(x,y,z)

{context}"""

# 备选 System Prompt：当模型不支持 tool calling 时使用
# 教 LLM 用固定文本格式输出工具调用，由代码解析
REACT_SYSTEM_PROMPT = """\
You are an expert FreeCAD CAD agent. You create and refine 3D mechanical parts \
using FreeCAD's Python API. You work iteratively: write code, execute it, \
analyze results, and refine until the design meets requirements.

TOOL CALLING FORMAT — you MUST use this exact format to call tools:

<tool name="execute_code">
{"code": "your code here", "description": "what it does"}
</tool>

<tool name="analyze_geometry">
{}
</tool>

<tool name="validate_design">
{"requirements": "user requirements to check against"}
</tool>

Available tools:
- execute_code: Run FreeCAD Python code (FreeCAD, Part, math, Gui pre-imported)
- analyze_geometry: Inspect current document geometry (no args needed, use {})
- validate_design: Check design against requirements

WORKFLOW:
1. Read requirements. Think about approach.
2. Call execute_code to create/modify geometry.
3. Call analyze_geometry to verify.
4. If errors, fix and retry. If satisfied, respond with a summary WITHOUT any <tool> tags.

RULES:
- Pre-imported: FreeCAD, Part, math, FreeCADGui (as Gui)
- Create doc: doc = FreeCAD.newDocument("Design")
- Add shapes: obj = doc.addObject("Part::Feature", "Name"); obj.Shape = shape
- Boolean: a.cut(b)/a.fuse(b)/a.common(b) return NEW shapes
- Translate: shape.translate(FreeCAD.Vector(x,y,z)) modifies IN-PLACE
- All dims in mm. No fillet or chamfer. End with doc.recompute()
- When done, respond with plain text summary (NO <tool> tags)

Part API:
- Part.makeBox(x,y,z), Part.makeCylinder(r,h), Part.makeCone(r1,r2,h)
- Part.makeSphere(r), Part.makeTorus(r1,r2)
- shape.translate(Vector) IN-PLACE, a.cut(b) NEW, a.fuse(b) NEW
- FreeCAD.Vector(x,y,z)

{context}"""

# ---------------------------------------------------------------------------
# LLM API call with tool support
# ---------------------------------------------------------------------------

def call_llm_with_tools(messages: list[dict],
                        tools: list[dict] | None = None,
                        temperature: float = 0.1) -> dict:
    """Call SiliconFlow API with optional tool definitions. Returns raw JSON."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if tools:
        payload["tools"] = tools

    req = urllib.request.Request(
        API_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Agent result
# ---------------------------------------------------------------------------

class AgentResult:
    """Outcome of an agent run."""
    def __init__(self):
        self.success: bool = False
        self.summary: str = ""
        self.iterations: int = 0
        self.errors: list[str] = []
        self.tool_calls_log: list[dict] = []  # [{name, description, result_preview, is_error}]


# ---------------------------------------------------------------------------
# Agent controller
# ---------------------------------------------------------------------------

class AgentController:
    """Runs the agentic loop for a single user request.

    自动检测模型是否支持 tool calling：
    - 第一次 API 调用尝试带 tools 参数
    - 如果返回 tool_calls → 正常模式
    - 如果返回纯文本 → 降级到文本 ReAct 模式（解析 <tool> 标签）
    """

    def __init__(self, session: ChatSession):
        self.session = session
        self.result = AgentResult()
        self._stopped = False
        self._mode = "auto"  # "auto" | "tool_calling" | "react"

    def stop(self):
        self._stopped = True

    def run(self, user_prompt: str, context: str = "") -> AgentResult:
        """
        Run the agent loop with auto-detection of tool calling support.

        First call tries with tools parameter. If the model returns plain text
        instead of tool_calls, switches to ReAct text parsing mode permanently.
        """
        self.result = AgentResult()

        # Build system prompt — start with tool calling prompt
        system_content = AGENT_SYSTEM_PROMPT.format(
            context=f"\nCURRENT DOCUMENT CONTEXT:\n{context}" if context else ""
        )
        self.session.set_system_prompt(system_content)
        self.session.add_user_message(user_prompt)

        iteration = 0

        while iteration < MAX_ITERATIONS and not self._stopped:
            iteration += 1

            # Decide whether to send tools parameter
            use_tools = self._mode in ("auto", "tool_calling")
            try:
                response = call_llm_with_tools(
                    self.session.get_messages(),
                    tools=TOOL_DEFINITIONS if use_tools else None,
                )
            except Exception as e:
                self.result.errors.append(f"API call failed: {type(e).__name__}: {e}")
                break

            choice = response["choices"][0]
            assistant_msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "")
            content = assistant_msg.get("content", "")

            self.session.add_assistant_message(assistant_msg)

            # --- Mode detection (first iteration only) ---
            if self._mode == "auto" and finish_reason == "stop" and iteration == 1:
                # Check if the text contains <tool> tags — model doesn't support
                # native tool calling but is following the ReAct text format
                parsed = parse_react_tool_calls(content)
                if parsed:
                    self._mode = "react"
                    # Switch system prompt to ReAct version
                    react_prompt = REACT_SYSTEM_PROMPT.format(
                        context=f"\nCURRENT DOCUMENT CONTEXT:\n{context}" if context else ""
                    )
                    self.session.set_system_prompt(react_prompt)
                else:
                    # Model genuinely returned a final answer without tools
                    self._mode = "tool_calling"

            # --- Handle tool_calls mode (native API tool calling) ---
            if finish_reason == "tool_calls":
                if self._mode == "auto":
                    self._mode = "tool_calling"
                tool_calls = assistant_msg.get("tool_calls", [])
                self._execute_tool_calls(tool_calls, iteration)
                continue

            # --- Handle ReAct text mode (parsed <tool> tags) ---
            if self._mode == "react":
                parsed = parse_react_tool_calls(content)
                if parsed:
                    self._execute_tool_calls(parsed, iteration)
                    # In ReAct mode, add tool results as user messages
                    # since the model doesn't understand role="tool"
                    continue
                # No <tool> tags found — model is done
                self.result.success = True
                self.result.summary = content
                self.result.iterations = iteration
                self.session.update_summary(content)
                break

            # --- finish_reason == "stop" and no tool tags — agent done ---
            self.result.success = True
            self.result.summary = content
            self.result.iterations = iteration
            self.session.update_summary(content)

            try:
                doc = FreeCAD.ActiveDocument
                if doc:
                    self.session.update_document_state(analyze_document(doc))
            except Exception:
                pass
            break

        self.result.iterations = iteration

        if self._stopped:
            self.result.summary = "Agent stopped by user."
        elif iteration >= MAX_ITERATIONS:
            self.result.summary = "Agent reached maximum iterations."
            self.result.errors.append(f"Exceeded max iterations ({MAX_ITERATIONS})")

        return self.result

    def _execute_tool_calls(self, tool_calls: list[dict], iteration: int):
        """Execute a list of tool calls and append results to session."""
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

            tool_result = dispatch_tool(tool_name, tool_args)

            # In ReAct mode, append tool result as user message
            # because models without tool calling don't understand role="tool"
            if self._mode == "react":
                self.session.add_user_message(
                    f"[Tool Result for {tool_name}]:\n{tool_result}"
                )
            else:
                self.session.add_tool_result(tool_id, tool_result)

            is_error = tool_result.startswith("ERROR")
            self.result.tool_calls_log.append({
                "iteration": iteration,
                "name": tool_name,
                "description": desc,
                "result_preview": tool_result[:200],
                "is_error": is_error,
            })
            if is_error:
                self.result.errors.append(
                    f"[Iter {iteration}] {tool_name}: {tool_result[:100]}"
                )

"""
LLM engine — call remote API and return FreeCAD Python code.
Uses only stdlib (urllib) so no extra packages are needed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request


def _load_env() -> dict:
    """从 .env 文件加载配置到环境变量（不覆盖已有值），然后返回配置字典。"""
    defaults = {
        "API_BASE_URL": "https://api.siliconflow.cn/v1",
        "API_KEY": "",
        "MODEL_NAME": "Pro/zai-org/GLM-5.1",
    }
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value
    return {k: os.environ.get(k, v) for k, v in defaults.items()}


_cfg = _load_env()
API_BASE_URL = _cfg["API_BASE_URL"]
API_KEY = _cfg["API_KEY"]
MODEL_NAME = _cfg["MODEL_NAME"]

# ---------------------------------------------------------------------------
# System prompt: teach LLM to write FreeCAD Part API code
# ---------------------------------------------------------------------------
# System Prompt 设计要点：
#   1. 明确告诉 LLM 不需要写 import（已预注入），减少生成行数
#   2. 附带 Part API 速查表，约束 LLM 只使用这些 API，降低出错率
#   3. 强调 translate() 是原地修改、cut/fuse 返回新对象，这是 LLM 最容易搞错的点
#   4. 限制 30 行以内，避免生成过长代码导致 exec 执行出错后难以调试
SYSTEM_PROMPT_NEW = """\
You are a FreeCAD Python scripting expert. Given a natural language \
description of a mechanical part, generate FreeCAD Python code to create \
it as a 3D model.

STRICT OUTPUT RULES:
1. Only return valid Python code. No markdown fences. No explanations.
2. Pre-imported: FreeCAD, Part, math, FreeCADGui (as Gui)
3. Create doc: doc = FreeCAD.newDocument("Design")
4. Build shapes with Part module, add to document:
   obj = doc.addObject("Part::Feature", "Name")
   obj.Shape = some_shape
5. Boolean: a.cut(b) / a.fuse(b) / a.common(b) return NEW shapes
6. Position: shape.translate(FreeCAD.Vector(x,y,z)) modifies IN-PLACE
7. Circular patterns: for-loop + math.cos / math.sin
8. All dims in mm. No fillet or chamfer. Under 30 lines.
9. End with:  doc.recompute()  (no other lines needed after this)

Part API:
- Part.makeBox(x,y,z)      box from origin +X +Y +Z
- Part.makeCylinder(r,h)    along Z, 0 to h
- Part.makeCone(r1,r2,h)
- Part.makeSphere(r)
- Part.makeTorus(r1,r2)
- shape.translate(Vector)   IN-PLACE
- a.cut(b)                  NEW shape A-B
- a.fuse(b)                 NEW shape A+B
- a.common(b)               NEW shape intersection
- FreeCAD.Vector(x,y,z)

EXAMPLE - flanged cylinder with bolt holes:
doc = FreeCAD.newDocument("Design")
body = Part.makeCylinder(100, 360)
ft = Part.makeCylinder(125, 20)
ft.translate(FreeCAD.Vector(0, 0, 360))
fb = Part.makeCylinder(125, 20)
outer = body.fuse(ft).fuse(fb)
inner = Part.makeCylinder(88, 400)
inner.translate(FreeCAD.Vector(0, 0, -20))
shell = outer.cut(inner)
for i in range(12):
    a = 2 * math.pi * i / 12
    h = Part.makeCylinder(5, 20)
    h.translate(FreeCAD.Vector(115*math.cos(a), 115*math.sin(a), 360))
    shell = shell.cut(h)
obj = doc.addObject("Part::Feature", "Housing")
obj.Shape = shell
doc.recompute()
"""

SYSTEM_PROMPT_MODIFY = """\
You are a FreeCAD Python scripting expert. You will MODIFY an existing \
FreeCAD document based on the user's request.

CURRENT DOCUMENT CONTEXT:
{context}

STRICT OUTPUT RULES:
1. Only return valid Python code. No markdown fences. No explanations.
2. Pre-imported: FreeCAD, Part, math, FreeCADGui (as Gui)
3. Access existing doc: doc = FreeCAD.ActiveDocument
4. Find existing objects: doc.getObjectsByLabel("name") or doc.Objects
5. Modify shapes: get obj.Shape, perform boolean ops, reassign obj.Shape
6. Add new objects: doc.addObject("Part::Feature", "Name")
7. Boolean: a.cut(b) / a.fuse(b) / a.common(b) return NEW shapes
8. Position: shape.translate(FreeCAD.Vector(x,y,z)) modifies IN-PLACE
9. Circular patterns: for-loop + math.cos / math.sin
10. All dims in mm. No fillet or chamfer. Under 30 lines.
11. End with: doc.recompute()

Part API:
- Part.makeBox(x,y,z)      box from origin +X +Y +Z
- Part.makeCylinder(r,h)    along Z, 0 to h
- Part.makeCone(r1,r2,h)
- Part.makeSphere(r)
- Part.makeTorus(r1,r2)
- shape.translate(Vector)   IN-PLACE
- a.cut(b)                  NEW shape A-B
- a.fuse(b)                 NEW shape A+B
- FreeCAD.Vector(x,y,z)

EXAMPLE - add bolt holes to existing flange:
doc = FreeCAD.ActiveDocument
obj = doc.getObjectsByLabel("Housing")[0]
shape = obj.Shape
for i in range(12):
    a = 2 * math.pi * i / 12
    h = Part.makeCylinder(5, 20)
    h.translate(FreeCAD.Vector(115*math.cos(a), 115*math.sin(a), 360))
    shape = shape.cut(h)
obj.Shape = shape
doc.recompute()
"""

SYSTEM_PROMPT_DERIVE = """\
You are a FreeCAD Python scripting expert. You will DERIVE a NEW part \
based on an existing FreeCAD document. The new part should be a companion \
or mating part (e.g. end cap, bracket, mounting plate).

CURRENT DOCUMENT CONTEXT (reference geometry):
{context}

STRICT OUTPUT RULES:
1. Only return valid Python code. No markdown fences. No explanations.
2. Pre-imported: FreeCAD, Part, math, FreeCADGui (as Gui)
3. Create NEW doc: doc = FreeCAD.newDocument("Derived")
4. Build the new part using dimensions from the reference context
5. Build shapes with Part module, add to document:
   obj = doc.addObject("Part::Feature", "Name")
   obj.Shape = some_shape
6. Boolean: a.cut(b) / a.fuse(b) / a.common(b) return NEW shapes
7. Position: shape.translate(FreeCAD.Vector(x,y,z)) modifies IN-PLACE
8. Circular patterns: for-loop + math.cos / math.sin
9. All dims in mm. No fillet or chamfer. Under 30 lines.
10. End with: doc.recompute()

Part API:
- Part.makeBox(x,y,z)      box from origin +X +Y +Z
- Part.makeCylinder(r,h)    along Z, 0 to h
- Part.makeCone(r1,r2,h)
- Part.makeSphere(r)
- Part.makeTorus(r1,r2)
- shape.translate(Vector)   IN-PLACE
- a.cut(b)                  NEW shape A-B
- a.fuse(b)                 NEW shape A+B
- FreeCAD.Vector(x,y,z)
"""

SYSTEM_PROMPT_VARIANT = """\
You are a FreeCAD Python scripting expert. You will create a PARAMETRIC \
VARIANT of an existing part. Keep the same topology/structure but change \
dimensions as the user requests.

CURRENT DOCUMENT CONTEXT (reference geometry):
{context}

STRICT OUTPUT RULES:
1. Only return valid Python code. No markdown fences. No explanations.
2. Pre-imported: FreeCAD, Part, math, FreeCADGui (as Gui)
3. Create NEW doc: doc = FreeCAD.newDocument("Variant")
4. Rebuild the same structure with updated dimensions from user request
5. Build shapes with Part module, add to document:
   obj = doc.addObject("Part::Feature", "Name")
   obj.Shape = some_shape
6. Boolean: a.cut(b) / a.fuse(b) / a.common(b) return NEW shapes
7. Position: shape.translate(FreeCAD.Vector(x,y,z)) modifies IN-PLACE
8. Circular patterns: for-loop + math.cos / math.sin
9. All dims in mm. No fillet or chamfer. Under 30 lines.
10. End with: doc.recompute()

Part API:
- Part.makeBox(x,y,z)      box from origin +X +Y +Z
- Part.makeCylinder(r,h)    along Z, 0 to h
- Part.makeCone(r1,r2,h)
- Part.makeSphere(r)
- Part.makeTorus(r1,r2)
- shape.translate(Vector)   IN-PLACE
- a.cut(b)                  NEW shape A-B
- a.fuse(b)                 NEW shape A+B
- FreeCAD.Vector(x,y,z)
"""

# 兼容旧代码的别名
SYSTEM_PROMPT = SYSTEM_PROMPT_NEW


def _strip_markdown(text: str) -> str:
    """去掉 LLM 输出中可能包裹的 markdown 代码块标记（```python ... ```）。

    虽然 System Prompt 要求不输出 markdown 标记，但 LLM 不一定严格遵守，
    必须在这里兜底清理，否则 exec() 会因为语法错误而失败。
    """
    text = text.strip()
    text = re.sub(r"^```(?:python)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def generate_freecad_code(user_description: str,
                          mode: str = "new",
                          context: str = "") -> str:
    """调用 LLM API 并返回可直接 exec() 的 Python 代码字符串。

    Args:
        user_description: 用户的自然语言描述（如 "法兰筒体 OD 200mm"）
        mode: 设计模式 — "new" 全新创建 | "modify" 修改现有 | "derive" 派生配合件 | "variant" 参数变体
        context: doc_analyzer 提取的文档几何文本（modify/derive/variant 模式必须提供）
    """
    prompt_map = {
        "new": SYSTEM_PROMPT_NEW,
        "modify": SYSTEM_PROMPT_MODIFY,
        "derive": SYSTEM_PROMPT_DERIVE,
        "variant": SYSTEM_PROMPT_VARIANT,
    }
    system_prompt = prompt_map.get(mode, SYSTEM_PROMPT_NEW)
    # modify/derive/variant 的 Prompt 含 {context} 占位符，替换为实际几何信息
    if "{context}" in system_prompt:
        system_prompt = system_prompt.format(context=context or "(No document context)")

    # temperature 设为 0.1：代码生成需要确定性输出，高 temperature 会导致 API 名称拼写错误
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_description},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode("utf-8")

    # 使用 urllib（标准库）而非 requests，因为 FreeCAD 内置 Python 不保证安装了第三方包
    req = urllib.request.Request(
        API_BASE_URL.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    content = data["choices"][0]["message"]["content"]
    code = _strip_markdown(content)
    if not code:
        raise ValueError("LLM returned empty response")
    return code

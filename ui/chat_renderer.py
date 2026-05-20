"""Chat display rendering — Markdown to HTML conversion and HTML helpers."""
from __future__ import annotations

import re


def esc(t: str) -> str:
    """Escape text for safe HTML embedding."""
    return (t.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\n", "<br>"))


def markdown_to_html(md_text: str) -> str:
    """Convert Markdown text to HTML for QTextBrowser display."""
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

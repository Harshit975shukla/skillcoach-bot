"""A small, safe Markdown subset rendered as Telegram HTML.

Lesson text uses **bold**, `inline code`, fenced ``` blocks, "#" headings and "-" bullets. Everything
else is escaped, so generated text can never inject Telegram entities or links.
"""

import html
import re

FENCE = re.compile(r"^\s*```([A-Za-z0-9_+-]{0,20})\s*$")
LANGUAGE = re.compile(r"^[A-Za-z0-9_+-]{1,20}$")


def _width(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def md_chunks(text: str, limit: int = 4000) -> list[str]:
    """Split on line boundaries; an open code fence is closed and reopened across chunks.

    Widths are Markdown source in UTF-16 units. Telegram counts its 4096 limit after parsing entities,
    and both the HTML and plain renderings only remove characters, so the source width is an upper bound.
    """
    parts, current, size, fence = [], [], 0, None
    reserve = 12

    def flush():
        nonlocal current, size
        if current:
            body = "\n".join(current)
            if fence is not None:
                body += "\n```"
            parts.append(body)
        current, size = ([f"```{fence}"], _width(fence) + 4) if fence is not None else ([], 0)

    for line in text.split("\n"):
        while _width(line) > limit - reserve - 30:
            cut = len(line)
            while _width(line[:cut]) > limit - reserve - 30:
                cut = int(cut * 0.8)
            head, line = line[:cut], line[cut:]
            if size + _width(head) + 1 > limit - reserve:
                flush()
            current.append(head)
            size += _width(head) + 1
        if size + _width(line) + 1 > limit - reserve and current:
            flush()
        match = FENCE.match(line)
        current.append(line)
        size += _width(line) + 1
        if match:
            fence = None if fence is not None else match.group(1)
    if current and not (fence is not None and current == [f"```{fence}"]):
        body = "\n".join(current)
        if fence is not None:
            body += "\n```"
        parts.append(body)
    return parts or [""]


def _inline(text: str) -> str:
    out, pos = [], 0
    for match in re.finditer(r"`([^`\n]+)`", text):
        out.append(_bold(text[pos : match.start()]))
        out.append("<code>" + html.escape(match.group(1), quote=False) + "</code>")
        pos = match.end()
    out.append(_bold(text[pos:]))
    return "".join(out)


def _bold(text: str) -> str:
    out, pos = [], 0
    for match in re.finditer(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", text):
        out.append(html.escape(text[pos : match.start()], quote=False))
        out.append("<b>" + html.escape(match.group(1), quote=False) + "</b>")
        pos = match.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def telegram_html(text: str) -> str:
    lines, out, code, language = text.split("\n"), [], None, ""
    for line in lines:
        match = FENCE.match(line)
        if match and code is None:
            code, language = [], match.group(1)
            continue
        if match and code is not None:
            out.append(_pre(code, language))
            code = None
            continue
        if code is not None:
            code.append(line)
            continue
        heading = re.match(r"^\s{0,3}#{1,4}\s+(.+)$", line)
        bullet = re.match(r"^(\s*)[-*]\s+(.+)$", line)
        if heading:
            out.append("<b>" + _inline(heading.group(1).strip().strip("*")) + "</b>")
        elif bullet:
            out.append(bullet.group(1) + "• " + _inline(bullet.group(2)))
        else:
            out.append(_inline(line))
    if code is not None:
        out.append(_pre(code, language))
    return "\n".join(out)


def _pre(lines, language):
    body = html.escape("\n".join(lines), quote=False)
    if LANGUAGE.match(language or ""):
        return f'<pre><code class="language-{language}">{body}</code></pre>'
    return f"<pre>{body}</pre>"


def plain(text: str) -> str:
    """Fallback when Telegram rejects the HTML: keep content, drop formatting markers."""
    out = []
    for line in text.split("\n"):
        if FENCE.match(line):
            continue
        line = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", line)
        line = re.sub(r"`([^`\n]+)`", r"\1", line)
        line = re.sub(r"^\s{0,3}#{1,4}\s+", "", line)
        out.append(line)
    return "\n".join(out)


def spans(text: str) -> list[dict]:
    """Inline text as typed spans for textContent-only rendering: text, code and bold."""
    out = []
    for piece in re.split(r"(`[^`\n]+`)", text):
        if not piece:
            continue
        if piece.startswith("`") and piece.endswith("`") and len(piece) > 1:
            out.append({"t": "code", "v": piece[1:-1]})
            continue
        pos = 0
        for match in re.finditer(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", piece):
            if match.start() > pos:
                out.append({"t": "text", "v": piece[pos : match.start()]})
            out.append({"t": "b", "v": match.group(1)})
            pos = match.end()
        if pos < len(piece):
            out.append({"t": "text", "v": piece[pos:]})
    return out


def md_blocks(text: str) -> list[dict]:
    """Parse the lesson Markdown subset into data blocks; nothing is ever interpreted as HTML."""
    blocks, paragraph, code, language = [], [], None, ""

    def close_paragraph():
        if paragraph:
            blocks.append({"type": "p", "spans": spans("\n".join(paragraph))})
            paragraph.clear()

    for line in (text or "").split("\n"):
        match = FENCE.match(line)
        if match and code is None:
            close_paragraph()
            code, language = [], match.group(1)
            continue
        if match:
            blocks.append({"type": "code", "lang": language, "text": "\n".join(code)})
            code = None
            continue
        if code is not None:
            code.append(line)
            continue
        bullet = re.match(r"^\s*[-*•]\s+(.+)$", line)
        number = re.match(r"^\s*(\d{1,2})[.)]\s+(.+)$", line)
        heading = re.match(r"^\s{0,3}#{1,4}\s+(.+)$", line)
        if not line.strip():
            close_paragraph()
        elif heading:
            close_paragraph()
            blocks.append({"type": "h", "spans": spans(heading.group(1).strip().strip("*"))})
        elif bullet or number:
            close_paragraph()
            kind = "ul" if bullet else "ol"
            item = spans(bullet.group(1) if bullet else number.group(2))
            if blocks and blocks[-1]["type"] == kind:
                blocks[-1]["items"].append(item)
            else:
                blocks.append({"type": kind, "items": [item], "start": int(number.group(1)) if number else 1})
        else:
            paragraph.append(line.strip())
    close_paragraph()
    if code is not None:
        blocks.append({"type": "code", "lang": language, "text": "\n".join(code)})
    return blocks

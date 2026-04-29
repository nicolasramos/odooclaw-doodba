import html
import re
from urllib.parse import urlparse


def markdown_to_safe_html(text):  # noqa: C901
    content = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not content:
        return ""

    blocks = []
    paragraph = []
    bullet_items = []
    ordered_items = []
    quote_lines = []
    table_lines = []
    code_lines = []
    code_language = ""
    in_code_block = False

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            parts = []
            for line in paragraph:
                if parts:
                    parts.append("<br />")
                parts.append(_render_inline(line))
            blocks.append(f"<p>{''.join(parts)}</p>")
            paragraph = []

    def flush_bullets():
        nonlocal bullet_items
        if bullet_items:
            items = "".join(f"<li>{_render_inline(item)}</li>" for item in bullet_items)
            blocks.append(f"<ul>{items}</ul>")
            bullet_items = []

    def flush_ordered():
        nonlocal ordered_items
        if ordered_items:
            items = "".join(
                f"<li>{_render_inline(item)}</li>" for item in ordered_items
            )
            blocks.append(f"<ol>{items}</ol>")
            ordered_items = []

    def flush_quotes():
        nonlocal quote_lines
        if quote_lines:
            rendered = markdown_to_safe_html("\n".join(quote_lines))
            blocks.append(f"<blockquote>{rendered}</blockquote>")
            quote_lines = []

    def flush_table():
        nonlocal table_lines
        if not table_lines:
            return
        parsed = _parse_table(table_lines)
        table_lines = []
        if not parsed:
            for line in parsed or []:
                paragraph.append(line)
            return

        header, rows = parsed
        head_html = "".join(f"<th>{_render_inline(cell)}</th>" for cell in header)
        body_html = "".join(
            f"<tr>{''.join(f'<td>{_render_inline(cell)}</td>' for cell in row)}</tr>"
            for row in rows
        )
        blocks.append(
            f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"
        )

    def flush_code_block():
        nonlocal code_lines, code_language
        if code_lines:
            escaped = html.escape("\n".join(code_lines), quote=False)
            class_attr = (
                f' class="language-{html.escape(code_language, quote=True)}"'
                if code_language
                else ""
            )
            blocks.append(f"<pre><code{class_attr}>{escaped}</code></pre>")
            code_lines = []
            code_language = ""

    def flush_non_code():
        flush_paragraph()
        flush_bullets()
        flush_ordered()
        flush_quotes()
        flush_table()

    for raw_line in content.split("\n"):
        stripped = raw_line.strip()

        if stripped.startswith("```"):
            flush_non_code()
            if in_code_block:
                flush_code_block()
            else:
                code_lines = []
                code_language = stripped[3:].strip()
            in_code_block = not in_code_block
            continue

        if in_code_block:
            code_lines.append(raw_line)
            continue

        if _is_table_line(stripped):
            flush_paragraph()
            flush_bullets()
            flush_ordered()
            flush_quotes()
            table_lines.append(stripped)
            continue
        flush_table()

        if stripped.startswith(">"):
            flush_paragraph()
            flush_bullets()
            flush_ordered()
            quote_lines.append(stripped[1:].lstrip())
            continue
        flush_quotes()

        bullet_match = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet_match:
            flush_paragraph()
            flush_ordered()
            bullet_items.append(bullet_match.group(1))
            continue

        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered_match:
            flush_paragraph()
            flush_bullets()
            ordered_items.append(ordered_match.group(1))
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_non_code()
            level = min(len(heading_match.group(1)), 6)
            rendered_heading = _render_inline(heading_match.group(2))
            blocks.append(f"<h{level}>{rendered_heading}</h{level}>")
            continue

        if not stripped:
            flush_non_code()
            continue

        paragraph.append(raw_line.rstrip())

    if in_code_block:
        flush_code_block()
    flush_non_code()
    return "\n".join(blocks)


def _render_inline(text):
    rendered = html.escape(text or "", quote=False)
    rendered = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", rendered)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"__(.+?)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", rendered)
    rendered = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"<em>\1</em>", rendered)
    rendered = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _render_link, rendered)
    return rendered


def _render_link(match):
    label = match.group(1)
    href = html.unescape(match.group(2)).strip()
    parsed = urlparse(href)
    if parsed.scheme and parsed.scheme not in ("http", "https", "mailto"):
        return label
    safe_href = html.escape(href, quote=True)
    return (
        f'<a href="{safe_href}" target="_blank" rel="noopener noreferrer">{label}</a>'
    )


def _is_table_line(line):
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _parse_table(lines):
    if len(lines) < 2:
        return None

    header = _split_table_row(lines[0])
    separator = _split_table_row(lines[1])
    if not header or len(header) != len(separator):
        return None
    if not all(re.match(r"^:?-{3,}:?$", cell.replace(" ", "")) for cell in separator):
        return None

    rows = []
    for line in lines[2:]:
        row = _split_table_row(line)
        if len(row) != len(header):
            return None
        rows.append(row)
    return header, rows


def _split_table_row(line):
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]

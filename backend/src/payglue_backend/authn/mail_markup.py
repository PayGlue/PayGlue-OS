# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The little formatting a mail body may carry, and both ways of reading it.

A body stays plain text with four marks on top: `## ` and `### ` start a
heading, lines that all start with `- ` or `1. ` make a list, `**word**` is bold
and `[text](https://...)` is a link with its own text. Everything else is
escaped, so a body can never inject markup into the branded mail.

The same body becomes the plain-text part too. There the marks fall away and a
link keeps its address in brackets, because a text mail cannot hide it.

Kept this small on purpose. Every existing template is plain text, and a mark
that ordinary text could trigger by accident would change mails nobody edited.
That is why there is no `*italic*` and no `_underline_`: both appear in
addresses and file names.
"""
import html
import re

_URL = re.compile(r"https?://[^\s<]+")
_LINK = re.compile(r"\[([^\[\]\n]+)\]\(((?:https?://|mailto:)[^\s()]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_BULLET = re.compile(r"^[-*] ")
_NUMBER = re.compile(r"^\d+\. ")

_P = "margin:0 0 16px;font-size:15px;color:#cbd5e1;line-height:1.7;"
_H2 = "margin:8px 0 12px;font-size:18px;font-weight:600;color:#f1f5f9;line-height:1.4;"
_H3 = "margin:8px 0 10px;font-size:16px;font-weight:600;color:#f1f5f9;line-height:1.4;"
_LIST = "margin:0 0 16px;padding-left:22px;font-size:15px;color:#cbd5e1;line-height:1.7;"
_A = "color:#818cf8;text-decoration:none;"


def _inline(text: str) -> str:
    """Escape, then turn links, bare addresses and bold into markup. Links go
    first and are parked, so a bare-address pass cannot link them twice."""
    parked: list[str] = []

    def park(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        parked.append(f'<a href="{html.escape(url, quote=True)}" style="{_A}">{html.escape(label)}</a>')
        return f"\x00{len(parked) - 1}\x00"

    text = _LINK.sub(park, text)
    text = html.escape(text)
    text = _URL.sub(lambda m: f'<a href="{m.group(0)}" style="{_A}">{m.group(0)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: parked[int(m.group(1))], text)


def _list_items(lines: list[str], marker: re.Pattern) -> str:
    return "".join(f"<li>{_inline(marker.sub('', line, count=1))}</li>" for line in lines)


def to_html(body: str) -> str:
    blocks = []
    for block in body.strip().split("\n\n"):
        lines = [line.rstrip() for line in block.strip().split("\n") if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and lines[0].startswith("### "):
            blocks.append(f'<h3 style="{_H3}">{_inline(lines[0][4:])}</h3>')
        elif len(lines) == 1 and lines[0].startswith("## "):
            blocks.append(f'<h2 style="{_H2}">{_inline(lines[0][3:])}</h2>')
        elif all(_BULLET.match(line) for line in lines):
            blocks.append(f'<ul style="{_LIST}">{_list_items(lines, _BULLET)}</ul>')
        elif all(_NUMBER.match(line) for line in lines):
            blocks.append(f'<ol style="{_LIST}">{_list_items(lines, _NUMBER)}</ol>')
        else:
            blocks.append(f'<p style="{_P}">{"<br />".join(_inline(line) for line in lines)}</p>')
    return "".join(blocks)


def to_text(body: str) -> str:
    text = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2).removeprefix('mailto:')})", body)
    text = _BOLD.sub(r"\1", text)
    return re.sub(r"^#{2,3} ", "", text, flags=re.MULTILINE)

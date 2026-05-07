"""
utils/display_utils.py — Display formatting helpers.
"""
from __future__ import annotations
from typing import List


def truncate(text: str, max_len: int = 80, suffix: str = "…") -> str:
    return text if len(text) <= max_len else text[:max_len - len(suffix)] + suffix


def table(rows: List[List[str]], headers: List[str] = None) -> str:
    """Build a plain-text table from rows."""
    all_rows = ([headers] + rows) if headers else rows
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(len(all_rows[0]))]
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"

    lines = [sep]
    for ri, row in enumerate(all_rows):
        line = "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)) + " |"
        lines.append(line)
        if ri == 0 and headers:
            lines.append(sep)
    lines.append(sep)
    return "\n".join(lines)


def bullet_list(items: List[str], prefix: str = "  • ") -> str:
    return "\n".join(f"{prefix}{item}" for item in items)

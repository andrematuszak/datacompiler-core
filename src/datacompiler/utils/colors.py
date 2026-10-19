"""Normalize editable colors to the PDF renderer's opaque RGB hex format."""

import re


def normalize_hex_color(value: str) -> str:
    """Validate a CSS-style #RGB or #RRGGBB value and return #RRGGBB."""
    if not isinstance(value, str):
        raise ValueError("Color must be a #RGB or #RRGGBB string")
    match = re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value.strip())
    if not match:
        raise ValueError(f"Invalid color {value!r}; expected #RGB or #RRGGBB")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return f"#{digits.upper()}"

from __future__ import annotations

import re


GD_T_SYMBOLS = {
    "⊥": "垂直度",
    "∥": "平行度",
    "⌒": "轮廓度",
    "⌖": "位置度",
    "◎": "同轴度",
    "○": "圆度",
    "⌭": "圆柱度",
    "⌯": "跳动",
    "⌰": "全跳动",
    "⌔": "线轮廓度",
}

ROUGHNESS_SYMBOLS = {
    "▽",
    "△",
    "∇",
    "⌵",
    "⌓",
    "⏊",
}


def normalize_engineering_text(value: object, *, ascii_only: bool = False) -> str:
    """Normalize drawing text for bubble rendering and CSV readability.

    The default keeps common engineering symbols that normal fonts support
    (Phi, plus-minus, degree, multiply), but removes symbols that often render
    as tofu boxes in generated bubble diagrams.
    """
    text = str(value or "")
    if not text:
        return ""

    roughness_tofu_pattern = re.compile(r"R[□�\ufffd]\s*", re.IGNORECASE)
    text = roughness_tofu_pattern.sub("Ra", text)

    replacements = {
        "\ufffd": "",
        "□": "",
        "�": "",
        "Ø": "Phi" if ascii_only else "Φ",
        "∅": "Phi" if ascii_only else "Φ",
        "⌀": "Phi" if ascii_only else "Φ",
        "φ": "Phi" if ascii_only else "Φ",
        "×": "x" if ascii_only else "×",
        "✕": "x" if ascii_only else "×",
        "✖": "x" if ascii_only else "×",
        "±": "+/-" if ascii_only else "±",
        "°": "deg" if ascii_only else "°",
        "℃": "degC" if ascii_only else "°C",
        "μ": "u" if ascii_only else "μ",
        "µ": "u" if ascii_only else "μ",
        "·": "." if ascii_only else "·",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)

    for symbol in ROUGHNESS_SYMBOLS:
        text = text.replace(symbol, "")
    for symbol, label in GD_T_SYMBOLS.items():
        text = text.replace(symbol, label)

    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"R\s*a", "Ra", text, flags=re.IGNORECASE)
    return text

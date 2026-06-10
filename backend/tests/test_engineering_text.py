from app.services.engineering_text import normalize_engineering_text


def test_normalize_engineering_text_for_bubble_display() -> None:
    assert normalize_engineering_text("▽ Ra1.6") == "Ra1.6"
    assert normalize_engineering_text("Ø45 ±0.01 90°") == "Φ45 ±0.01 90°"
    assert normalize_engineering_text("⊥0.01 A-B") == "垂直度0.01 A-B"
    assert normalize_engineering_text("R□1.6") == "Ra1.6"


def test_normalize_engineering_text_ascii_mode() -> None:
    assert normalize_engineering_text("Ø45 ±0.01 90° ×2", ascii_only=True) == "Phi45 +/-0.01 90deg x2"

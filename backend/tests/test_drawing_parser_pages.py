from pathlib import Path

from app.services.drawing_parser import DrawingParser


def test_extract_pdf_page_images_returns_empty_for_missing_file():
    parser = DrawingParser()
    assert parser.extract_pdf_page_images(Path("/tmp/not-exists-cutr.pdf")) == []
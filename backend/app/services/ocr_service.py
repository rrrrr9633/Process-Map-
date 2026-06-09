from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings


_AI_OCR_PROVIDERS = {"ai", "deepseek", "openai", "openai_compatible"}


class OCRService:
    """OCR文字识别服务"""

    def __init__(self):
        self.provider = settings.ocr_provider
        self.enabled = self.provider != "none"

    def _ocr_image_with_pytesseract(self, image_path: Path) -> str:
        try:
            import pytesseract
            from PIL import Image
        except Exception:
            return ""

        try:
            with Image.open(image_path) as image:
                text = pytesseract.image_to_string(image, lang="chi_sim+eng")
                return text.strip()
        except Exception:
            return ""

    def _render_pdf_page_text(self, pdf_path: Path, max_pages: int = 6) -> str:
        try:
            import fitz
            from PIL import Image
        except Exception:
            return ""

        texts: list[str] = []
        document = fitz.open(str(pdf_path))
        try:
            matrix = fitz.Matrix(1.5, 1.5)
            for page_index in range(min(len(document), max_pages)):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                try:
                    import pytesseract
                except Exception:
                    return ""
                try:
                    text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
                except Exception:
                    text = ""
                if text:
                    texts.append(text)
                if sum(len(item) for item in texts) >= 300:
                    break
        finally:
            document.close()
        return "\n".join(texts).strip()

    def _ocr_with_ai(self, image_path: Path) -> str:
        from app.services.ai_service import ai_service

        if self.provider in _AI_OCR_PROVIDERS:
            text = ai_service.ocr_image_text(image_path)
            if text.strip():
                return text.strip()
        return ""

    def extract_text_from_image(self, image_path: Path) -> str:
        """
        从图片中提取文字。
        """
        if self.provider in _AI_OCR_PROVIDERS:
            ai_text = self._ocr_with_ai(image_path)
            if ai_text:
                return ai_text
        if self.provider == "none":
            return self._ocr_image_with_pytesseract(image_path)
        return self._ocr_image_with_pytesseract(image_path)


    def extract_pdf_page_texts(self, pdf_path: Path, max_pages: int = 20) -> dict[int, str]:
        """按页提取 PDF 文本，文本层不足时对该页做 OCR。"""
        from pypdf import PdfReader

        page_texts: dict[int, str] = {}
        try:
            reader = PdfReader(str(pdf_path), strict=False)
            for page_index, page in enumerate(reader.pages[:max_pages], start=1):
                page_texts[page_index] = (page.extract_text() or "").strip()
        except Exception:
            page_texts = {}

        try:
            import fitz
            from PIL import Image
        except Exception:
            return page_texts

        document = fitz.open(str(pdf_path))
        try:
            total = min(len(document), max_pages)
            matrix = fitz.Matrix(1.5, 1.5)
            for page_index in range(total):
                page_no = page_index + 1
                if len(page_texts.get(page_no, "")) >= 40:
                    continue
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                try:
                    import pytesseract
                    ocr_text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
                except Exception:
                    ocr_text = ""
                if ocr_text:
                    existing = page_texts.get(page_no, "")
                    page_texts[page_no] = f"{existing}\n{ocr_text}".strip() if existing else ocr_text
        finally:
            document.close()
        return page_texts

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """
        从PDF中提取文字（结合文本提取和OCR）。
        """
        from pypdf import PdfReader

        try:
            reader = PdfReader(str(pdf_path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            text = ""

        if len(text.strip()) >= 100:
            return text

        ocr_text = self._render_pdf_page_text(pdf_path)
        if ocr_text:
            if text.strip():
                return f"{text.strip()}\n\n{ocr_text}"
            return ocr_text
        return text


class VisionService:
    """多模态视觉识别服务"""
    
    def __init__(self):
        self.provider = settings.vision_provider
        self.enabled = self.provider != "none"
    
    async def analyze_drawing(self, image_path: Path, prompt: Optional[str] = None) -> dict:
        """
        使用视觉模型分析图纸
        
        Args:
            image_path: 图纸图片路径
            prompt: 分析提示词
        
        Returns:
            分析结果
        """
        from app.services.ai_service import ai_service

        default_prompt = prompt or (
            "请分析这张曲轴工程图纸，提取零件名称、材料、关键加工特征、尺寸公差、技术要求，"
            "以 JSON 返回：part_name, material, features[], dimensions[], technical_notes[]"
        )
        providers = {"ai", "deepseek", "openai", "openai_compatible", "qwen"}
        if self.provider in providers and ai_service.enabled:
            raw = ai_service.ocr_image_text(image_path, prompt=default_prompt + "\n只返回 JSON。")
            if raw.strip():
                try:
                    import json
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return {"raw_analysis": raw.strip()}
        return {}
    
    async def identify_features(self, image_path: Path) -> list[dict]:
        """
        识别图纸中的加工特征
        
        Args:
            image_path: 图纸图片路径
        
        Returns:
            特征列表
        """
        if not self.enabled:
            return []
        
        # TODO: 调用视觉模型识别加工特征
        return []


# 全局实例
ocr_service = OCRService()
vision_service = VisionService()

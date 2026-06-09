from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings


class OCRService:
    """OCR文字识别服务"""
    
    def __init__(self):
        self.provider = settings.ocr_provider
        self.enabled = self.provider != "none"
    
    async def extract_text_from_image(self, image_path: Path) -> str:
        """
        从图片中提取文字
        
        Args:
            image_path: 图片路径
        
        Returns:
            识别出的文本
        """
        if not self.enabled:
            return ""
        
        # TODO: 根据provider调用对应的OCR服务
        # - baidu: 百度OCR
        # - aliyun: 阿里云OCR
        # - tencent: 腾讯云OCR
        # - custom: 自定义OCR服务
        
        return ""
    
    async def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """
        从PDF中提取文字（结合OCR和文本提取）
        
        Args:
            pdf_path: PDF文件路径
        
        Returns:
            提取的文本
        """
        # 先尝试直接提取文本
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        
        # 如果文本很少，说明可能是扫描件，需要OCR
        if len(text.strip()) < 100 and self.enabled:
            # TODO: 将PDF转图片后进行OCR
            pass
        
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
        if not self.enabled:
            return {}
        
        default_prompt = """
        请分析这张曲轴工程图纸，提取以下信息：
        1. 零件名称和图号
        2. 材料和热处理要求
        3. 关键加工特征（主轴颈、连杆颈、法兰等）
        4. 尺寸和公差要求
        5. 技术要求（滚压、探伤、动平衡等）
        6. 表面处理要求
        
        请以结构化JSON格式返回。
        """
        
        # TODO: 根据provider调用对应的视觉识别API
        # - openai: GPT-4 Vision
        # - qwen: 通义千问-VL
        # - custom: 自定义视觉服务
        
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

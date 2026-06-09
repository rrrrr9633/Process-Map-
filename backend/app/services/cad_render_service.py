from __future__ import annotations

import base64
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models.drawing_explanation import DrawingPageAsset
from app.services.drawing_parser import DrawingParser


class CadRenderService:
    def __init__(self) -> None:
        self._parser = DrawingParser()

    def render_pages(
        self,
        source_path: str | Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
        *,
        max_pages: int = 1,
    ) -> list[tuple[DrawingPageAsset, dict[str, str]]]:
        path = Path(source_path)
        suffix = path.suffix.lower()
        if suffix == ".dxf":
            return self._render_dxf(path, target_dir, file_index, file_name, max_pages=max_pages)
        if suffix == ".dwg":
            return self._render_dwg(path, target_dir, file_index, file_name, max_pages=max_pages)
        return []

    def _render_dxf(
        self,
        path: Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
        *,
        max_pages: int,
    ) -> list[tuple[DrawingPageAsset, dict[str, str]]]:
        rendered = self._render_dxf_with_ezdxf(path, target_dir, file_index, file_name)
        if rendered:
            return rendered[:max_pages]
        return self._render_text_preview(path, target_dir, file_index, file_name, page=1, title="DXF 文本预览")

    def _render_dwg(
        self,
        path: Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
        *,
        max_pages: int,
    ) -> list[tuple[DrawingPageAsset, dict[str, str]]]:
        rendered = self._render_dwg_with_odafc(path, target_dir, file_index, file_name)
        if rendered:
            return rendered[:max_pages]
        return self._render_text_preview(
            path,
            target_dir,
            file_index,
            file_name,
            page=1,
            title="DWG 预览（需安装 ODA File Converter 才能渲染几何）",
        )

    def _render_dxf_with_ezdxf(
        self,
        path: Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
    ) -> list[tuple[DrawingPageAsset, dict[str, str]]]:
        try:
            import ezdxf
            from ezdxf.addons.drawing import Frontend, RenderContext
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
            import matplotlib.pyplot as plt
        except Exception:
            return []

        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        image_path = target / f"file_{file_index:03d}_page_1.png"
        try:
            document = ezdxf.readfile(str(path))
            figure = plt.figure(figsize=(12, 8), dpi=150)
            axis = figure.add_axes([0, 0, 1, 1])
            axis.set_axis_off()
            context = RenderContext(document)
            backend = MatplotlibBackend(axis)
            Frontend(context, backend).draw_layout(document.modelspace(), finalize=True)
            figure.savefig(image_path, dpi=150, bbox_inches="tight", pad_inches=0.05)
            plt.close(figure)
        except Exception:
            try:
                plt.close("all")
            except Exception:
                pass
            return []

        return [self._asset_from_image(image_path, target, file_index, file_name, page=1)]

    def _render_dwg_with_odafc(
        self,
        path: Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
    ) -> list[tuple[DrawingPageAsset, dict[str, str]]]:
        try:
            from ezdxf.addons import odafc
        except Exception:
            return []
        if not odafc.is_installed():
            return []
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        image_path = target / f"file_{file_index:03d}_page_1.png"
        try:
            import ezdxf
            from ezdxf.addons.drawing import Frontend, RenderContext
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
            import matplotlib.pyplot as plt

            document = odafc.readfile(str(path))
            figure = plt.figure(figsize=(12, 8), dpi=150)
            axis = figure.add_axes([0, 0, 1, 1])
            axis.set_axis_off()
            context = RenderContext(document)
            backend = MatplotlibBackend(axis)
            Frontend(context, backend).draw_layout(document.modelspace(), finalize=True)
            figure.savefig(image_path, dpi=150, bbox_inches="tight", pad_inches=0.05)
            plt.close(figure)
        except Exception:
            try:
                plt.close("all")
            except Exception:
                pass
            return []
        return [self._asset_from_image(image_path, target, file_index, file_name, page=1)]

    def _render_text_preview(
        self,
        path: Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
        *,
        page: int,
        title: str,
    ) -> list[tuple[DrawingPageAsset, dict[str, str]]]:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        image_path = target / f"file_{file_index:03d}_page_{page}.png"
        text = self._parser._extract_dxf_text(path) if path.suffix.lower() == ".dxf" else ""
        if not text.strip():
            text = f"{path.name}\n\n当前无法渲染 CAD 几何，请安装 ezdxf + matplotlib（DXF）或 ODA File Converter（DWG）。"
        image = Image.new("RGB", (1400, 980), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        draw.text((24, 24), title, fill=(0, 0, 0), font=font)
        y = 56
        for line in textwrap.wrap(text, width=90):
            draw.text((24, y), line, fill=(30, 30, 30), font=font)
            y += 16
            if y > 940:
                break
        image.save(image_path)
        return [self._asset_from_image(image_path, target, file_index, file_name, page=page)]

    def _asset_from_image(
        self,
        image_path: Path,
        target_dir: Path,
        file_index: int,
        file_name: str,
        *,
        page: int,
    ) -> tuple[DrawingPageAsset, dict[str, str]]:
        with Image.open(image_path) as image:
            width, height = image.size
        payload = {
            "name": image_path.name,
            "page": str(page),
            "mime_type": "image/png",
            "base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "source": "cad_render",
        }
        asset = DrawingPageAsset(
            file_index=file_index,
            file_name=file_name,
            page=page,
            image_path=str(image_path),
            image_url=f"pages/{image_path.name}",
            width=width,
            height=height,
        )
        return asset, payload


cad_render_service = CadRenderService()
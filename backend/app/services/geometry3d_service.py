from __future__ import annotations

import base64
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.models.drawing import ConfidenceLevel, DrawingFeature, DrawingParseResult, FeatureType, RiskFlag
from app.models.drawing_explanation import DrawingPageAsset


SUPPORTED_MESH_SUFFIXES = {".stl", ".obj", ".ply"}
CAD_KERNEL_SUFFIXES = {".step", ".stp", ".iges", ".igs"}
SUPPORTED_3D_SUFFIXES = SUPPORTED_MESH_SUFFIXES | CAD_KERNEL_SUFFIXES


@dataclass
class Geometry3DAnalysis:
    file_name: str
    suffix: str
    status: str
    summary: str
    vertices: np.ndarray
    faces: list[tuple[int, int, int]]
    dimensions: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bbox_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bbox_max: tuple[float, float, float] = (0.0, 0.0, 0.0)
    dominant_axis: str = "待确认"
    risk_notes: list[str] | None = None


class Geometry3DService:
    def is_supported_3d(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_3D_SUFFIXES

    def analyze_file(self, path: str | Path) -> Geometry3DAnalysis:
        source = Path(path)
        suffix = source.suffix.lower()
        if suffix in CAD_KERNEL_SUFFIXES:
            return Geometry3DAnalysis(
                file_name=source.name,
                suffix=suffix,
                status="needs_cad_kernel",
                summary=(
                    f"{source.name} 是 STEP/IGES 精确 CAD 模型。当前轻量内核无法直接读取 B-Rep 面、孔、圆角和基准；"
                    "需要安装 CadQuery/OCP/pythonOCC 后才能做完整特征识别。"
                ),
                vertices=np.empty((0, 3)),
                faces=[],
                risk_notes=["STEP/IGES 已接收，但尚未启用 B-Rep CAD 内核；当前不能直接提取精确孔径、圆角和公差。"],
            )
        try:
            if suffix == ".stl":
                vertices, faces = self._load_stl(source)
            elif suffix == ".obj":
                vertices, faces = self._load_obj(source)
            elif suffix == ".ply":
                vertices, faces = self._load_ply(source)
            else:
                vertices, faces = np.empty((0, 3)), []
        except Exception as exc:
            return Geometry3DAnalysis(
                file_name=source.name,
                suffix=suffix,
                status="failed",
                summary=f"{source.name} 三维模型解析失败：{type(exc).__name__}: {exc}",
                vertices=np.empty((0, 3)),
                faces=[],
                risk_notes=["3D 文件无法解析，请确认模型格式或重新导出 STL/OBJ/PLY。"],
            )

        if vertices.size == 0:
            return Geometry3DAnalysis(
                file_name=source.name,
                suffix=suffix,
                status="empty",
                summary=f"{source.name} 未读取到有效三维顶点。",
                vertices=vertices,
                faces=faces,
                risk_notes=["模型没有有效几何数据，不能用于工序生成。"],
            )

        bbox_min_arr = vertices.min(axis=0)
        bbox_max_arr = vertices.max(axis=0)
        dims_arr = bbox_max_arr - bbox_min_arr
        axis_index = int(np.argmax(dims_arr))
        axis_name = ("X", "Y", "Z")[axis_index]
        ratio = float(dims_arr[axis_index] / max(1e-9, np.partition(dims_arr, 1)[1]))
        shape_hint = "长轴类零件" if ratio >= 2.2 else "块状/盘类零件"
        summary = (
            f"{source.name} 已解析为{shape_hint}：包围盒约 "
            f"X={dims_arr[0]:.2f}, Y={dims_arr[1]:.2f}, Z={dims_arr[2]:.2f}；"
            f"主延伸方向为 {axis_name} 轴；顶点 {len(vertices)} 个，三角面 {len(faces)} 个。"
        )
        risks = ["网格模型只含几何外形，不含尺寸公差、材料、粗糙度和工艺要求；需与 PDF/DWG 图纸标注融合。"]
        if not faces:
            risks.append("模型缺少面片数据，只能做点云级包围盒分析。")
        return Geometry3DAnalysis(
            file_name=source.name,
            suffix=suffix,
            status="ok",
            summary=summary,
            vertices=vertices,
            faces=faces,
            dimensions=tuple(float(item) for item in dims_arr),
            bbox_min=tuple(float(item) for item in bbox_min_arr),
            bbox_max=tuple(float(item) for item in bbox_max_arr),
            dominant_axis=axis_name,
            risk_notes=risks,
        )

    def parse_to_drawing_result(self, path: str | Path) -> DrawingParseResult:
        analysis = self.analyze_file(path)
        features: list[DrawingFeature] = []
        risks = [
            RiskFlag(field="geometry_3d", message=note, severity="warning")
            for note in (analysis.risk_notes or [])
        ]
        if analysis.status == "ok":
            dims = analysis.dimensions
            long_ratio = max(dims) / max(1e-9, sorted(dims)[1])
            if long_ratio >= 2.2:
                features.append(
                    DrawingFeature(
                        type=FeatureType.SHAFT,
                        name="三维长轴主体",
                        description="由 3D 网格包围盒识别出的长轴类主体，可作为车削/磨削/装夹流程依据。",
                        location=f"{analysis.dominant_axis} 轴方向",
                        source_text=analysis.summary,
                        confidence=ConfidenceLevel.MEDIUM,
                    )
                )
            else:
                features.append(
                    DrawingFeature(
                        type=FeatureType.GENERAL_FEATURE,
                        name="三维主体外形",
                        description="由 3D 网格包围盒识别出的主体外形，需要结合图纸标注细化孔、槽、面和基准。",
                        source_text=analysis.summary,
                        confidence=ConfidenceLevel.MEDIUM,
                    )
                )
        severity = "critical" if analysis.status in {"failed", "empty"} else "warning"
        if analysis.status != "ok":
            risks.append(RiskFlag(field="geometry_3d", message=analysis.summary, severity=severity))
        return DrawingParseResult(features=features, risk_flags=risks, raw_text=self.to_prompt_text(analysis))

    def render_pages(
        self,
        path: str | Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
    ) -> list[tuple[DrawingPageAsset, dict[str, str], str]]:
        analysis = self.analyze_file(path)
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        image_path = target / f"file_{file_index:03d}_page_1.png"
        self._render_preview(analysis, image_path)
        asset = DrawingPageAsset(
            file_index=file_index,
            file_name=file_name,
            page=1,
            image_path=str(image_path),
            image_url=f"pages/{image_path.name}",
            width=0,
            height=0,
        )
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                asset.width, asset.height = image.size
        except Exception:
            pass
        payload = {
            "name": image_path.name,
            "page": "1",
            "mime_type": "image/png",
            "base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "source": "geometry_3d_preview",
        }
        return [(asset, payload, self.to_prompt_text(analysis))]

    def render_payloads(self, path: str | Path, target_dir: str | Path, file_index: int) -> list[dict[str, str]]:
        pages = self.render_pages(path, target_dir, file_index, Path(path).name)
        return [payload for _, payload, _ in pages]

    def to_prompt_text(self, analysis: Geometry3DAnalysis) -> str:
        lines = [
            "三维几何分析结果",
            f"文件：{analysis.file_name}",
            f"状态：{analysis.status}",
            f"摘要：{analysis.summary}",
        ]
        if analysis.status == "ok":
            lines.extend(
                [
                    f"包围盒最小点：{analysis.bbox_min}",
                    f"包围盒最大点：{analysis.bbox_max}",
                    f"尺寸估计：X={analysis.dimensions[0]:.3f}, Y={analysis.dimensions[1]:.3f}, Z={analysis.dimensions[2]:.3f}",
                    f"主轴方向：{analysis.dominant_axis}",
                ]
            )
        if analysis.risk_notes:
            lines.append("限制与复核：" + "；".join(analysis.risk_notes))
        return "\n".join(lines)

    def _load_stl(self, path: Path) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
        data = path.read_bytes()
        if len(data) >= 84:
            face_count = struct.unpack("<I", data[80:84])[0]
            expected = 84 + face_count * 50
            if expected == len(data):
                vertices: list[tuple[float, float, float]] = []
                faces: list[tuple[int, int, int]] = []
                offset = 84
                for _ in range(face_count):
                    tri = struct.unpack("<12fH", data[offset : offset + 50])
                    base = len(vertices)
                    vertices.extend([(tri[3], tri[4], tri[5]), (tri[6], tri[7], tri[8]), (tri[9], tri[10], tri[11])])
                    faces.append((base, base + 1, base + 2))
                    offset += 50
                return np.array(vertices, dtype=float), faces
        text = data.decode("utf-8", errors="ignore")
        vertices = []
        faces = []
        current = []
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) == 4 and parts[0].lower() == "vertex":
                current.append((float(parts[1]), float(parts[2]), float(parts[3])))
                if len(current) == 3:
                    base = len(vertices)
                    vertices.extend(current)
                    faces.append((base, base + 1, base + 2))
                    current = []
        return np.array(vertices, dtype=float), faces

    def _load_obj(self, path: Path) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
        vertices: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int]] = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == "v" and len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif parts[0] == "f" and len(parts) >= 4:
                indexes = [int(item.split("/")[0]) - 1 for item in parts[1:]]
                for i in range(1, len(indexes) - 1):
                    faces.append((indexes[0], indexes[i], indexes[i + 1]))
        return np.array(vertices, dtype=float), faces

    def _load_ply(self, path: Path) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        vertex_count = 0
        face_count = 0
        header_end = 0
        for index, line in enumerate(lines):
            parts = line.strip().split()
            if len(parts) == 3 and parts[:2] == ["element", "vertex"]:
                vertex_count = int(parts[2])
            elif len(parts) == 3 and parts[:2] == ["element", "face"]:
                face_count = int(parts[2])
            elif line.strip() == "end_header":
                header_end = index + 1
                break
        vertices = []
        for line in lines[header_end : header_end + vertex_count]:
            parts = line.strip().split()
            if len(parts) >= 3:
                vertices.append((float(parts[0]), float(parts[1]), float(parts[2])))
        faces = []
        for line in lines[header_end + vertex_count : header_end + vertex_count + face_count]:
            parts = line.strip().split()
            if len(parts) >= 4:
                indexes = [int(item) for item in parts[1:]]
                for i in range(1, len(indexes) - 1):
                    faces.append((indexes[0], indexes[i], indexes[i + 1]))
        return np.array(vertices, dtype=float), faces

    def _render_preview(self, analysis: Geometry3DAnalysis, image_path: Path) -> None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=(12, 8), dpi=150)
        ax = fig.add_subplot(111, projection="3d")
        ax.set_title(analysis.summary[:120])
        if analysis.vertices.size:
            vertices = analysis.vertices
            sample_step = max(1, math.ceil(len(vertices) / 4000))
            sample = vertices[::sample_step]
            ax.scatter(sample[:, 0], sample[:, 1], sample[:, 2], s=1, c="#111111", alpha=0.55)
            mins = np.array(analysis.bbox_min)
            maxs = np.array(analysis.bbox_max)
            self._draw_bbox(ax, mins, maxs)
            center = (mins + maxs) / 2
            radius = max(maxs - mins) / 2 or 1
            ax.set_xlim(center[0] - radius, center[0] + radius)
            ax.set_ylim(center[1] - radius, center[1] + radius)
            ax.set_zlim(center[2] - radius, center[2] + radius)
        else:
            ax.text2D(0.05, 0.5, analysis.summary, transform=ax.transAxes)
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        fig.tight_layout()
        fig.savefig(image_path)
        plt.close(fig)

    def _draw_bbox(self, ax: Any, mins: np.ndarray, maxs: np.ndarray) -> None:
        corners = np.array(
            [
                [mins[0], mins[1], mins[2]],
                [maxs[0], mins[1], mins[2]],
                [maxs[0], maxs[1], mins[2]],
                [mins[0], maxs[1], mins[2]],
                [mins[0], mins[1], maxs[2]],
                [maxs[0], mins[1], maxs[2]],
                [maxs[0], maxs[1], maxs[2]],
                [mins[0], maxs[1], maxs[2]],
            ]
        )
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        for start, end in edges:
            ax.plot(*zip(corners[start], corners[end]), color="#d62728", linewidth=1.2)


geometry3d_service = Geometry3DService()

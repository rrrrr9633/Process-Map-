from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import uuid4

from app.models.drawing_explanation import DrawingExplanation
from app.models.flow import ProcessFlow
from app.models.process import ProcessPlan


class ExportService:
    def to_markdown(self, plan: ProcessPlan, flow: ProcessFlow) -> str:
        lines = [f"# {plan.title}", "", "## 工序明细", ""]
        for operation in plan.operations:
            lines.extend(
                [
                    f"### {operation.operation_no} {operation.operation_name}",
                    "",
                    f"- 加工对象：{'、'.join(operation.targets) or '待确认'}",
                    f"- 操作内容：{operation.content}",
                    f"- 关键管控点：{'；'.join(operation.control_points) or '无'}",
                    f"- 检测项目：{'、'.join(operation.inspection_items) or '无'}",
                    f"- 图纸依据：{'；'.join(operation.drawing_basis) or '待确认'}",
                    f"- 是否强制节点：{'是' if operation.mandatory else '否'}",
                    f"- 是否需人工确认：{'是' if operation.requires_manual_review else '否'}",
                    "",
                ]
            )

        lines.extend(["## 流程图", "", "```mermaid", flow.mermaid, "```", ""])
        if plan.validation_issues:
            lines.extend(["## 校验提示", ""])
            for issue in plan.validation_issues:
                lines.append(f"- [{issue.severity}] {issue.message}")
            lines.append("")
        return "\n".join(lines)

    def archive_markdown(self, plan: ProcessPlan, flow: ProcessFlow, archive_dir: str | Path = "archives") -> Path:
        target_dir = Path(archive_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"process_plan_{uuid4().hex}.md"
        file_path.write_text(self.to_markdown(plan, flow), encoding="utf-8")
        return file_path

    def export_annotations(self, explanations: list[DrawingExplanation], export_dir: str | Path) -> tuple[Path, Path]:
        target_dir = Path(export_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        csv_path = target_dir / "annotations.csv"
        json_path = target_dir / "annotations.json"
        rows: list[dict] = []
        for explanation in explanations:
            page_sources = explanation.page_explanations or []
            if page_sources:
                for page_explanation in page_sources:
                    for row in page_explanation.annotation_result.export_rows:
                        rows.append(
                            {
                                "file_index": explanation.file_index,
                                "file_name": explanation.file_name,
                                "page": page_explanation.page,
                                "row_no": row.row_no,
                                "annotation_id": row.annotation_id,
                                "parameter_name": row.parameter_name,
                                "parameter_value": row.parameter_value,
                                "upper_limit": row.upper_limit,
                                "lower_limit": row.lower_limit,
                                "unit": row.unit,
                                "semantic_type": row.semantic_type,
                                "review_status": row.review_status,
                                "source": row.source,
                                "confidence": row.confidence,
                            }
                        )
                continue
            for row in explanation.annotation_result.export_rows:
                rows.append(
                    {
                        "file_index": explanation.file_index,
                        "file_name": explanation.file_name,
                        "row_no": row.row_no,
                        "annotation_id": row.annotation_id,
                        "parameter_name": row.parameter_name,
                        "parameter_value": row.parameter_value,
                        "upper_limit": row.upper_limit,
                        "lower_limit": row.lower_limit,
                        "unit": row.unit,
                        "semantic_type": row.semantic_type,
                        "review_status": row.review_status,
                        "source": row.source,
                        "confidence": row.confidence,
                    }
                )
        fieldnames = [
            "file_index",
            "file_name",
            "page",
            "row_no",
            "annotation_id",
            "parameter_name",
            "parameter_value",
            "upper_limit",
            "lower_limit",
            "unit",
            "semantic_type",
            "review_status",
            "source",
            "confidence",
        ]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return csv_path, json_path
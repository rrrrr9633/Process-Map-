from __future__ import annotations

from pathlib import Path
from uuid import uuid4

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
from __future__ import annotations

from app.models.flow import FlowEdge, FlowNode, FlowNodeType, ProcessFlow
from app.models.process import Operation, OperationType, ProcessPlan


FLOW_TYPE_MAP = {
    OperationType.BLANK_PREPARATION: FlowNodeType.MACHINING,
    OperationType.BASELINE_PROCESSING: FlowNodeType.MACHINING,
    OperationType.ROUGH_MACHINING: FlowNodeType.MACHINING,
    OperationType.SEMI_FINISHING: FlowNodeType.MACHINING,
    OperationType.HOLE_PROCESSING: FlowNodeType.MACHINING,
    OperationType.FINISHING: FlowNodeType.PRECISION_MACHINING,
    OperationType.INSPECTION: FlowNodeType.INSPECTION,
    OperationType.SPECIAL_PROCESS: FlowNodeType.SPECIAL_PROCESS,
    OperationType.CLEANING_FINAL_INSPECTION: FlowNodeType.CLEANING_FINAL_INSPECTION,
}


class FlowBuilder:
    def build(self, plan: ProcessPlan) -> ProcessFlow:
        nodes = [self._to_node(operation) for operation in plan.operations]
        edges = [
            FlowEdge(source=nodes[index].id, target=nodes[index + 1].id)
            for index in range(len(nodes) - 1)
        ]
        if plan.requires_manual_review:
            review_node = FlowNode(
                id="manual_review",
                label="人工微调确认",
                type=FlowNodeType.MANUAL_REVIEW,
                control_points=["确认识别风险、企业习惯差异和特殊技术要求"],
            )
            if nodes:
                edges.append(FlowEdge(source=nodes[-1].id, target=review_node.id, label="需确认"))
            nodes.append(review_node)
        return ProcessFlow(title=f"{plan.title}流程图", nodes=nodes, edges=edges, mermaid=self._to_mermaid(nodes, edges))

    def build_with_edges(self, plan: ProcessPlan, edges: list[FlowEdge]) -> ProcessFlow:
        nodes = [self._to_node(operation) for operation in plan.operations]
        valid_node_ids = {node.id for node in nodes}
        safe_edges = [edge for edge in edges if edge.source in valid_node_ids and edge.target in valid_node_ids]
        if not safe_edges:
            return self.build(plan)
        if plan.requires_manual_review:
            review_node = FlowNode(
                id="manual_review",
                label="人工微调确认",
                type=FlowNodeType.MANUAL_REVIEW,
                control_points=["确认识别风险、企业习惯差异和特殊技术要求"],
            )
            if nodes:
                safe_edges.append(FlowEdge(source=nodes[-1].id, target=review_node.id, label="需确认"))
            nodes.append(review_node)
        return ProcessFlow(title=f"{plan.title}流程图", nodes=nodes, edges=safe_edges, mermaid=self._to_mermaid(nodes, safe_edges))

    def _to_node(self, operation: Operation) -> FlowNode:
        return FlowNode(
            id=f"op_{operation.operation_no}",
            label=f"{operation.operation_no} {operation.operation_name}",
            type=FLOW_TYPE_MAP[operation.operation_type],
            operation_no=operation.operation_no,
            control_points=operation.control_points,
        )

    def _to_mermaid(self, nodes: list[FlowNode], edges: list[FlowEdge]) -> str:
        lines = ["flowchart LR"]
        for node in nodes:
            safe_label = node.label.replace('"', "'")
            lines.append(f'  {node.id}["{safe_label}"]')
        for edge in edges:
            if edge.label:
                lines.append(f"  {edge.source} -->|{edge.label}| {edge.target}")
            else:
                lines.append(f"  {edge.source} --> {edge.target}")
        return "\n".join(lines)
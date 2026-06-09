from app.models.drawing import DrawingParseResult, TechnicalRequirement, RequirementType
from app.models.process import ProcessMode
from app.services.flow_builder import FlowBuilder
from app.services.process_generator import ProcessGenerator


def test_generate_standard_8_with_special_requirements():
    parse_result = DrawingParseResult(
        technical_requirements=[
            TechnicalRequirement(type=RequirementType.ROLLING, content="轴颈需滚压"),
            TechnicalRequirement(type=RequirementType.DYNAMIC_BALANCING, content="需做动平衡"),
            TechnicalRequirement(type=RequirementType.CLEANLINESS, content="油道清洁度要求"),
        ]
    )

    plan = ProcessGenerator().generate(parse_result, ProcessMode.STANDARD_8)
    flow = FlowBuilder().build(plan)

    assert len(plan.operations) == 8
    assert "滚压" in "\n".join(plan.operations[5].control_points)
    assert "动平衡" in "\n".join(plan.operations[6].control_points)
    assert "清洁" in "\n".join(plan.operations[7].control_points)
    assert "flowchart LR" in flow.mermaid
from __future__ import annotations

from dataclasses import dataclass

from app.models.drawing import RequirementType
from app.models.process import Operation, OperationType, ProcessMode


@dataclass(frozen=True)
class OperationTemplate:
    operation_no: str
    operation_name: str
    operation_type: OperationType
    targets: tuple[str, ...]
    content: str
    control_points: tuple[str, ...]
    equipment: tuple[str, ...] = ()
    inspection_items: tuple[str, ...] = ()
    drawing_basis: tuple[str, ...] = ()
    mandatory: bool = True

    def to_operation(self) -> Operation:
        return Operation(
            operation_no=self.operation_no,
            operation_name=self.operation_name,
            operation_type=self.operation_type,
            targets=list(self.targets),
            content=self.content,
            control_points=list(self.control_points),
            equipment=list(self.equipment),
            inspection_items=list(self.inspection_items),
            drawing_basis=list(self.drawing_basis),
            mandatory=self.mandatory,
        )


STANDARD_8_TEMPLATES = [
    OperationTemplate(
        "01",
        "毛坯预处理",
        OperationType.BLANK_PREPARATION,
        ("曲轴毛坯",),
        "检查毛坯状态，完成飞边、氧化皮、明显缺陷清理，并确认材料、炉批和热处理状态。",
        ("确认毛坯无裂纹、夹渣、明显变形", "核对材料与热处理要求", "为后续基准加工保留稳定装夹余量"),
        ("毛坯检验台", "清理工具"),
        ("外观", "材料标识", "热处理状态"),
        ("材料要求", "毛坯技术要求"),
    ),
    OperationTemplate(
        "02",
        "两端面铣削及中心孔加工",
        OperationType.BASELINE_PROCESSING,
        ("两端面", "中心孔"),
        "加工曲轴两端面并制备中心孔，建立后续车削和磨削的统一加工基准。",
        ("保证两端面平整", "中心孔位置稳定可靠", "基准加工后不得磕碰中心孔"),
        ("端面铣床", "中心孔机床"),
        ("端面尺寸", "中心孔质量"),
        ("基准要求", "端面尺寸"),
    ),
    OperationTemplate(
        "03",
        "粗车整体外形",
        OperationType.ROUGH_MACHINING,
        ("主轴颈", "连杆颈", "平衡块", "外圆轮廓"),
        "按图纸外形轮廓进行粗车，去除主要余量，形成主轴颈、连杆颈和平衡块基础形状。",
        ("保留半精加工余量", "避免过切圆角和过渡面", "控制粗车后变形"),
        ("数控车床"),
        ("粗加工余量", "外形轮廓"),
        ("外形尺寸", "轴颈位置要求"),
    ),
    OperationTemplate(
        "04",
        "半精车轴颈与过渡面",
        OperationType.SEMI_FINISHING,
        ("主轴颈", "连杆颈", "圆角过渡区"),
        "对轴颈、台阶和过渡圆角进行半精车，稳定精加工前尺寸和形位基础。",
        ("控制轴颈半精加工余量", "保护过渡圆角", "无倒角区域按图纸要求执行"),
        ("数控车床"),
        ("轴颈尺寸", "圆角状态", "形位基础"),
        ("轴颈尺寸", "圆角要求", "无倒角要求"),
    ),
    OperationTemplate(
        "05",
        "法兰及孔系加工",
        OperationType.HOLE_PROCESSING,
        ("法兰端", "螺栓孔", "定位销孔", "油道"),
        "加工法兰端面、螺栓孔、定位销孔和油道等孔系结构。",
        ("孔位置与孔径按图纸控制", "油道加工后不得残留毛刺", "定位销孔需保证定位精度"),
        ("加工中心", "钻削设备"),
        ("孔径", "孔距", "油道通畅性"),
        ("孔系尺寸", "油道要求", "法兰端要求"),
    ),
    OperationTemplate(
        "06",
        "精磨与滚压精加工",
        OperationType.FINISHING,
        ("主轴颈", "连杆颈", "滚压区域"),
        "对主轴颈、连杆颈进行精磨，并按图纸要求完成滚压或表面精整。",
        ("控制轴颈尺寸、公差和粗糙度", "滚压区域不得遗漏", "避免破坏圆角和过渡面"),
        ("外圆磨床", "滚压设备"),
        ("轴颈直径", "圆度", "粗糙度", "圆跳动"),
        ("轴颈公差", "表面粗糙度", "滚压要求"),
    ),
    OperationTemplate(
        "07",
        "分组打刻、无损检测与动平衡",
        OperationType.INSPECTION,
        ("轴颈", "打刻区", "整件"),
        "完成尺寸测量分组、标识打刻、无损检测和动平衡确认。",
        ("分组规则按图纸执行", "打刻位置不得影响功能面", "探伤和动平衡结果需记录"),
        ("测量设备", "打刻设备", "探伤设备", "动平衡机"),
        ("尺寸分组", "打刻内容", "探伤结果", "动平衡结果"),
        ("分组打刻要求", "探伤要求", "动平衡要求"),
    ),
    OperationTemplate(
        "08",
        "深度清洗与终检入库",
        OperationType.CLEANING_FINAL_INSPECTION,
        ("整件", "油道", "外观"),
        "对曲轴进行深度清洗、油道清洁和成品终检，合格后入库。",
        ("油道和孔系不得残留铁屑", "清洁度满足图纸或企业标准", "终检记录完整"),
        ("清洗机", "终检量具"),
        ("清洁度", "外观", "终检尺寸"),
        ("清洁度要求", "终检标准"),
    ),
]


DETAILED_10_TEMPLATES = [
    OperationTemplate("01", "毛坯修整", OperationType.BLANK_PREPARATION, ("曲轴毛坯",), "修整毛坯飞边和表面缺陷，确认毛坯状态。", ("确认毛坯质量", "核对材料与热处理要求"), ("毛坯检验台",), ("外观",), ("毛坯要求",)),
    OperationTemplate("02", "端面加工", OperationType.BASELINE_PROCESSING, ("两端面",), "加工曲轴两端面，为中心孔和后续装夹建立端面基础。", ("端面平整", "端面余量受控"), ("端面铣床",), ("端面尺寸",), ("端面尺寸",)),
    OperationTemplate("03", "基准中心孔加工", OperationType.BASELINE_PROCESSING, ("中心孔",), "加工两端中心孔，建立统一加工和检测基准。", ("中心孔位置准确", "中心孔不得磕碰"), ("中心孔机床",), ("中心孔质量",), ("基准要求",)),
    OperationTemplate("04", "粗车成型", OperationType.ROUGH_MACHINING, ("主轴颈", "连杆颈", "平衡块"), "粗车曲轴主体轮廓，去除主要加工余量。", ("保留半精加工余量", "控制粗车变形"), ("数控车床",), ("粗加工余量",), ("外形尺寸",)),
    OperationTemplate("05", "半精车精修", OperationType.SEMI_FINISHING, ("轴颈", "过渡面", "圆角"), "半精车轴颈、台阶和圆角，形成精加工前稳定状态。", ("保护圆角", "无倒角区按要求处理"), ("数控车床",), ("半精车尺寸",), ("轴颈尺寸", "圆角要求")),
    OperationTemplate("06", "孔系加工", OperationType.HOLE_PROCESSING, ("法兰孔", "定位销孔", "油道"), "加工法兰孔、定位销孔和油道孔系。", ("孔位孔径受控", "油道去毛刺"), ("加工中心",), ("孔径", "孔位", "油道通畅性"), ("孔系尺寸", "油道要求")),
    OperationTemplate("07", "轴颈精磨滚压", OperationType.FINISHING, ("主轴颈", "连杆颈", "滚压区域"), "对轴颈进行精磨和滚压，保证尺寸、公差与表面质量。", ("控制尺寸公差", "滚压区域不得遗漏", "控制粗糙度"), ("外圆磨床", "滚压设备"), ("轴颈直径", "粗糙度", "圆跳动"), ("轴颈公差", "滚压要求")),
    OperationTemplate("08", "尺寸检测与分组打刻", OperationType.INSPECTION, ("轴颈", "打刻区"), "完成多截面尺寸检测、分组计算和标识打刻。", ("分组规则准确", "打刻位置正确"), ("测量设备", "打刻设备"), ("尺寸分组", "打刻内容"), ("分组打刻要求", "测量要求")),
    OperationTemplate("09", "去毛刺外观精修与特种检测", OperationType.SPECIAL_PROCESS, ("整件", "孔口", "探伤区域"), "完成去毛刺、外观精修，并按要求执行探伤、退磁等特种检测。", ("孔口不得残留毛刺", "探伤后按要求退磁", "检测记录完整"), ("去毛刺工具", "探伤设备"), ("外观", "探伤结果", "退磁结果"), ("探伤要求", "退磁要求")),
    OperationTemplate("10", "深度清洗与成品终检", OperationType.CLEANING_FINAL_INSPECTION, ("整件", "油道", "孔系"), "深度清洗油道和孔系，完成成品终检并归档。", ("清洁度达标", "终检记录完整"), ("清洗机", "终检量具"), ("清洁度", "终检尺寸", "外观"), ("清洁度要求", "终检标准")),
]


PROCESS_TEMPLATES: dict[ProcessMode, list[OperationTemplate]] = {
    ProcessMode.STANDARD_8: STANDARD_8_TEMPLATES,
    ProcessMode.DETAILED_10: DETAILED_10_TEMPLATES,
}


REQUIREMENT_RULES = {
    RequirementType.MAGNETIC_PARTICLE_TESTING: {
        "keywords": ("磁粉探伤", "探伤", "无损检测"),
        "required_terms": ("探伤", "无损检测"),
        "control_point": "按图纸要求执行磁粉探伤并记录结果",
    },
    RequirementType.DEMAGNETIZATION: {
        "keywords": ("退磁",),
        "required_terms": ("退磁",),
        "control_point": "探伤后按图纸要求执行退磁处理",
    },
    RequirementType.DYNAMIC_BALANCING: {
        "keywords": ("动平衡", "平衡试验"),
        "required_terms": ("动平衡",),
        "control_point": "按图纸或企业标准完成动平衡试验",
    },
    RequirementType.GROUP_MARKING: {
        "keywords": ("分组", "打刻", "标识"),
        "required_terms": ("分组", "打刻"),
        "control_point": "按尺寸分组规则完成计算与打刻标识",
    },
    RequirementType.CLEANLINESS: {
        "keywords": ("清洁度", "清洗", "油道清洁"),
        "required_terms": ("清洁", "清洗"),
        "control_point": "油道和孔系清洁度必须满足图纸要求",
    },
    RequirementType.ROLLING: {
        "keywords": ("滚压",),
        "required_terms": ("滚压",),
        "control_point": "滚压区域、负载或工艺参数按图纸要求执行",
    },
    RequirementType.NO_CHAMFER: {
        "keywords": ("无倒角", "不得倒角"),
        "required_terms": ("无倒角", "不得倒角"),
        "control_point": "无倒角区域必须保护，不得擅自倒角或修磨",
    },
    RequirementType.MULTI_SECTION_MEASUREMENT: {
        "keywords": ("多截面", "多点测量", "截面测量"),
        "required_terms": ("测量", "检测"),
        "control_point": "按多截面多点测量规则执行尺寸检测",
    },
}


def get_templates(mode: ProcessMode) -> list[OperationTemplate]:
    return PROCESS_TEMPLATES[mode]
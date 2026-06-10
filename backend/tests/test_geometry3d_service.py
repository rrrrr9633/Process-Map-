from pathlib import Path

from app.services.geometry3d_service import geometry3d_service


def test_geometry3d_service_analyzes_ascii_stl(tmp_path: Path) -> None:
    stl = tmp_path / "shaft_like.stl"
    stl.write_text(
        """
solid shaft
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 100 0 0
      vertex 0 10 0
    endloop
  endfacet
  facet normal 0 0 1
    outer loop
      vertex 100 0 0
      vertex 100 10 0
      vertex 0 10 0
    endloop
  endfacet
endsolid shaft
""",
        encoding="utf-8",
    )

    result = geometry3d_service.parse_to_drawing_result(stl)

    assert "三维几何分析结果" in (result.raw_text or "")
    assert result.features
    assert result.features[0].name == "三维长轴主体"
    assert any("网格模型只含几何外形" in flag.message for flag in result.risk_flags)


def test_geometry3d_service_reports_step_kernel_requirement(tmp_path: Path) -> None:
    step = tmp_path / "part.step"
    step.write_text("ISO-10303-21;", encoding="utf-8")

    result = geometry3d_service.parse_to_drawing_result(step)

    assert "STEP/IGES" in (result.raw_text or "")
    assert any(flag.field == "geometry_3d" for flag in result.risk_flags)

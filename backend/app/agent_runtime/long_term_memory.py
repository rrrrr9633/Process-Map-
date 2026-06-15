from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import settings
from app.models.case import HumanEdit, ProcessCase


class LongTermMemoryService:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else settings.knowledge_base_path / "agent_memory"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "memory_index.json"
        self.feedback_path = self.base_dir / "case_feedback.jsonl"

    def index_case(self, case: ProcessCase) -> dict[str, Any]:
        index = self._load_index()
        document = self.case_document(case)
        entry = {
            "memory_id": f"case:{case.case_id}",
            "kind": "case",
            "case_id": case.case_id,
            "title": case.case_name,
            "document": document,
            "tokens": sorted(_tokens(document)),
            "quality": case.quality.value if case.quality else "",
            "status": case.status.value,
            "ai_error_count": len(case.ai_errors),
            "human_edit_count": len(case.human_edits),
            "updated_at": case.updated_at.isoformat(),
        }
        index[entry["memory_id"]] = entry
        self._save_index(index)
        return entry

    def record_human_edit(self, case: ProcessCase, edit: HumanEdit) -> dict[str, Any]:
        entry = {
            "memory_id": f"feedback:{uuid4().hex}",
            "kind": "human_edit",
            "case_id": case.case_id,
            "title": f"人工修正：{case.case_name}",
            "document": " ".join(
                [
                    case.case_name,
                    edit.field,
                    edit.original_value,
                    edit.edited_value,
                    edit.reason or "",
                ]
            ),
            "tokens": [],
            "created_at": datetime.now().isoformat(),
        }
        entry["tokens"] = sorted(_tokens(entry["document"]))
        self._append_feedback(entry)
        self.index_case(case)
        return entry

    def record_ai_error(self, case: ProcessCase, error_description: str) -> dict[str, Any]:
        entry = {
            "memory_id": f"feedback:{uuid4().hex}",
            "kind": "ai_error",
            "case_id": case.case_id,
            "title": f"AI 错误：{case.case_name}",
            "document": f"{case.case_name} {error_description}",
            "tokens": [],
            "created_at": datetime.now().isoformat(),
        }
        entry["tokens"] = sorted(_tokens(entry["document"]))
        self._append_feedback(entry)
        self.index_case(case)
        return entry

    def search(self, query: str, *, limit: int = 5, include_feedback: bool = True) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        candidates = list(self._load_index().values())
        if include_feedback:
            candidates.extend(self._load_feedback())
        scored: list[dict[str, Any]] = []
        for item in candidates:
            item_tokens = set(item.get("tokens") or [])
            score = _score(query_tokens, item_tokens)
            if item.get("kind") == "case":
                score += _quality_boost(item)
                score -= min(0.2, 0.03 * int(item.get("ai_error_count") or 0))
            if score <= 0:
                continue
            scored.append({**item, "score": round(score, 4)})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[: max(1, min(limit, 20))]

    def case_document(self, case: ProcessCase) -> str:
        part = case.drawing_parse_result.part
        operations = [
            " ".join(
                [
                    operation.operation_name,
                    " ".join(operation.targets),
                    " ".join(operation.control_points),
                    " ".join(operation.inspection_items),
                    " ".join(operation.drawing_basis),
                ]
            )
            for operation in case.process_plan.operations
        ]
        edits = [f"{edit.field} {edit.original_value} {edit.edited_value} {edit.reason or ''}" for edit in case.human_edits]
        return " ".join(
                [
                    case.case_name,
                    part.part_name or "",
                    part.material or "",
                    part.heat_treatment or "",
                " ".join(case.tags),
                " ".join(operations),
                " ".join(case.ai_errors),
                " ".join(edits),
                case.production_feedback or "",
                " ".join(case.quality_issues),
            ]
        )

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _save_index(self, index: dict[str, dict[str, Any]]) -> None:
        temp_path = self.index_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.index_path)

    def _append_feedback(self, entry: dict[str, Any]) -> None:
        with self.feedback_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load_feedback(self) -> list[dict[str, Any]]:
        if not self.feedback_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.feedback_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                entries.append(item)
        return entries


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    latin = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    cjk = set(re.findall(r"[\u4e00-\u9fff]{2,}", lowered))
    bigrams: set[str] = set()
    for chunk in cjk:
        bigrams.update(chunk[index : index + 2] for index in range(max(0, len(chunk) - 1)))
    return latin | cjk | bigrams


def _score(query_tokens: set[str], item_tokens: set[str]) -> float:
    overlap = query_tokens & item_tokens
    if not overlap:
        return 0.0
    return len(overlap) / math.sqrt(max(1, len(query_tokens)) * max(1, len(item_tokens)))


def _quality_boost(item: dict[str, Any]) -> float:
    quality = str(item.get("quality") or "")
    return {
        "excellent": 0.2,
        "good": 0.12,
        "normal": 0.05,
        "poor": -0.1,
    }.get(quality, 0.0)


long_term_memory_service = LongTermMemoryService()

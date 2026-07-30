"""黄金评测集：以仿真器 sidecar 真值（*.truth.json）为标注来源。

关键纪律：truth.json 中的 narrative / root_cause_label 等字段绝不进入模型上下文，
只在评测阶段与 Agent 输出比对——否则就是答案泄漏。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vela.util.jsonl import read_json


@dataclass
class GoldenCase:
    archive: Path
    truth_path: Path
    truth: dict = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        return self.truth.get("scenario_id", self.archive.stem)

    @property
    def expected_label(self) -> str | None:
        return self.truth.get("root_cause_label")

    @property
    def healthy(self) -> bool:
        return bool(self.truth.get("healthy"))

    @property
    def expected_skills(self) -> list[str]:
        return list(self.truth.get("expect_skills") or [])

    @property
    def expected_phase(self) -> str | None:
        return self.truth.get("fail_phase")

    @property
    def culprit_components(self) -> list[str]:
        return list(self.truth.get("culprit_components") or [])


def load_golden(dataset_dir: str | Path) -> list[GoldenCase]:
    d = Path(dataset_dir)
    cases: list[GoldenCase] = []
    for zp in sorted(d.glob("*.zip")):
        tp = d / f"{zp.stem}.truth.json"
        if not tp.exists():
            continue
        cases.append(GoldenCase(archive=zp, truth_path=tp, truth=read_json(tp)))
    return cases

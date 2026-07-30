"""
配置加载：YAML + 环境变量覆盖。

优先级（高 -> 低）： 显式函数参数 > 进程环境变量 > .env > config/*.yaml > 代码内默认值
.env 在本模块导入时静默加载一次（override=False）。
生产接入切换点全部收敛在这里，业务代码不读 os.environ。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv
import yaml

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _find_project_root(start: Path) -> Path | None:
    """从 start 起按锚点回溯定位项目根。

    采用锚点回溯而非 find_dotenv(usecwd=True)：usecwd=True 会让 .env
    定位随 cwd 漂移，直接违反 D-07「不受 cwd 影响」。以 __file__ 为起点，
    可编辑安装下第一跳即命中项目根（<root>/src/vela/config.py → <root> 有
    pyproject.toml）；常规安装到 site-packages 时一路无锚点，返回 None → 静默跳过。
    """
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return None


_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

_DOTENV_STATE: dict[str, Any] = {
    "path": None,
    "loaded": False,
    "keys": [],
    "shadowed": [],
}
_DOTENV_LOADED: bool = False


def _apply_dotenv(root: Path | None) -> dict[str, Any]:
    """加载 root/.env 到 os.environ（override=False）；root 可注入以便单测。"""
    empty: dict[str, Any] = {"path": None, "loaded": False, "keys": [], "shadowed": []}
    if root is None:
        return empty
    path = root / ".env"
    if not path.is_file():
        return empty
    file_keys = [k for k in dotenv_values(path) if k is not None]
    shadowed = sorted(k for k in file_keys if k in os.environ)
    load_dotenv(dotenv_path=path, override=False)
    return {
        "path": str(path),
        "loaded": True,
        "keys": sorted(file_keys),
        "shadowed": shadowed,
    }


def _load_dotenv_once() -> None:
    """模块导入期幂等守卫：只加载一次项目根 .env。"""
    global _DOTENV_LOADED, _DOTENV_STATE
    if _DOTENV_LOADED:
        return
    _DOTENV_STATE = _apply_dotenv(_PROJECT_ROOT)
    _DOTENV_LOADED = True


def dotenv_report() -> dict[str, Any]:
    """供 doctor 消费的 .env 加载事实（只含键名，不含任何值）。"""
    return dict(_DOTENV_STATE)


def config_dir() -> Path:
    return Path(os.environ.get("VELA_CONFIG_DIR", str(_DEFAULT_CONFIG_DIR))).resolve()


def workspace_dir() -> Path:
    return Path(os.environ.get("VELA_WORKSPACE", "./workspace")).resolve()


@lru_cache(maxsize=32)
def load_yaml(name: str) -> dict[str, Any]:
    p = config_dir() / name
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {p}（可用 VELA_CONFIG_DIR 指定目录）")
    with open(p, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_skills() -> list[dict[str, Any]]:
    """加载技能库：config/skills/ 下所有 *.yaml 合并，按 id 字典序稳定排序。"""
    out: list[dict[str, Any]] = []
    d = config_dir() / "skills"
    if d.exists():
        for p in sorted(d.glob("*.yaml")):
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            out.extend(data.get("skills", []))
    return sorted(out, key=lambda s: s["id"])


@dataclass(frozen=True)
class BudgetProfile:
    """机制一/机制四的全部可调参数，从 budget.yaml 的某个 profile 实例化。"""
    name: str
    whitelist_terms: tuple[str, ...]
    whitelist_cap_per_template: int
    rare_template_max_count: int
    template_quota_lines: int
    slide_window_seconds: int
    round_evidence_tokens: int
    session_evidence_multiplier: int
    round_llm_tokens: int
    session_llm_tokens: int
    max_rounds: int
    detail_fetch_hard_limit: int
    wide_result_warn_threshold: int
    context_lines_limit: int
    sql_max_rows: int
    bytes_per_token_ascii: float = 4.0
    bytes_per_token_cjk: float = 1.5

    @property
    def session_evidence_tokens(self) -> int:
        return self.round_evidence_tokens * self.session_evidence_multiplier


def load_budget(profile: str | None = None) -> BudgetProfile:
    cfg = load_yaml("budget.yaml")
    name = profile or os.environ.get("VELA_PROFILE") or cfg.get("active_profile", "poc")
    profiles = cfg["profiles"]
    if name not in profiles:
        raise KeyError(f"未知 profile: {name}，可选: {sorted(profiles)}")
    p = profiles[name]
    te = cfg.get("token_estimate", {})
    return BudgetProfile(
        name=name,
        whitelist_terms=tuple(str(t).lower() for t in p["compression"]["whitelist_terms"]),
        whitelist_cap_per_template=int(p["compression"]["whitelist_cap_per_template"]),
        rare_template_max_count=int(p["compression"]["rare_template_max_count"]),
        template_quota_lines=int(p["compression"]["template_quota_lines"]),
        slide_window_seconds=int(p["compression"]["slide_window_seconds"]),
        round_evidence_tokens=int(p["budget"]["round_evidence_tokens"]),
        session_evidence_multiplier=int(p["budget"]["session_evidence_multiplier"]),
        round_llm_tokens=int(p["budget"]["round_llm_tokens"]),
        session_llm_tokens=int(p["budget"]["session_llm_tokens"]),
        max_rounds=int(p["budget"]["max_rounds"]),
        detail_fetch_hard_limit=int(p["guardrail"]["detail_fetch_hard_limit"]),
        wide_result_warn_threshold=int(p["guardrail"]["wide_result_warn_threshold"]),
        context_lines_limit=int(p["guardrail"]["context_lines_limit"]),
        sql_max_rows=int(p["guardrail"]["sql_max_rows"]),
        bytes_per_token_ascii=float(te.get("bytes_per_token_ascii", 4.0)),
        bytes_per_token_cjk=float(te.get("bytes_per_token_cjk", 1.5)),
    )


@dataclass(frozen=True)
class PipelineConfig:
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur


def load_pipeline() -> PipelineConfig:
    return PipelineConfig(load_yaml("pipeline.yaml"))


def tenant_id() -> str:
    """强制租户谓词的租户标识（机制四：查询门面唯一收口）。"""
    return os.environ.get("VELA_TENANT", "demo-tenant")


def config_hash() -> str:
    """
    参数与规则集的联合指纹，写入 runs.config_hash；跨 run 比较指纹前必须一致。
    覆盖：pipeline.yaml + parsers.yaml + ota_phases.yaml + 规范化规则版本 + 实际生效的哈希算法。
    """
    import hashlib

    from vela.util.hashing import fingerprint_algos
    from vela.util.jsonl import canonical_json
    from vela.util.textutil import canon_rules_version

    payload = canonical_json({
        "pipeline": load_yaml("pipeline.yaml"),
        "parsers": load_yaml("parsers.yaml"),
        "phases": load_yaml("ota_phases.yaml"),
        "canon_rules_version": canon_rules_version(),
        "algos": fingerprint_algos(),
    })
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


_load_dotenv_once()

"""环境变量形态检查器（D-16 / ENV-04）：纯诊断、不进 config_hash。"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from vela.config import load_yaml
from vela.util.textutil import mask_secret


class EnvChecker:
    """规则驱动的 .env / 进程环境变量形态检查；cfg 与 environ 均可注入。"""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg if cfg is not None else load_yaml("env_checks.yaml")
        self._hygiene: list[tuple[str, re.Pattern[str], str]] = [
            (r["name"], re.compile(r["pattern"]), r["hint"])
            for r in cfg.get("value_hygiene", [])
        ]
        self._variables: list[dict[str, Any]] = []
        for v in cfg.get("variables", []):
            pat = v.get("pattern") or ""
            self._variables.append({
                "name": v["name"],
                "display": v.get("display", "plain"),
                "required_for_providers": list(v.get("required_for_providers") or []),
                "pattern": re.compile(pat) if pat else None,
                "hint": v.get("hint", ""),
            })

    def run(self, provider: str,
            environ: Mapping[str, str] | None = None) -> list[dict]:
        env = os.environ if environ is None else environ
        results: list[dict] = []
        for var in self._variables:
            results.append(self._check_one(var, provider, env))
        return results

    def _check_one(self, var: dict[str, Any], provider: str,
                   env: Mapping[str, str]) -> dict:
        name = var["name"]
        raw = env.get(name)
        value = raw if raw is not None else ""
        if not value:
            if provider in var["required_for_providers"]:
                return _item(name, False, var["hint"])
            return _item(name, True, "未设置（当前 provider 不需要）")

        shown = mask_secret(value) if var["display"] == "masked" else value

        for _hname, rx, hint in self._hygiene:
            if rx.search(value):
                return _item(name, False, f"值={shown} — {hint}")

        pat = var["pattern"]
        if pat is not None and pat.fullmatch(value) is None:
            return _item(name, False, f"值={shown} — {var['hint']}")

        return _item(name, True, shown)


def _item(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "kind": "local"}

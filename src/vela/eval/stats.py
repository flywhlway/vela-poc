"""评测重复跑统计：均值 / 标准差 / Student t 双侧置信区间（METR-04）。

仅在 `--repeat N` 路径按需 import scipy；主链路（单次 eval）不顶层依赖。
"""
from __future__ import annotations

from typing import Any


def mean_std_ci(values: list[float], confidence: float = 0.95) -> dict[str, Any]:
    """返回 {mean, std, ci95, n}；n<2 时 ci95=None。

    使用 scipy.stats.t.interval + sem（非手写 t 表）。缺包时抛出安装指引。
    """
    try:
        import numpy as np
        from scipy import stats
    except ImportError as e:
        raise ImportError(
            "重复评测统计需要 scipy。请安装：pip install -e '.[eval]' 或 pip install 'scipy>=1.11'"
        ) from e

    xs = np.asarray(values, dtype=float)
    n = int(xs.size)
    if n == 0:
        return {"mean": 0.0, "std": 0.0, "ci95": None, "n": 0}
    mean = float(np.mean(xs))
    std = float(np.std(xs, ddof=1)) if n >= 2 else 0.0
    if n < 2:
        return {"mean": mean, "std": std, "ci95": None, "n": n}
    sem = float(stats.sem(xs))
    lo, hi = stats.t.interval(confidence, df=n - 1, loc=mean, scale=sem)
    return {"mean": mean, "std": std, "ci95": [float(lo), float(hi)], "n": n}


def aggregate_metrics(runs: list[dict[str, Any]],
                      keys: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """对多次 metrics() 字典中的数值键做 mean_std_ci 聚合。"""
    if not runs:
        return {}
    if keys is None:
        keys = sorted({k for m in runs for k, v in m.items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)})
    out: dict[str, dict[str, Any]] = {}
    for k in keys:
        vals = [float(m[k]) for m in runs if k in m and m[k] is not None
                and isinstance(m[k], (int, float)) and not isinstance(m[k], bool)]
        if vals:
            out[k] = mean_std_ci(vals)
    return out

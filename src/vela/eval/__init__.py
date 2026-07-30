"""评估平面：黄金评测集 + 指标计算 + 报告渲染。"""
from vela.eval.golden import GoldenCase, load_golden
from vela.eval.report import render_markdown
from vela.eval.runner import EvalRunner, EvalResult

__all__ = ["GoldenCase", "load_golden", "EvalRunner", "EvalResult", "render_markdown"]

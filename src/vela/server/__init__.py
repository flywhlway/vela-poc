"""本地 HTTP 服务：优先 FastAPI，缺失时自动降级为标准库 http.server（零依赖可运行）。"""
from vela.server.app import build_app, serve

__all__ = ["build_app", "serve"]

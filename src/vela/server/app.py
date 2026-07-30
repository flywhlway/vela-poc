"""本地服务：查询工具 REST 化 + 诊断会话 + 事件流（SSE）+ 指标。

设计原则：不引入容器与外部中间件。FastAPI 可用则用之（带自动 OpenAPI 文档），
不可用则用标准库 http.server 提供同样的路由，保证"任何一台装了 Python 的机器都能跑"。
"""
from __future__ import annotations

import json
from pathlib import Path

from vela.query.api import LogQueryAPI
from vela.query.tools import TOOLS_BY_NAME, TOOL_SPECS
from vela.version import __version__

_STATE: dict = {}


def _json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


def _api() -> LogQueryAPI:
    if "api" not in _STATE:
        _STATE["api"] = LogQueryAPI(_STATE["db"])
    return _STATE["api"]


def _handle(path: str, body: dict) -> tuple[int, dict]:
    if path == "/health":
        return 200, {"ok": True, "version": __version__, "db": _STATE.get("db")}
    if path == "/tools":
        return 200, {"tools": TOOL_SPECS}
    if path == "/describe":
        r = _api().call("describe_dataset")
        return 200, r.to_dict()
    if path == "/call":
        tool = body.get("tool")
        if tool not in TOOLS_BY_NAME:
            return 400, {"error": f"未知工具 {tool}"}
        r = _api().call(tool, **(body.get("args") or {}))
        return (200 if r.ok else 400), r.to_dict()
    if path == "/diagnose":
        from vela.agent.graph import AgentGraph
        g = AgentGraph(_STATE["db"], workspace=_STATE.get("ws"),
                       provider=body.get("provider"), profile=body.get("profile"),
                       question=body.get("question"))
        try:
            res = g.run(max_rounds=body.get("max_rounds"))
        finally:
            g.close()
        return 200, {"status": res.state.status, "root_cause": res.state.root_cause,
                     "report_md": res.state.report_md,
                     "citation_check": res.state.citation_check,
                     "evidence_pack": res.state.evidence_pack,
                     "rounds": res.state.round_no, "gateway": res.gateway_stats,
                     "metrics": res.metrics}
    if path == "/metrics":
        p = Path(_STATE.get("ws") or ".") / "obs" / "events.jsonl"
        n = sum(1 for _ in p.open(encoding="utf-8")) if p.exists() else 0
        return 200, {"events": n, "calls": len(_api().call_log)}
    if path == "/events":
        p = Path(_STATE.get("ws") or ".") / "obs" / "events.jsonl"
        since = int(body.get("since") or 0)
        evs = []
        if p.exists():
            for line in p.open(encoding="utf-8"):
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("event_id", 0) > since:
                    evs.append(e)
        return 200, {"events": evs[-500:]}
    return 404, {"error": f"未知路径 {path}"}


# ------------------------------------------------------------------ FastAPI
def build_app(db: str, workspace: str | None = None):
    _STATE["db"] = db
    _STATE["ws"] = workspace or str(Path(db).parent.parent)
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, PlainTextResponse
    except ImportError:
        return None

    app = FastAPI(title="VELA 车端日志证据化诊断", version=__version__,
                  description="本地优先的 OTA 日志取证与诊断服务")

    @app.get("/health")
    def health():
        return _handle("/health", {})[1]

    @app.get("/tools")
    def tools():
        return _handle("/tools", {})[1]

    @app.get("/describe")
    def describe():
        return _handle("/describe", {})[1]

    @app.post("/call")
    async def call(req: Request):
        code, data = _handle("/call", await req.json())
        return JSONResponse(data, status_code=code)

    @app.post("/diagnose")
    async def diagnose(req: Request):
        code, data = _handle("/diagnose", await req.json())
        return JSONResponse(data, status_code=code)

    @app.get("/events")
    def events(since: int = 0):
        return _handle("/events", {"since": since})[1]

    @app.get("/metrics")
    def metrics():
        return PlainTextResponse(json.dumps(_handle("/metrics", {})[1], ensure_ascii=False))

    return app


# --------------------------------------------------------------- 降级实现
def _stdlib_serve(host: str, port: int) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, data: dict):
            payload = _json(data)
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):                                   # noqa: N802
            u = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(u.query).items()}
            self._send(*_handle(u.path, qs))

        def do_POST(self):                                  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "请求体不是合法 JSON"})
            self._send(*_handle(urlparse(self.path).path, body))

        def log_message(self, fmt, *args):                  # 静默访问日志
            pass

    print(f"⚠️  未检测到 FastAPI，已降级为标准库 HTTP 服务：http://{host}:{port}")
    print("   路由: GET /health /tools /describe /events /metrics ； POST /call /diagnose")
    ThreadingHTTPServer((host, port), H).serve_forever()
    return 0


def serve(db: str, workspace: str | None = None, host: str = "127.0.0.1",
          port: int = 8848) -> int:
    app = build_app(db, workspace)
    if app is None:
        return _stdlib_serve(host, port)
    try:
        import uvicorn
    except ImportError:
        return _stdlib_serve(host, port)
    print(f"🚀 VELA 服务: http://{host}:{port}   交互文档: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0

"""LogQueryAPI —— Agent 工具集的唯一实现，也是列式库的唯一查询收口。

每个工具返回统一的 ToolResult：
  rows / total_matches / rows_scanned / elapsed_ms / truncated / next_cursor / notes
其中 notes 承载护栏告警与降级说明，会被原样注入模型上下文（在环负反馈）。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from vela.config import BudgetProfile, load_budget, load_yaml, tenant_id
from vela.query.guard import Guardrail, SqlGuard, SqlGuardError, wrap_log_content
from vela.query.tools import TOOLS_BY_NAME, tool_names
from vela.util.textutil import estimate_tokens
from vela.util.timeutil import bucket_seconds, iso, parse_iso

_LEVELS = {"TRACE": 10, "DEBUG": 20, "INFO": 25, "NOTICE": 28, "WARN": 30, "ERROR": 40, "FATAL": 50}
_GROUP_WHITELIST = {"component", "level_norm", "template_id", "ota_phase", "ecu_id",
                    "parser_name", "parse_status", "logger", "boot_id", "ts_kind"}
_SUMMARY_COLS = ("line_id", "ts_utc", "ts_confidence", "ts_kind", "component", "level_norm",
                 "ota_phase", "ecu_id", "template_id", "row_hash", "file_path", "line_no")


@dataclass
class ToolResult:
    tool: str
    ok: bool = True
    rows: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    total_matches: int = 0
    rows_scanned: int = 0
    elapsed_ms: float = 0.0
    truncated: bool = False
    next_cursor: str | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def est_tokens(self) -> int:
        return estimate_tokens(json.dumps(self.rows, ensure_ascii=False, default=str))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["est_tokens"] = self.est_tokens
        return d


class LogQueryAPI:
    def __init__(self, db_path: str | Path, budget: BudgetProfile | None = None,
                 tenant: str | None = None, read_only: bool = True):
        self.db_path = str(db_path)
        self.con = duckdb.connect(self.db_path, read_only=read_only)
        self.budget = budget or load_budget()
        self.guard = Guardrail(self.budget)
        self.sqlguard = SqlGuard(max_rows=self.budget.sql_max_rows)
        self.tenant = tenant or tenant_id()
        self._nrc = load_yaml("ota_phases.yaml").get("uds_nrc", {})
        self._fts = self._probe_fts()
        self.call_log: list[dict] = []

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass

    def _probe_fts(self) -> bool:
        try:
            self.con.execute("LOAD fts")
            self.con.execute("SELECT 1 FROM fts_main_log_lines.docs LIMIT 1").fetchone()
            return True
        except Exception:
            return False

    def _q(self, sql: str, params: dict | None = None) -> list[dict]:
        cur = self.con.execute(sql, params or {})
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _check_tenant(self) -> str | None:
        row = self._q("SELECT tenant_id FROM runs LIMIT 1")
        if not row:
            return "[GUARDRAIL] runs 表为空，无法校验租户归属。"
        if row[0]["tenant_id"] != self.tenant:
            return (f"[GUARDRAIL] 租户不匹配：库归属 {row[0]['tenant_id']}，"
                    f"当前上下文 {self.tenant}，已拒绝返回明细。")
        return None

    def call(self, tool: str, **kwargs) -> ToolResult:
        """统一入口：记录调用轨迹（可观测/可重放），并强制租户校验。"""
        t0 = time.time()
        if tool not in TOOLS_BY_NAME:
            return ToolResult(tool=tool, ok=False, error=f"未知工具 {tool}，可用: {tool_names()}")
        deny = self._check_tenant()
        if deny and tool not in ("describe_dataset",):
            return ToolResult(tool=tool, ok=False, error=deny, notes=[deny])
        try:
            res: ToolResult = getattr(self, f"t_{tool}")(**kwargs)
        except SqlGuardError as e:
            res = ToolResult(tool=tool, ok=False, error=f"SQL 沙箱拒绝：{e}")
        except TypeError as e:
            res = ToolResult(tool=tool, ok=False, error=f"参数错误：{e}")
        except Exception as e:                                  # pragma: no cover - 防御式
            res = ToolResult(tool=tool, ok=False, error=f"{type(e).__name__}: {e}")
        res.elapsed_ms = round((time.time() - t0) * 1000, 2)
        self.call_log.append({"tool": tool, "args": {k: v for k, v in sorted(kwargs.items())},
                              "ok": res.ok, "rows": len(res.rows),
                              "total_matches": res.total_matches,
                              "elapsed_ms": res.elapsed_ms, "est_tokens": res.est_tokens,
                              "notes": list(res.notes)})
        return res

    # ---------------- 鸟瞰型 ---------------- #
    def t_describe_dataset(self) -> ToolResult:
        run = self._q("SELECT * FROM runs LIMIT 1")
        comp = self._q("SELECT component, lines, errors, ts_min, ts_max, "
                       "round(avg_ts_conf,3) AS avg_ts_conf FROM v_component_stats ORDER BY lines DESC")
        ph = self._q("SELECT ota_phase, lines, errors, round(duration_s,1) AS duration_s, "
                     "started_at, ended_at FROM v_phase_spans ORDER BY started_at")
        lvl = self._q("SELECT level_norm, count(*) AS n FROM log_lines GROUP BY 1 ORDER BY 2 DESC")
        kinds = self._q("SELECT ts_kind, count(*) AS n FROM log_lines GROUP BY 1 ORDER BY 2 DESC")
        tot = self._q("SELECT count(*) n, min(ts_utc) lo, max(ts_utc) hi, "
                      "count(DISTINCT template_id) t FROM log_lines")[0]
        r = run[0] if run else {}
        return ToolResult(
            tool="describe_dataset",
            summary={
                "run_id": r.get("run_id"), "input_archive": r.get("input_archive"),
                "input_sha256": r.get("input_sha256"), "config_hash": r.get("config_hash"),
                "total_records": tot["n"], "templates": tot["t"],
                "ts_min": iso(tot["lo"]), "ts_max": iso(tot["hi"]),
                "unparsed_records": r.get("unparsed_records"),
                "levels": {x["level_norm"]: x["n"] for x in lvl},
                "ts_kinds": {x["ts_kind"]: x["n"] for x in kinds},
                "phases": [{k: (iso(v) if hasattr(v, "isoformat") else v) for k, v in p.items()} for p in ph],
                "hint": ("ts_confidence>=0.9 可用于毫秒级因果；0.6~0.9 只能用于秒/分钟级关联；"
                         "<0.6 结论中必须声明时间不确定性。"),
            },
            rows=[{k: (iso(v) if hasattr(v, "isoformat") else v) for k, v in c.items()} for c in comp],
            total_matches=len(comp), rows_scanned=tot["n"])

    def t_timeline(self, bucket: str = "1m", time_from: str | None = None, time_to: str | None = None,
                   components: list[str] | None = None, min_level: str | None = None) -> ToolResult:
        sec = bucket_seconds(bucket)
        where, params = self._where(components=components, min_level=min_level,
                                    time_from=time_from, time_to=time_to)
        rows = self._q(f"""
            SELECT to_timestamp(floor(epoch(ts_utc)/{sec})*{sec}) AS bucket_ts,
                   component,
                   count(*) AS n,
                   sum(CASE WHEN level_num>=40 THEN 1 ELSE 0 END) AS errors,
                   sum(CASE WHEN level_num=30 THEN 1 ELSE 0 END) AS warns
            FROM log_lines WHERE {where}
            GROUP BY 1,2 ORDER BY 1,2
        """, params)
        out = [{"bucket_ts": iso(r["bucket_ts"]), "component": r["component"],
                "n": r["n"], "errors": r["errors"], "warns": r["warns"]} for r in rows]
        return ToolResult(tool="timeline", rows=out, total_matches=len(out),
                          summary={"bucket": bucket, "buckets": len({r['bucket_ts'] for r in out})})

    def t_aggregate(self, group_by: list[str], filters: dict | None = None,
                    order_by: str = "count_desc", limit: int = 50) -> ToolResult:
        bad = [g for g in group_by if g not in _GROUP_WHITELIST]
        if bad:
            return ToolResult(tool="aggregate", ok=False,
                              error=f"维度不在白名单内: {bad}，可用: {sorted(_GROUP_WHITELIST)}")
        limit = min(int(limit), 500)
        f = filters or {}
        where, params = self._where(components=f.get("components"), min_level=f.get("min_level"),
                                    time_from=f.get("time_from"), time_to=f.get("time_to"),
                                    ota_phase=f.get("ota_phase"), ecu_id=f.get("ecu_id"))
        cols = ", ".join(group_by)
        order = {"count_desc": "n DESC", "count_asc": "n ASC",
                 "first_seen": "first_seen ASC"}.get(order_by, "n DESC")
        rows = self._q(f"""
            SELECT {cols}, count(*) AS n, min(ts_utc) AS first_seen, max(ts_utc) AS last_seen,
                   sum(CASE WHEN level_num>=40 THEN 1 ELSE 0 END) AS errors
            FROM log_lines WHERE {where}
            GROUP BY {cols} ORDER BY {order}, {cols} LIMIT {limit}
        """, params)
        out = [{**{k: r[k] for k in group_by},
                "n": r["n"], "errors": r["errors"],
                "first_seen": iso(r["first_seen"]), "last_seen": iso(r["last_seen"])} for r in rows]
        return ToolResult(tool="aggregate", rows=out, total_matches=len(out),
                          summary={"group_by": group_by})

    def t_top_templates(self, sort: str = "error_only", components: list[str] | None = None,
                        limit: int = 30) -> ToolResult:
        limit = min(int(limit), 200)
        cond = "1=1"
        params: dict = {}
        if components:
            cond += " AND list_contains($comps, t.components[1])"
            params["comps"] = list(components)
        order = {"frequent": "t.occurrences DESC", "rare": "t.occurrences ASC",
                 "error_only": "t.occurrences DESC", "newest": "t.first_seen_utc DESC"}.get(sort, "t.occurrences DESC")
        if sort == "error_only":
            # is_error_like 是文本启发式：单靠它会把 DEBUG 级的 "NRC received ..." 当成故障信号。
            # 叠加级别过滤，确保鸟瞰阶段拿到的是真正的错误面貌。
            cond += (" AND t.is_error_like"
                     " AND coalesce(t.level_mode,'') NOT IN ('DEBUG','TRACE')")
        rows = self._q(f"""
            SELECT t.template_id, t.template_text, t.occurrences, t.param_count,
                   t.components, t.level_mode, t.is_error_like,
                   t.first_seen_utc, t.last_seen_utc
            FROM templates t WHERE {cond}
            ORDER BY {order}, t.template_id LIMIT {limit}
        """, params)
        out = [{**{k: v for k, v in r.items() if k not in ("first_seen_utc", "last_seen_utc")},
                "first_seen": iso(r["first_seen_utc"]), "last_seen": iso(r["last_seen_utc"])}
               for r in rows]
        return ToolResult(tool="top_templates", rows=out, total_matches=len(out),
                          summary={"sort": sort,
                                   "hint": "稀有模板（occurrences 小）常是根因所在，与通用摘要『保高频』相反。"})

    def t_phase_timeline(self, ecu_id: str | None = None) -> ToolResult:
        params: dict = {}
        cond = "ota_phase IS NOT NULL"
        if ecu_id:
            cond += " AND ecu_id = $ecu"
            params["ecu"] = ecu_id
        rows = self._q(f"""
            SELECT ota_phase, min(ts_utc) AS started_at, max(ts_utc) AS ended_at,
                   count(*) AS lines,
                   sum(CASE WHEN level_num>=40 THEN 1 ELSE 0 END) AS errors,
                   round(epoch(max(ts_utc))-epoch(min(ts_utc)),2) AS duration_s
            FROM log_lines WHERE {cond}
            GROUP BY ota_phase ORDER BY started_at
        """, params)
        out = [{"ota_phase": r["ota_phase"], "started_at": iso(r["started_at"]),
                "ended_at": iso(r["ended_at"]), "duration_s": r["duration_s"],
                "lines": r["lines"], "errors": r["errors"]} for r in rows]
        last = out[-1]["ota_phase"] if out else None
        aborted = self._q("""SELECT raw_line, ts_utc, row_hash, line_id FROM log_lines
                             WHERE lower(raw_line) LIKE '%aborted at%'
                                OR lower(raw_line) LIKE '%campaign aborted%'
                             ORDER BY ts_utc LIMIT 5""")
        return ToolResult(tool="phase_timeline", rows=out, total_matches=len(out),
                          summary={"last_phase": last,
                                   "abort_markers": [{"line_id": a["line_id"], "row_hash": a["row_hash"],
                                                      "ts_utc": iso(a["ts_utc"]),
                                                      "raw_line": a["raw_line"][:200]} for a in aborted]})

    def t_find_gaps(self, min_gap_seconds: float = 30, components: list[str] | None = None,
                    limit: int = 30) -> ToolResult:
        limit = min(int(limit), 200)
        where, params = self._where(components=components)
        rows = self._q(f"""
            WITH x AS (
              SELECT component, ts_utc, line_id, row_hash, raw_line,
                     lag(ts_utc) OVER (PARTITION BY component ORDER BY ts_utc, line_id) AS prev_ts,
                     lag(line_id) OVER (PARTITION BY component ORDER BY ts_utc, line_id) AS prev_line
              FROM log_lines WHERE {where} AND ts_utc IS NOT NULL
            )
            SELECT component, prev_ts AS gap_start, ts_utc AS gap_end,
                   round(epoch(ts_utc)-epoch(prev_ts),3) AS gap_seconds,
                   prev_line AS before_line_id, line_id AS after_line_id,
                   row_hash AS after_row_hash, raw_line AS after_raw_line
            FROM x WHERE prev_ts IS NOT NULL
              AND epoch(ts_utc)-epoch(prev_ts) >= {float(min_gap_seconds)}
            ORDER BY gap_seconds DESC, component LIMIT {limit}
        """, params)
        out = [{"component": r["component"], "gap_start": iso(r["gap_start"]),
                "gap_end": iso(r["gap_end"]), "gap_seconds": r["gap_seconds"],
                "before_line_id": r["before_line_id"], "after_line_id": r["after_line_id"],
                "after_row_hash": r["after_row_hash"],
                "after_raw_line": r["after_raw_line"][:200]} for r in rows]
        return ToolResult(tool="find_gaps", rows=out, total_matches=len(out),
                          summary={"min_gap_seconds": min_gap_seconds})

    # ---------------- 下钻型 ---------------- #
    def t_search_logs(self, query: str, mode: str = "keyword", components: list[str] | None = None,
                      min_level: str | None = None, time_from: str | None = None,
                      time_to: str | None = None, min_ts_confidence: float = 0.0,
                      dedup: str = "none", limit: int = 50, cursor: str | None = None,
                      order: str = "auto") -> ToolResult:
        notes: list[str] = []
        req = int(limit)
        limit, note = self.guard.clamp_limit(req, "search_logs")
        if note:
            notes.append(note)
        limit = min(limit, 500)
        where, params = self._where(components=components, min_level=min_level,
                                    time_from=time_from, time_to=time_to,
                                    min_ts_confidence=min_ts_confidence)
        if dedup == "first_only":
            where += " AND dup_rank = 0"
        after = int(cursor) if cursor and str(cursor).isdigit() else -1
        if after >= 0:
            where += f" AND line_id > {after}"

        mcond, mparams = self._match_condition(query, mode)
        params.update(mparams)
        if mcond is None:
            return ToolResult(tool="search_logs", ok=False, error="检索模式不支持或正则非法")

        total = self._q(f"SELECT count(*) AS n FROM log_lines WHERE {where} AND {mcond}", params)[0]["n"]
        # order=auto：放得下就按时间序；放不下就按严重级别优先。
        # 否则一个按时间截断的窗口会把靠后的 ERROR 行整段丢掉——这正是漏诊的常见成因。
        truncating = total > limit
        use_sev = (order == "severity") or (order == "auto" and truncating)
        order_sql = ("level_num DESC, ts_utc, source_rank, file_id, line_no" if use_sev
                     else "ts_utc, source_rank, file_id, line_no")
        cols = ", ".join(_SUMMARY_COLS)
        rows = self._q(f"""
            SELECT {cols}, substr(raw_line,1,220) AS preview
            FROM log_lines WHERE {where} AND {mcond}
            ORDER BY {order_sql} LIMIT {limit}
        """, params)
        if use_sev and truncating:
            notes.append(f"[GUARDRAIL] 命中 {total} 行超过本次返回上限 {limit}，"
                         f"已改为『严重级别优先』排序返回，时间序不完整；"
                         f"需要完整时间序请收窄时间窗或组件后重试。")
        out = [{**{k: (iso(r[k]) if k == "ts_utc" else r[k]) for k in _SUMMARY_COLS},
                "preview": r["preview"]} for r in rows]
        hint = self.guard.wide_result_hint(total, "search_logs")
        if hint:
            notes.append(hint)
        truncated = total > len(out)
        cur = str(out[-1]["line_id"]) if (truncated and out and not use_sev) else None
        return ToolResult(tool="search_logs", rows=out, total_matches=total,
                          rows_scanned=total, truncated=truncated, next_cursor=cur, notes=notes,
                          summary={"mode": mode, "query": query,
                                   "note": "返回的是摘要行；需要原文请用 get_lines(line_ids=[...])。"})

    def t_get_lines(self, line_ids: list[int] | None = None, row_hashes: list[str] | None = None,
                    include_raw: bool = True) -> ToolResult:
        notes: list[str] = []
        ids = list(line_ids or [])[:200]
        hashes = list(row_hashes or [])[:200]
        if not ids and not hashes:
            return ToolResult(tool="get_lines", ok=False, error="必须提供 line_ids 或 row_hashes")
        conds, params = [], {}
        if ids:
            conds.append("line_id IN (SELECT unnest($ids))")
            params["ids"] = ids
        if hashes:
            conds.append("row_hash IN (SELECT unnest($hs))")
            params["hs"] = hashes
        cols = ", ".join(_SUMMARY_COLS)
        rows = self._q(f"""
            SELECT {cols}, byte_offset, byte_len, line_span, raw_hash, norm_hash,
                   dup_rank, dup_count, parse_status, anomaly_flags, raw_line
            FROM log_lines WHERE ({' OR '.join(conds)})
            ORDER BY ts_utc, line_id
        """, params)
        out = []
        for r in rows:
            item = {k: (iso(r[k]) if k == "ts_utc" else r[k]) for k in _SUMMARY_COLS}
            item.update({"byte_offset": r["byte_offset"], "byte_len": r["byte_len"],
                         "line_span": r["line_span"], "raw_hash": r["raw_hash"],
                         "norm_hash": str(r["norm_hash"]), "dup_rank": r["dup_rank"],
                         "dup_count": r["dup_count"], "parse_status": r["parse_status"],
                         "anomaly_flags": list(r["anomaly_flags"] or [])})
            if include_raw:
                item["raw_line"] = wrap_log_content(r["raw_line"])
            out.append(item)
        missing = sorted(set(hashes) - {r["row_hash"] for r in rows})
        if missing:
            notes.append(f"[CITE] 以下 row_hash 在库中不存在（悬空引用）：{missing[:10]}")
        return ToolResult(tool="get_lines", rows=out, total_matches=len(out), notes=notes)

    def t_get_context(self, line_id: int | None = None, row_hash: str | None = None,
                      before: int = 10, after: int = 10, scope: str = "same_file") -> ToolResult:
        notes: list[str] = []
        b, a, note = self.guard.clamp_context(int(before), int(after))
        if note:
            notes.append(note)
        if line_id is None and row_hash:
            r = self._q("SELECT line_id FROM log_lines WHERE row_hash=$h LIMIT 1", {"h": row_hash})
            if not r:
                return ToolResult(tool="get_context", ok=False, error=f"row_hash 不存在: {row_hash}")
            line_id = r[0]["line_id"]
        anchor = self._q("SELECT file_id, line_no, file_path, component FROM log_lines "
                         "WHERE line_id=$i", {"i": int(line_id)})
        if not anchor:
            return ToolResult(tool="get_context", ok=False, error=f"line_id 不存在: {line_id}")
        an = anchor[0]
        if scope == "same_file":
            rows = self._q("""
                SELECT line_id, ts_utc, component, level_norm, row_hash, line_no, raw_line
                FROM log_lines WHERE file_id=$f AND line_no BETWEEN $lo AND $hi
                ORDER BY line_no
            """, {"f": an["file_id"], "lo": an["line_no"] - b, "hi": an["line_no"] + a})
        else:
            rows = self._q("""
                SELECT line_id, ts_utc, component, level_norm, row_hash, line_no, raw_line
                FROM log_lines WHERE line_id BETWEEN $lo AND $hi ORDER BY line_id
            """, {"lo": int(line_id) - b, "hi": int(line_id) + a})
        out = [{"line_id": r["line_id"], "ts_utc": iso(r["ts_utc"]), "component": r["component"],
                "level_norm": r["level_norm"], "row_hash": r["row_hash"], "line_no": r["line_no"],
                "raw_line": r["raw_line"][:400],
                "is_anchor": r["line_id"] == int(line_id)} for r in rows]
        return ToolResult(tool="get_context", rows=out, total_matches=len(out), notes=notes,
                          summary={"anchor_line_id": int(line_id), "file_path": an["file_path"],
                                   "component": an["component"], "before": b, "after": a})

    def t_error_code_lookup(self, code: str) -> ToolResult:
        key = code.strip().lower()
        if not key.startswith("0x"):
            key = "0x" + key
        norm = "0x" + key[2:].upper().zfill(2)
        info = self._nrc.get(norm) or self._nrc.get(key)
        rows = self._q("""SELECT count(*) AS n, min(ts_utc) AS lo, max(ts_utc) AS hi
                          FROM log_lines WHERE lower(raw_line) LIKE $p""",
                       {"p": f"%{key}%"})[0]
        return ToolResult(tool="error_code_lookup",
                          rows=[{"code": norm, **(info or {"name": "UNKNOWN", "hint": "未收录该码"})}],
                          total_matches=1,
                          summary={"occurrences_in_log": rows["n"], "first_seen": iso(rows["lo"]),
                                   "last_seen": iso(rows["hi"])})

    def t_build_evidence(self, claim: str, items: list[dict], include_context: int = 5) -> ToolResult:
        from vela.evidencepack.builder import EvidenceBuilder
        eb = EvidenceBuilder(self)
        pack = eb.build(claim=claim, items=items, include_context=include_context)
        return ToolResult(tool="build_evidence", rows=pack["items"],
                          total_matches=len(pack["items"]),
                          summary={"evidence_id": pack["evidence_id"],
                                   "merkle_root": pack["merkle_root"],
                                   "path": pack.get("_path")})

    def t_run_sql(self, sql: str, max_rows: int = 200) -> ToolResult:
        guard = SqlGuard(max_rows=min(int(max_rows), self.budget.sql_max_rows))
        safe = guard.check(sql)
        rows = self._q(safe)
        out = [{k: (iso(v) if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]
        return ToolResult(tool="run_sql", rows=out, total_matches=len(out),
                          summary={"executed_sql": safe})

    # ---------------- 内部 ---------------- #
    def _where(self, *, components: list[str] | None = None, min_level: str | None = None,
               time_from: str | None = None, time_to: str | None = None,
               min_ts_confidence: float = 0.0, ota_phase: str | None = None,
               ecu_id: str | None = None) -> tuple[str, dict]:
        conds = ["1=1"]
        params: dict[str, Any] = {}
        if components:
            conds.append("component IN (SELECT unnest($comps))")
            params["comps"] = list(components)
        if min_level:
            conds.append(f"level_num >= {int(_LEVELS.get(min_level.upper(), 0))}")
        if time_from:
            dt = parse_iso(time_from)
            if dt:
                conds.append("ts_utc >= $tf")
                params["tf"] = dt
        if time_to:
            dt = parse_iso(time_to)
            if dt:
                conds.append("ts_utc <= $tt")
                params["tt"] = dt
        if min_ts_confidence:
            conds.append(f"ts_confidence >= {float(min_ts_confidence)}")
        if ota_phase:
            conds.append("ota_phase = $ph")
            params["ph"] = ota_phase
        if ecu_id:
            conds.append("ecu_id = $ecu")
            params["ecu"] = ecu_id
        return " AND ".join(conds), params

    def _match_condition(self, query: str, mode: str) -> tuple[str | None, dict]:
        if mode == "regex":
            try:
                re.compile(query)
            except re.error:
                return None, {}
            return "regexp_matches(raw_line, $rx)", {"rx": query}
        if mode == "substring":
            return "lower(raw_line) LIKE $sub", {"sub": f"%{query.lower()}%"}
        # keyword：多词 OR 命中（对 msg_tokens 与 raw_line 双路），无 FTS 时语义不变
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        if not terms:
            return "1=1", {}
        ors, params = [], {}
        for i, t in enumerate(terms):
            params[f"k{i}"] = f"%{t.lower()}%"
            ors.append(f"(lower(msg_tokens) LIKE ${'k'}{i} OR lower(raw_line) LIKE ${'k'}{i})")
        return "(" + " OR ".join(ors) + ")", params

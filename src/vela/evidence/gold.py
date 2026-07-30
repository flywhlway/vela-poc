"""Stage-7 Gold 层构建：DuckDB 表、索引、FTS、物化视图、阶段前向填充。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa

from vela.evidence.models import (CLOCK_ANCHORS_SCHEMA, FILES_SCHEMA, PARSE_ERRORS_SCHEMA,
                                  RUNS_SCHEMA, TEMPLATES_SCHEMA)


def _table_from(schema: pa.Schema, rows: list[dict]) -> pa.Table:
    cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
    return pa.Table.from_arrays([pa.array(cols[f.name], type=f.type) for f in schema], schema=schema)


def build(con, silver_dir: Path, *, entries: list, templates: list[dict],
          template_seen: dict, parse_errors: list[dict], run_meta: dict,
          storm_threshold: int = 100, build_fts: bool = True) -> None:
    glob = str(Path(silver_dir) / "**" / "*.parquet")

    # ---- 主表 ----
    con.execute("DROP TABLE IF EXISTS log_lines")
    con.execute(
        "CREATE TABLE log_lines AS SELECT * FROM read_parquet($g, hive_partitioning=true)",
        {"g": glob})

    # ---- dup_count 回填（行级重复：绝不删行，只标注）----
    con.execute("""
        UPDATE log_lines SET dup_count = c.n
        FROM (SELECT norm_hash, count(*) AS n FROM log_lines GROUP BY norm_hash) c
        WHERE log_lines.norm_hash = c.norm_hash
    """)

    # ---- OTA 阶段前向填充（技术方案 §14.2）----
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _phase_filled AS
        SELECT line_id,
               last_value(ota_phase IGNORE NULLS) OVER (
                   ORDER BY line_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS phase
        FROM log_lines
    """)
    con.execute("""
        UPDATE log_lines SET ota_phase = f.phase
        FROM _phase_filled f
        WHERE log_lines.line_id = f.line_id AND log_lines.ota_phase IS NULL
    """)

    # ---- 日志风暴标记（同模板 1 秒内频次超阈值）----
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _storm AS
        SELECT template_id, date_trunc('second', ts_utc) AS sec, count(*) AS n
        FROM log_lines WHERE template_id IS NOT NULL AND ts_utc IS NOT NULL
        GROUP BY 1,2 HAVING count(*) >= {int(storm_threshold)}
    """)
    con.execute("""
        UPDATE log_lines SET anomaly_flags = list_distinct(list_append(anomaly_flags,'STORM'))
        FROM _storm s
        WHERE log_lines.template_id = s.template_id
          AND date_trunc('second', log_lines.ts_utc) = s.sec
    """)

    # ---- 辅助表 ----
    files_rows = [{
        "file_id": e.file_id, "archive_path": run_meta.get("input_archive", ""),
        "rel_path": e.rel_path, "file_name": e.file_name, "file_sha256": e.file_sha256,
        "size_bytes": e.size_bytes, "mtime_utc": e.mtime_utc, "encoding": e.encoding,
        "encoding_conf": e.encoding_conf, "component": e.component, "parser_name": e.parser_hint,
        "line_count": e.line_count, "record_count": e.record_count,
        "ts_min": e.extra.get("ts_min"), "ts_max": e.extra.get("ts_max"),
        "is_rotated": e.is_rotated, "rotation_group": e.rotation_group,
        "rotation_index": e.rotation_index, "alias_of": e.alias_of, "is_binary": e.is_binary,
    } for e in entries]
    _register(con, "files", _table_from(FILES_SCHEMA, files_rows))

    tmpl_rows = []
    for t in templates:
        lo, hi = template_seen.get(t["template_id"], [None, None])
        tmpl_rows.append({**t, "template_hash": abs(hash(t["template_text"])) % (2 ** 63),
                          "first_seen_utc": lo, "last_seen_utc": hi})
    _register(con, "templates", _table_from(TEMPLATES_SCHEMA, tmpl_rows))
    _register(con, "parse_errors", _table_from(PARSE_ERRORS_SCHEMA, parse_errors))
    _register(con, "clock_anchors", _table_from(CLOCK_ANCHORS_SCHEMA, []))
    _register(con, "runs", _table_from(RUNS_SCHEMA, [run_meta]))

    # ---- 索引（DuckDB ART：等值/范围过滤加速）----
    for col in ("ts_utc", "component", "level_num", "template_id", "row_hash", "ota_phase", "ecu_id"):
        try:
            con.execute(f"CREATE INDEX IF NOT EXISTS idx_ll_{col} ON log_lines({col})")
        except Exception:                                # pragma: no cover - 某些列类型不支持
            pass

    # ---- 物化视图 ----
    con.execute("""
        CREATE OR REPLACE VIEW v_errors AS
        SELECT * FROM log_lines WHERE level_num >= 40
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW v_storm_windows AS
        SELECT template_id, date_trunc('second', ts_utc) AS sec, count(*) AS n,
               any_value(component) AS component
        FROM log_lines WHERE template_id IS NOT NULL
        GROUP BY 1,2 HAVING count(*) >= {int(storm_threshold)} ORDER BY n DESC
    """)
    con.execute("""
        CREATE OR REPLACE VIEW v_phase_spans AS
        SELECT ota_phase, min(ts_utc) AS started_at, max(ts_utc) AS ended_at,
               count(*) AS lines,
               sum(CASE WHEN level_num >= 40 THEN 1 ELSE 0 END) AS errors,
               epoch(max(ts_utc)) - epoch(min(ts_utc)) AS duration_s
        FROM log_lines WHERE ota_phase IS NOT NULL
        GROUP BY ota_phase
    """)
    con.execute("""
        CREATE OR REPLACE VIEW v_component_stats AS
        SELECT component, count(*) AS lines,
               sum(CASE WHEN level_num >= 40 THEN 1 ELSE 0 END) AS errors,
               min(ts_utc) AS ts_min, max(ts_utc) AS ts_max,
               avg(ts_confidence) AS avg_ts_conf
        FROM log_lines GROUP BY component
    """)

    # ---- 全文检索（可用则建，不可用则由查询层降级 LIKE/regex）----
    if build_fts:
        try:
            con.execute("INSTALL fts")
            con.execute("LOAD fts")
            con.execute("PRAGMA create_fts_index('log_lines','line_id','msg_tokens', overwrite=1)")
        except Exception:
            pass


def _register(con, name: str, table: pa.Table) -> None:
    con.register(f"_tmp_{name}", table)
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM _tmp_{name}")
    con.unregister(f"_tmp_{name}")


def has_fts(con) -> bool:
    try:
        con.execute("SELECT 1 FROM fts_main_log_lines.docs LIMIT 1").fetchone()
        return True
    except Exception:
        return False

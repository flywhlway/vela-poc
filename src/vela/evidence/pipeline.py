"""证据平面编排：Stage-0 ~ Stage-8 一次跑通，产出可查询的 Gold 库。"""
from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vela.config import config_hash, load_pipeline, load_yaml, tenant_id
from vela.evidence import discover, gold, qa, reader, writer
from vela.evidence.fingerprint import DupTracker, fingerprints, tokenize_for_search
from vela.evidence.models import (ANOMALY_CLOCK_JUMP, ANOMALY_DECODE_ERROR, ANOMALY_GIANT_LINE,
                                  ANOMALY_MULTILINE, ANOMALY_OUT_OF_ORDER, PARSE_ENCODING_ERROR,
                                  PARSE_OK, PARSE_TRUNCATED, PARSE_UNPARSED, empty_row)
from vela.evidence.parsers import ParserRegistry, extract_business
from vela.evidence.template import MiniDrain
from vela.evidence.timeline import TimestampNormalizer
from vela.evidence.unpack import extract
from vela.util.ids import new_run_id
from vela.util.jsonl import read_json, write_json
from vela.util.textutil import mask_vin
from vela.version import PIPELINE_VERSION, SCHEMA_VERSION

UTC = timezone.utc

_LEVEL_HINT = [
    (re.compile(r"\b(fatal|panic|corrupt)\b|严重", re.I), "FATAL", 50),
    (re.compile(r"\b(error|fail|failed|failure|exception|abort|denied|invalid|"
                r"unreachable|enospc|nrc)\b|错误|失败|异常|中止", re.I), "ERROR", 40),
    (re.compile(r"\b(warn|warning|timeout|retry|degraded|below threshold|pending)\b|警告|超时", re.I), "WARN", 30),
]


@dataclass
class BuildResult:
    run_id: str
    workspace: Path
    gold_db: Path
    total_files: int
    total_records: int
    unparsed_records: int
    elapsed_s: float
    qa_report: Path          # qa_report.json —— 供程序化解析（checks 列表等结构化字段）
    qa_report_md: Path       # qa_report.md    —— 同目录下的人读版本
    manifest: Path
    stats: dict = field(default_factory=dict)


def _infer_level(level_norm: str, message: str) -> tuple[str, int]:
    if level_norm != "UNKNOWN":
        return level_norm, 0
    for rx, lv, num in _LEVEL_HINT:
        if rx.search(message or ""):
            return lv, num
    return "INFO", 25


def _phase_matchers() -> list[tuple[str, list[re.Pattern]]]:
    cfg = load_yaml("ota_phases.yaml")
    return [(r["phase"], [re.compile(p, re.I) for p in r["any_of"]])
            for r in cfg["ota_phase_rules"]]


def build(archive: str | Path, workspace: str | Path, *, run_id: str | None = None,
          keep_raw: bool | None = None, progress: bool = True) -> BuildResult:
    t0 = time.time()
    archive = Path(archive)
    ws = Path(workspace)
    cfg = load_pipeline()
    run_id = run_id or new_run_id(f"{archive.name}:{archive.stat().st_size}")
    keep_raw = cfg.get("unpack.keep_raw", True) if keep_raw is None else keep_raw

    for sub in ("bronze", "silver", "gold", "qa", "evidence"):
        (ws / sub).mkdir(parents=True, exist_ok=True)
    raw_dir = ws / "raw" / run_id[:12]
    if raw_dir.exists():
        shutil.rmtree(raw_dir)

    # ---------------- Stage-0 安全解包 ----------------
    up = extract(archive, raw_dir,
                 max_bytes=int(cfg.get("unpack.max_uncompressed_bytes", 20 << 30)),
                 max_files=int(cfg.get("unpack.max_files", 200000)),
                 max_depth=int(cfg.get("unpack.max_nesting_depth", 3)),
                 allow_symlinks=bool(cfg.get("unpack.allow_symlinks", False)))

    # 包元数据（真实上传包一般随包携带；缺失则全部走推断）
    meta_path = raw_dir / "package_meta.json"
    pkg_meta = read_json(meta_path) if meta_path.exists() else {}
    ref_time = None
    if pkg_meta.get("collected_at"):
        from vela.util.timeutil import parse_iso
        ref_time = parse_iso(pkg_meta["collected_at"])
    if ref_time is None:
        ref_time = datetime.fromtimestamp(archive.stat().st_mtime, UTC)
    local_tz = pkg_meta.get("timezone") or cfg.get("timeline.default_timezone", "Asia/Shanghai")
    vin = pkg_meta.get("vin")
    vin_masked = mask_vin(vin) if vin else None

    # ---------------- Stage-1 清单与探测 ----------------
    entries = discover.inventory(
        raw_dir, cfg.get("discover.component_rules", []),
        encoding_candidates=cfg.get("discover.encoding_candidates", ["utf-8", "gb18030"]),
        sample_bytes=int(cfg.get("discover.encoding_sample_bytes", 65536)),
        binary_ratio_threshold=float(cfg.get("discover.binary_ratio_threshold", 0.30)),
        exclude_patterns=cfg.get("discover.exclude_patterns", []))
    todo = discover.parse_order(entries)

    # ---------------- Stage-2..5 逐文件解析 ----------------
    registry = ParserRegistry()
    miner = MiniDrain(sim_threshold=float(cfg.get("template.sim_threshold", 0.4)),
                      max_depth=int(cfg.get("template.max_depth", 4)),
                      max_children=int(cfg.get("template.max_children", 100)),
                      max_clusters=int(cfg.get("template.max_clusters", 5000)))
    dups = DupTracker()
    phases = _phase_matchers()
    agg = reader.MultilineAggregator(cfg.get("reader.multiline.continuation_patterns", []),
                                     int(cfg.get("reader.multiline.max_span_lines", 200)))
    sw = writer.ShardWriter(ws / "bronze", batch_rows=50_000,
                            compression=cfg.get("writer.compression", "zstd"))
    parse_errors: list[dict] = []
    templ_seen: dict[int, list] = {}
    unparsed = 0
    total_records = 0
    by_component: dict[str, int] = {}

    for e in todo:
        norm = TimestampNormalizer(
            local_tz=local_tz, reference_time=ref_time,
            year_inference=bool(cfg.get("timeline.year_inference", True)),
            clock_jump_threshold_ms=int(cfg.get("timeline.clock_jump_threshold_ms", 5000)))
        norm.reset_file(boot_id=f"boot-{e.component}")
        prev_epoch = 0
        prev_utc = None
        rec_n = 0
        line_n = 0
        ts_min = ts_max = None

        for rec in reader.iter_records(
                e.abs_path, e.encoding if not e.is_binary else "latin-1",
                max_line_bytes=int(cfg.get("reader.max_line_bytes", 262144)),
                aggregator=agg if cfg.get("reader.multiline.enabled", True) else None):
            line_n = max(line_n, rec.line_no + rec.line_span - 1)
            pr = registry.parse(rec.text)
            tr = norm.normalize(ts_raw=pr.ts_raw, ts_kind=pr.ts_kind, ts_format=pr.ts_format,
                                mono_s=pr.mono_s, file_mtime=e.mtime_utc)
            fp = fingerprints(rec.raw_bytes, rec.text, e.rel_path, rec.line_no)
            lvl, lvl_num = _infer_level(pr.level_norm, pr.message)
            if pr.level_norm != "UNKNOWN":
                lvl, lvl_num = pr.level_norm, pr.level_num
            tid_ = miner.add(pr.message or rec.text, e.component, lvl)
            biz = extract_business(rec.text)

            flags: list[str] = []
            status = pr.status
            if rec.decode_error:
                flags.append(ANOMALY_DECODE_ERROR)
                status = PARSE_ENCODING_ERROR
            if rec.truncated:
                flags.append(ANOMALY_GIANT_LINE)
                status = PARSE_TRUNCATED
            if rec.line_span > 1:
                flags.append(ANOMALY_MULTILINE)
            if norm.clock_epoch != prev_epoch:
                flags.append(ANOMALY_CLOCK_JUMP)
                prev_epoch = norm.clock_epoch
            gap_ms = None
            if tr.ts_utc and prev_utc:
                gap_ms = int((tr.ts_utc - prev_utc).total_seconds() * 1000)
                if gap_ms < 0:
                    flags.append(ANOMALY_OUT_OF_ORDER)
            if tr.ts_utc:
                prev_utc = tr.ts_utc
                ts_min = tr.ts_utc if ts_min is None or tr.ts_utc < ts_min else ts_min
                ts_max = tr.ts_utc if ts_max is None or tr.ts_utc > ts_max else ts_max

            phase = None
            for name, rxs in phases:
                if any(r.search(rec.text) for r in rxs):
                    phase = name
                    break

            row = empty_row()
            row.update({
                "run_id": run_id, "schema_version": SCHEMA_VERSION,
                "ts_utc": tr.ts_utc, "ts_local": tr.ts_local.replace(tzinfo=None) if tr.ts_local else None,
                "ts_raw": pr.ts_raw, "ts_kind": tr.ts_kind, "ts_confidence": tr.ts_confidence,
                "monotonic_ns": tr.monotonic_ns, "boot_id": norm.boot_id,
                "clock_epoch": norm.clock_epoch, "ts_gap_ms": gap_ms,
                "file_id": e.file_id, "file_path": e.rel_path, "line_no": rec.line_no,
                "byte_offset": rec.byte_offset, "byte_len": rec.byte_len,
                "line_span": rec.line_span, "source_rank": e.source_rank,
                "component": e.component, "process": pr.process, "pid": pr.pid, "tid": pr.tid,
                "logger": pr.logger, "src_loc": pr.src_loc,
                "level_raw": pr.level_raw, "level_norm": lvl,
                "level_num": lvl_num if lvl_num else registry.level_num.get(lvl, 0),
                "message": pr.message, "raw_line": rec.text,
                "msg_tokens": tokenize_for_search(pr.message or rec.text),
                "fields": sorted(pr.fields.items()),
                "raw_hash": fp["raw_hash"], "norm_hash": fp["norm_hash"], "row_hash": fp["row_hash"],
                "template_id": tid_, "dup_rank": dups.observe(fp["norm_hash"]),
                "ota_task_id": biz.get("ota_task_id") or pkg_meta.get("task_id"),
                "campaign_id": biz.get("campaign_id") or pkg_meta.get("campaign_id"),
                "ecu_id": biz.get("ecu_id"), "ota_phase": phase,
                "vin_masked": vin_masked,
                "parse_status": status, "parser_name": pr.parser_name,
                "parser_version": pr.parser_version, "encoding": e.encoding,
                "anomaly_flags": sorted(set(flags)),
                "dt": (tr.ts_utc or ref_time).strftime("%Y-%m-%d"),
            })
            sw.add(row)
            rec_n += 1
            total_records += 1
            by_component[e.component] = by_component.get(e.component, 0) + 1
            if status == PARSE_UNPARSED:
                unparsed += 1
                if len(parse_errors) < 5000:
                    parse_errors.append({"file_id": e.file_id, "line_no": rec.line_no,
                                         "byte_offset": rec.byte_offset,
                                         "reason": "NO_PARSER_MATCH",
                                         "raw_snippet": rec.text[:512]})
            if tid_ not in templ_seen:
                templ_seen[tid_] = [tr.ts_utc, tr.ts_utc]
            else:
                lo, hi = templ_seen[tid_]
                if tr.ts_utc:
                    templ_seen[tid_] = [min(lo or tr.ts_utc, tr.ts_utc), max(hi or tr.ts_utc, tr.ts_utc)]

        e.record_count = rec_n
        e.line_count = line_n
        e.extra["ts_min"] = ts_min
        e.extra["ts_max"] = ts_max
        if progress:
            print(f"    [parse] {e.rel_path:44s} {rec_n:>8d} rec  enc={e.encoding}")

    sw.close()

    # ---------------- Stage-6/7 Silver + Gold ----------------
    import duckdb
    gold_db = ws / "gold" / "analysis.duckdb"
    if gold_db.exists():
        gold_db.unlink()
    con = duckdb.connect(str(gold_db))
    try:
        con.execute("PRAGMA threads=2")
        silver_dir = ws / "silver" / "log_lines"
        n_silver = writer.build_silver(con, ws / "bronze", silver_dir,
                                       int(cfg.get("writer.row_group_size", 200000)))
        gold.build(con, silver_dir, entries=entries, templates=miner.summary(),
                   template_seen=templ_seen, parse_errors=parse_errors,
                   run_meta={
                       "run_id": run_id,
                       "started_at_utc": datetime.fromtimestamp(t0, UTC),
                       "finished_at_utc": datetime.now(UTC),
                       "pipeline_version": PIPELINE_VERSION, "schema_version": SCHEMA_VERSION,
                       "input_archive": archive.name, "input_sha256": up.archive_sha256,
                       "config_hash": config_hash(), "total_files": len(entries),
                       "total_bytes": up.total_bytes, "total_lines": sum(e.line_count for e in entries),
                       "total_records": total_records, "unparsed_records": unparsed,
                       "merkle_root": "", "tenant_id": tenant_id(),
                   },
                   storm_threshold=int(cfg.get("gold.storm_threshold_per_sec", 100)),
                   build_fts=bool(cfg.get("gold.build_fts", True)))
        qa_report, stats = qa.build_report(con, ws / "qa", cfg, pkg_meta)
        qa_report_md = qa_report.with_suffix(".md")
    finally:
        con.close()

    if not keep_raw:
        shutil.rmtree(raw_dir, ignore_errors=True)

    manifest = {
        "run_id": run_id, "pipeline_version": PIPELINE_VERSION, "schema_version": SCHEMA_VERSION,
        "config_hash": config_hash(), "tenant_id": tenant_id(),
        "input_archive": str(archive), "input_sha256": up.archive_sha256,
        "package_meta": pkg_meta, "local_tz": local_tz,
        "raw_dir": str(raw_dir) if keep_raw else None,
        "gold_db": str(gold_db), "silver_dir": str(ws / "silver" / "log_lines"),
        "total_files": len(entries), "total_records": total_records,
        "records_in_silver": n_silver, "unparsed_records": unparsed,
        "templates": len(miner.clusters), "by_component": dict(sorted(by_component.items())),
        "elapsed_s": round(time.time() - t0, 3),
        "qa": stats,
    }
    mpath = write_json(ws / "manifest.json", manifest)

    return BuildResult(run_id=run_id, workspace=ws, gold_db=gold_db, total_files=len(entries),
                       total_records=total_records, unparsed_records=unparsed,
                       elapsed_s=round(time.time() - t0, 3), qa_report=qa_report,
                       qa_report_md=qa_report_md,
                       manifest=mpath, stats=stats)

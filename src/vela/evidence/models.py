"""Arrow / Parquet Schema 定义（主表 log_lines 与全部辅助表）。

字段按功能域分组，共 53 列 = 技术方案 §5.1 的 42 列 + 交底书机制二的 row_hash
+ 统一两方案所需的少量派生列（sub_module / thread_name / session_id / trace_id 等）。

Schema 演进策略：additive-only + version gate（见 §5.4）。
"""
from __future__ import annotations

import pyarrow as pa

from vela.version import SCHEMA_VERSION

LOG_LINES_SCHEMA = pa.schema([
    # ---- 标识域 ----
    ("line_id", pa.int64()),
    ("run_id", pa.string()),
    ("schema_version", pa.uint16()),
    # ---- 时间域 ----
    ("ts_utc", pa.timestamp("us", tz="UTC")),
    ("ts_local", pa.timestamp("us")),
    ("ts_raw", pa.string()),
    ("ts_kind", pa.string()),
    ("ts_confidence", pa.float32()),
    ("monotonic_ns", pa.int64()),
    ("boot_id", pa.string()),
    ("clock_epoch", pa.int32()),
    ("ts_gap_ms", pa.int64()),
    # ---- 来源域（证据链根基）----
    ("file_id", pa.int32()),
    ("file_path", pa.string()),
    ("line_no", pa.int64()),
    ("byte_offset", pa.int64()),
    ("byte_len", pa.int32()),
    ("line_span", pa.int32()),
    ("source_rank", pa.uint16()),
    # ---- 组件与进程域 ----
    ("component", pa.string()),
    ("sub_module", pa.string()),
    ("process", pa.string()),
    ("pid", pa.int32()),
    ("tid", pa.int32()),
    ("thread_name", pa.string()),
    ("logger", pa.string()),
    ("src_loc", pa.string()),
    # ---- 级别与内容域 ----
    ("level_raw", pa.string()),
    ("level_norm", pa.string()),
    ("level_num", pa.uint8()),
    ("message", pa.string()),
    ("raw_line", pa.string()),
    ("msg_tokens", pa.string()),
    ("fields", pa.map_(pa.string(), pa.string())),
    # ---- 指纹与去重域 ----
    ("raw_hash", pa.string()),          # L1 BLAKE3-128 hex（存 hex 便于 SQL 直接比对）
    ("norm_hash", pa.uint64()),         # L2 xxh3-64
    ("row_hash", pa.string()),          # 交底书机制二：引用锚点 H(raw‖path‖line_no)
    ("template_id", pa.int32()),        # L3
    ("dup_rank", pa.int32()),
    ("dup_count", pa.int32()),
    # ---- 业务关联域 ----
    ("ota_task_id", pa.string()),
    ("campaign_id", pa.string()),
    ("ecu_id", pa.string()),
    ("ota_phase", pa.string()),
    ("session_id", pa.string()),
    ("trace_id", pa.string()),
    ("vin_masked", pa.string()),
    # ---- 质量域 ----
    ("parse_status", pa.string()),
    ("parser_name", pa.string()),
    ("parser_version", pa.string()),
    ("encoding", pa.string()),
    ("anomaly_flags", pa.list_(pa.string())),
    # ---- 分区列 ----
    ("dt", pa.string()),
])

COLUMN_COUNT = len(LOG_LINES_SCHEMA)

FILES_SCHEMA = pa.schema([
    ("file_id", pa.int32()), ("archive_path", pa.string()), ("rel_path", pa.string()),
    ("file_name", pa.string()), ("file_sha256", pa.string()), ("size_bytes", pa.int64()),
    ("mtime_utc", pa.timestamp("us", tz="UTC")), ("encoding", pa.string()),
    ("encoding_conf", pa.float32()), ("component", pa.string()), ("parser_name", pa.string()),
    ("line_count", pa.int64()), ("record_count", pa.int64()),
    ("ts_min", pa.timestamp("us", tz="UTC")), ("ts_max", pa.timestamp("us", tz="UTC")),
    ("is_rotated", pa.bool_()), ("rotation_group", pa.string()), ("rotation_index", pa.int32()),
    ("alias_of", pa.int32()), ("is_binary", pa.bool_()),
])

TEMPLATES_SCHEMA = pa.schema([
    ("template_id", pa.int32()), ("template_text", pa.string()), ("template_hash", pa.uint64()),
    ("param_count", pa.int32()), ("occurrences", pa.int64()),
    ("first_seen_utc", pa.timestamp("us", tz="UTC")), ("last_seen_utc", pa.timestamp("us", tz="UTC")),
    ("components", pa.list_(pa.string())), ("level_mode", pa.string()), ("is_error_like", pa.bool_()),
])

CLOCK_ANCHORS_SCHEMA = pa.schema([
    ("anchor_id", pa.int32()), ("boot_id", pa.string()), ("monotonic_ns", pa.int64()),
    ("wall_utc", pa.timestamp("us", tz="UTC")), ("source_file_id", pa.int32()),
    ("source_line_no", pa.int64()), ("method", pa.string()),
    ("residual_ms", pa.float64()), ("weight", pa.float64()),
])

PARSE_ERRORS_SCHEMA = pa.schema([
    ("file_id", pa.int32()), ("line_no", pa.int64()), ("byte_offset", pa.int64()),
    ("reason", pa.string()), ("raw_snippet", pa.string()),
])

RUNS_SCHEMA = pa.schema([
    ("run_id", pa.string()), ("started_at_utc", pa.timestamp("us", tz="UTC")),
    ("finished_at_utc", pa.timestamp("us", tz="UTC")), ("pipeline_version", pa.string()),
    ("schema_version", pa.int32()), ("input_archive", pa.string()), ("input_sha256", pa.string()),
    ("config_hash", pa.string()), ("total_files", pa.int32()), ("total_bytes", pa.int64()),
    ("total_lines", pa.int64()), ("total_records", pa.int64()), ("unparsed_records", pa.int64()),
    ("merkle_root", pa.string()), ("tenant_id", pa.string()),
])

# 异常标记枚举
ANOMALY_OUT_OF_ORDER = "OUT_OF_ORDER"
ANOMALY_CLOCK_JUMP = "CLOCK_JUMP"
ANOMALY_STORM = "STORM"
ANOMALY_GIANT_LINE = "GIANT_LINE"
ANOMALY_BINARY_GARBAGE = "BINARY_GARBAGE"
ANOMALY_DECODE_ERROR = "DECODE_ERROR"
ANOMALY_MULTILINE = "MULTILINE"

PARSE_OK, PARSE_PARTIAL, PARSE_UNPARSED, PARSE_TRUNCATED, PARSE_ENCODING_ERROR = (
    "OK", "PARTIAL", "UNPARSED", "TRUNCATED", "ENCODING_ERROR")


def empty_row() -> dict:
    """给出一行的默认值骨架，保证列齐全（缺列会导致 Parquet 写入报错）。"""
    return {
        "line_id": 0, "run_id": "", "schema_version": SCHEMA_VERSION,
        "ts_utc": None, "ts_local": None, "ts_raw": None, "ts_kind": "NONE",
        "ts_confidence": 0.0, "monotonic_ns": None, "boot_id": "boot-0",
        "clock_epoch": 0, "ts_gap_ms": None,
        "file_id": 0, "file_path": "", "line_no": 0, "byte_offset": 0, "byte_len": 0,
        "line_span": 1, "source_rank": 500,
        "component": "unknown", "sub_module": None, "process": None, "pid": None, "tid": None,
        "thread_name": None, "logger": None, "src_loc": None,
        "level_raw": None, "level_norm": "UNKNOWN", "level_num": 0,
        "message": None, "raw_line": "", "msg_tokens": None, "fields": [],
        "raw_hash": "", "norm_hash": 0, "row_hash": "", "template_id": None,
        "dup_rank": 0, "dup_count": 1,
        "ota_task_id": None, "campaign_id": None, "ecu_id": None, "ota_phase": None,
        "session_id": None, "trace_id": None, "vin_masked": None,
        "parse_status": PARSE_OK, "parser_name": "", "parser_version": "", "encoding": "utf-8",
        "anomaly_flags": [], "dt": "1970-01-01",
    }

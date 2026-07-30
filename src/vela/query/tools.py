"""工具契约（JSON Schema）—— 与技术方案 §10.2 一致，并补齐交底书机制四的鸟瞰/下钻分类。"""
from __future__ import annotations

BIRDSEYE = "birdseye"      # 鸟瞰型：先看分布
DRILLDOWN = "drilldown"    # 下钻型：再取明细

TOOL_SPECS: list[dict] = [
    {"name": "describe_dataset", "kind": BIRDSEYE,
     "description": "返回本次日志库的全局概览：时间范围、组件清单、行数、阶段分布、质量指标。任何分析的第一步。",
     "input_schema": {"type": "object", "properties": {}}},

    {"name": "timeline", "kind": BIRDSEYE,
     "description": "时间线聚合：按时间桶统计各组件/级别的日志量。用于快速定位『什么时候出问题』。",
     "input_schema": {"type": "object", "properties": {
         "bucket": {"enum": ["1s", "10s", "1m", "5m", "1h"], "default": "1m"},
         "time_from": {"type": "string"}, "time_to": {"type": "string"},
         "components": {"type": "array", "items": {"type": "string"}},
         "min_level": {"type": "string"}}}},

    {"name": "aggregate", "kind": BIRDSEYE,
     "description": "受控聚合：按白名单维度分组计数。维度限于 component/level_norm/template_id/ota_phase/ecu_id/parser_name/parse_status/logger/boot_id/ts_kind。",
     "input_schema": {"type": "object", "properties": {
         "group_by": {"type": "array", "items": {"enum": [
             "component", "level_norm", "template_id", "ota_phase", "ecu_id",
             "parser_name", "parse_status", "logger", "boot_id", "ts_kind"]}},
         "filters": {"type": "object"},
         "order_by": {"enum": ["count_desc", "count_asc", "first_seen"], "default": "count_desc"},
         "limit": {"type": "integer", "default": 50, "maximum": 500}},
         "required": ["group_by"]}},

    {"name": "top_templates", "kind": BIRDSEYE,
     "description": "返回频次最高/最罕见/仅错误级的日志模板。认知压缩的主力工具——根因常藏于低频模板。",
     "input_schema": {"type": "object", "properties": {
         "sort": {"enum": ["frequent", "rare", "error_only", "newest"], "default": "error_only"},
         "components": {"type": "array", "items": {"type": "string"}},
         "limit": {"type": "integer", "default": 30, "maximum": 200}}}},

    {"name": "phase_timeline", "kind": BIRDSEYE,
     "description": "OTA 阶段状态机时间线：各阶段何时开始/结束/停留多久/在哪个阶段中断。",
     "input_schema": {"type": "object", "properties": {"ecu_id": {"type": "string"}}}},

    {"name": "find_gaps", "kind": BIRDSEYE,
     "description": "找出日志静默区间（超过阈值没有输出）。用于定位挂起、超时、进程崩溃。",
     "input_schema": {"type": "object", "properties": {
         "min_gap_seconds": {"type": "number", "default": 30},
         "components": {"type": "array", "items": {"type": "string"}},
         "limit": {"type": "integer", "default": 30}}}},

    {"name": "search_logs", "kind": DRILLDOWN,
     "description": "在日志中检索。支持 keyword(BM25/词元) / substring / regex 三种模式。返回轻量摘要行，不含全文。",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "mode": {"enum": ["keyword", "substring", "regex"], "default": "keyword"},
         "components": {"type": "array", "items": {"type": "string"}},
         "min_level": {"enum": ["TRACE", "DEBUG", "INFO", "NOTICE", "WARN", "ERROR", "FATAL"]},
         "time_from": {"type": "string"}, "time_to": {"type": "string"},
         "min_ts_confidence": {"type": "number", "default": 0.0},
         "dedup": {"enum": ["none", "first_only"], "default": "none"},
         "limit": {"type": "integer", "default": 50, "maximum": 500},
         "cursor": {"type": "string"}},
         "required": ["query"]}},

    {"name": "get_lines", "kind": DRILLDOWN,
     "description": "按 line_id 或 row_hash 取完整原文。search_logs 之后的第二阶段。",
     "input_schema": {"type": "object", "properties": {
         "line_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 200},
         "row_hashes": {"type": "array", "items": {"type": "string"}, "maxItems": 200},
         "include_raw": {"type": "boolean", "default": True}}}},

    {"name": "get_context", "kind": DRILLDOWN,
     "description": "取某一行在其源文件中的上下文（前 N 行 / 后 M 行）。用于理解单条错误的来龙去脉。",
     "input_schema": {"type": "object", "properties": {
         "line_id": {"type": "integer"}, "row_hash": {"type": "string"},
         "before": {"type": "integer", "default": 10, "maximum": 100},
         "after": {"type": "integer", "default": 10, "maximum": 100},
         "scope": {"enum": ["same_file", "all_components"], "default": "same_file"}}}},

    {"name": "error_code_lookup", "kind": DRILLDOWN,
     "description": "查询 UDS 否定响应码（NRC）语义与排查提示。诊断领域先验知识。",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}},
                      "required": ["code"]}},

    {"name": "build_evidence", "kind": DRILLDOWN,
     "description": "把一组 line_id/row_hash 打包成可离线验证的证据包（含三级指纹、字节偏移、Merkle 根）。",
     "input_schema": {"type": "object", "properties": {
         "claim": {"type": "string"},
         "items": {"type": "array", "items": {"type": "object", "properties": {
             "line_id": {"type": "integer"}, "row_hash": {"type": "string"},
             "role": {"enum": ["TRIGGER", "CAUSE", "EFFECT", "CONTEXT", "COUNTER"]}}}},
         "include_context": {"type": "integer", "default": 5}},
         "required": ["claim", "items"]}},

    {"name": "run_sql", "kind": DRILLDOWN,
     "description": "【逃生舱】执行只读 SQL。仅在上述工具无法表达时使用。有 SELECT 白名单、表白名单、超时与行数上限。",
     "input_schema": {"type": "object", "properties": {
         "sql": {"type": "string"},
         "max_rows": {"type": "integer", "default": 200, "maximum": 2000}},
         "required": ["sql"]}},
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOL_SPECS}


def tool_names() -> list[str]:
    return [t["name"] for t in TOOL_SPECS]


def birdseye_tools() -> list[str]:
    return [t["name"] for t in TOOL_SPECS if t["kind"] == BIRDSEYE]


def drilldown_tools() -> list[str]:
    return [t["name"] for t in TOOL_SPECS if t["kind"] == DRILLDOWN]


def compact_catalog() -> str:
    """给规划模型看的紧凑工具目录（控制 prompt token 成本）。"""
    lines = ["鸟瞰型工具（先看分布）："]
    lines += [f"  - {t['name']}: {t['description'][:60]}" for t in TOOL_SPECS if t["kind"] == BIRDSEYE]
    lines.append("下钻型工具（再取明细）：")
    lines += [f"  - {t['name']}: {t['description'][:60]}" for t in TOOL_SPECS if t["kind"] == DRILLDOWN]
    return "\n".join(lines)

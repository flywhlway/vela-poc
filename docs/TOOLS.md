# Agent 工具契约（12 个）

统一实现：`src/vela/query/api.py::LogQueryAPI`。每个工具经 `LogQueryAPI.call(tool, **kwargs)`
统一入口调用（自动做租户校验 + 调用轨迹记录），返回统一的 `ToolResult`：

```python
@dataclass
class ToolResult:
    tool: str
    ok: bool = True
    rows: list[dict]
    summary: dict
    total_matches: int
    rows_scanned: int
    elapsed_ms: float
    truncated: bool
    next_cursor: str | None
    notes: list[str]        # 护栏告警 / 降级说明，会原样进入模型上下文（在环负反馈）
    error: str | None
```

规范定义（工具名/参数 JSON Schema/描述）在 `src/vela/query/tools.py::TOOL_SPECS`，
`compact_catalog()` 生成给规划模型看的精简目录（控制 prompt token 成本）。

---

## 鸟瞰型（6 个）—— 建立全局认知，不返回逐行明细

### `describe_dataset()`

全局概览：运行元数据、总行数、模板数、级别分布、时间基准类型分布、各阶段耗时、组件清单。
**任何分析的强制第一步**（`agent/graph.py` 的 `BIRDSEYE_PROBES` 每轮 1 都会先跑一遍）。

```bash
vela query --db workspace/demo/gold/analysis.duckdb --tool describe_dataset
```

### `timeline(bucket="1m", time_from=None, time_to=None, components=None, min_level=None)`

按时间桶统计日志量。`bucket` 可选 `1s/10s/30s/1m/5m/1h`。快速定位"什么时候开始不对劲"。

### `aggregate(group_by, filters=None, order_by="count_desc", limit=50)`

受控聚合，`group_by` 维度**白名单限制**为：`component/level_norm/template_id/ota_phase/
ecu_id/parser_name/parse_status/logger/boot_id/ts_kind`（防止对高基数列如 `raw_line` 分组
导致结果爆炸）。`filters` 支持 `components`/`min_level`/`time_from`/`time_to`/`ota_phase`/`ecu_id`。

```python
api.call("aggregate", group_by=["component", "level_norm"],
        filters={"min_level": "ERROR"}, limit=10)
```

### `top_templates(sort="error_only", components=None, limit=30)`

**认知压缩的主力工具**。`sort` 四选一：
- `error_only`（默认）：仅 `is_error_like=true` 且级别非 DEBUG/TRACE 的模板
  （level_mode 过滤是必要的——单靠文本启发式会把"NRC received..."这类高频 DEBUG 级
  模板误当作错误面貌，这是评测过程中发现并修复的真实问题）
- `rare`：出现次数升序——**根因常藏在这里**，与直觉的"看高频"相反
- `frequent`：出现次数降序
- `newest`：最近首现的模板

### `phase_timeline(ecu_id=None)`

OTA 阶段状态机时间线：各阶段起止时间、停留时长、错误数；`summary.abort_markers`
额外给出显式的"campaign aborted"标记行（若存在）。

### `find_gaps(min_gap_seconds=30, components=None, limit=30)`

找日志静默区间，按间隔降序排列。**慎用其结果作为故障信号**：编排层组件
（`campaign_client`/`ota_master`/`flash_agent`）天然是事件驱动、突发式打点，
健康会话里也会出现几十秒到几十分钟的正常静默；真正有意义的静默通常发生在
诊断/通信层组件（`uds_stack`/`diag_router`）——这是评测过程中发现并修复的
一处假阳性来源（详见 `agent/graph.py::_absorb_signals` 的注释）。

---

## 下钻型（6 个）—— 取具体行/明细

### `search_logs(query, mode="keyword", components=None, min_level=None, time_from=None, time_to=None, min_ts_confidence=0.0, dedup="none", limit=50, cursor=None, order="auto")`

- `mode`：`keyword`（FTS BM25 或降级为 LIKE）/ `substring`（大小写不敏感子串）/ `regex`
- 返回**轻量摘要行**（`line_id/ts_utc/component/level_norm/template_id/row_hash/...+preview`），
  不含全文——要全文用 `get_lines`
- `order="auto"`：结果放得下就按时间序返回；**放不下（命中数超过 limit）时自动改为
  严重级别优先排序**，避免"按时间截断导致靠后的 ERROR 行被整段丢弃"这一漏诊模式
  （评测过程中发现并修复；触发时 `notes` 会显式提示时间序不完整）
- 护栏：请求量超过 `detail_fetch_hard_limit` 会被强制截断（`notes` 提示）；
  命中数超过 `wide_result_warn_threshold` 会提示"建议先鸟瞰再下钻"

```python
api.call("search_logs", query="NRC", mode="substring", min_level="ERROR", limit=20)
```

### `get_lines(line_ids=None, row_hashes=None, include_raw=True)`

按 `line_id` 或 `row_hash` 精确取完整原文（`search_logs` 之后的第二阶段）。
若某个 `row_hash` 在库中不存在，`notes` 会显式标出"悬空引用"而不是静默忽略——
这是引用校验闭环在查询层的第一道防线。原文经 `wrap_log_content` 包裹分隔标记
防止提示注入。

### `get_context(line_id=None, row_hash=None, before=10, after=10, scope="same_file")`

取某一行的上下文窗口。`scope="same_file"` 按源文件行号取；`scope="all_components"`
按全局 `line_id` 取（跨组件按时间序）。超过 `context_lines_limit` 会等比缩减。

### `error_code_lookup(code)`

查 UDS 否定响应码语义字典（`config/ota_phases.yaml` 的 `uds_nrc`），同时报告该码在
本次日志中的出现次数与首末次时间。领域先验知识查询，不查列式库主表。

```python
api.call("error_code_lookup", code="0x72")
# -> {"name": "generalProgrammingFailure", "hint": "编程失败，多为 Flash 擦写错误/坏块/掉电"}
```

### `build_evidence(claim, items, include_context=5)`

把一组 `{line_id 或 row_hash, role}` 打包成证据包：`role` 取值
`TRIGGER/CAUSE/EFFECT/CONTEXT/COUNTER`。产出含三级指纹、字节偏移、Merkle 根的完整
证据包，落盘于数据库自身工作区的 `evidence/` 目录（与建库工作区绑定，不是诊断会话
的 `--workspace`——因为证据包引用的字节偏移只对那次建库的原始压缩包有意义）。
详见 `docs/MECHANISM_MAPPING.md` 的机制二。

### `run_sql(sql, max_rows=200)`

**逃生舱**，仅在上述 11 个工具无法表达查询意图时使用。`SqlGuard` 强制：
- 只允许 `SELECT`/`WITH`，拒绝 DDL/DML（`DROP`/`DELETE`/`UPDATE`/`INSERT`）
- 表名白名单（`log_lines/files/templates/runs/parse_errors/clock_anchors` + 4 个视图）
- 禁止危险函数（如 `read_parquet('/etc/passwd')` 这类任意文件读取）
- 拒绝多语句（分号分隔的注入尝试）
- 自动追加 `LIMIT`（若原 SQL 未带）

---

## 设计原则小结

1. **鸟瞰优先**：12 个工具里 6 个不返回逐行明细，逼迫 Agent 先建立分布认知再下钻，
   这是"预算感知"在查询层的第一道防线（比压缩机制更早生效）。
2. **一切护栏都回注模型上下文而非静默生效**：截断/降级/告警都写进 `notes`，
   让模型知道"我看到的不是全貌"，而不是在不知情的情况下自信地下结论。
3. **只读、沙箱化、租户强制**：`run_sql` 是唯一能绕开工具化封装的逃生舱，
   但依然在只读 SQL 沙箱内；`LogQueryAPI._check_tenant` 保证任何工具调用
   都不会跨租户泄漏数据（POC 单租户库场景下体现为"库归属不匹配即拒绝"）。

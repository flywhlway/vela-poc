# 列式取证库 Schema 说明

Gold 层（`workspace/*/gold/analysis.duckdb`）共 6 张表 + 4 个视图 + 1 个 FTS 索引。
全部 Schema 定义在 `src/vela/evidence/models.py`（Python `pyarrow.Schema`，供 Bronze/Silver
Parquet 写出与 DuckDB 建表共用同一份定义，避免两处描述漂移）。

---

## `log_lines`（核心表，53 列）

按 9 大域分组：

### 标识域（3 列）
| 列 | 类型 | 说明 |
|---|---|---|
| `line_id` | int64 | 全局稠密行号（Silver 层 `row_number()` 生成，`0`-based，见 `writer.py::SILVER_SQL`） |
| `run_id` | string | 本次建库的运行 ID（Crockford Base32，`util/ids.py::new_run_id`，同输入确定性生成） |
| `schema_version` | uint16 | Schema 版本号，随 `version.py::SCHEMA_VERSION` |

### 时间域（9 列）
| 列 | 类型 | 说明 |
|---|---|---|
| `ts_utc` | timestamp(UTC) | 归一化后的 UTC 时间；`ts_kind`≠WALL 时是反推/继承值 |
| `ts_local` | timestamp | 按车辆所在时区（`config/pipeline.yaml` 或 `package_meta.json`）本地化 |
| `ts_raw` | string | 原始时间戳字符串（未解析），供人工复核 |
| `ts_kind` | string | `WALL` \| `MONOTONIC` \| `BOOT_RELATIVE` \| `DERIVED` \| `NONE` |
| `ts_confidence` | float | 0~1，见 `evidence/timeline.py::compute_ts_confidence` |
| `monotonic_ns` | int64 | 单调时钟原始纳秒值（若该行是单调时间戳） |
| `boot_id` | string | 单调时钟所属的"这一次开机"标识（跨文件对齐用） |
| `clock_epoch` | int32 | 时钟跳变计数器（每检测到一次倒退跳变 +1） |
| `ts_gap_ms` | int64 | 与上一行的时间差（毫秒），用于风暴/静默检测 |

### 来源域（7 列）
`file_id` / `file_path` / `line_no` / `byte_offset` / `byte_len` / `line_span` / `source_rank`
—— `byte_offset`/`byte_len` 是 **L2 溯源验证**的锚点：从原始压缩包按这两个值精确切片字节，
重算 `raw_hash` 应与库中一致（见 `evidencepack/verifier.py::verify_l2`）。

### 组件/进程域（8 列）
`component` / `sub_module` / `process` / `pid` / `tid` / `thread_name` / `logger` / `src_loc`

### 级别/内容域（7 列）
`level_raw` / `level_norm`（TRACE~FATAL 七级）/ `level_num`（10~50 数值，供比较）/
`message` / `raw_line` / `msg_tokens`（FTS 分词结果）/ `fields`（kv 结构化字段，map 类型）

### 指纹/去重域（6 列）—— 机制二的核心
| 列 | 类型 | 说明 |
|---|---|---|
| `raw_hash` | string | 原始字节 BLAKE3-128（32 位十六进制），L2 验证比对目标 |
| `norm_hash` | uint64 | 规范化文本 xxh3-64，去重/聚类用（不同 VIN/耗时的同类行会得到同一个值） |
| `row_hash` | string | **引用锚点**：`H(原文‖文件路径‖行号)`，16 位十六进制，报告 `[[EV:xxx]]` 引用的就是它 |
| `template_id` | int32 | 所属 MiniDrain 模板 ID |
| `dup_rank` | int32 | 同 `norm_hash` 重复组内的序号（0 = 首次出现） |
| `dup_count` | int32 | 同 `norm_hash` 重复组的总次数 |

### 业务关联域（7 列）
`ota_task_id` / `campaign_id` / `ecu_id` / `ota_phase`（前向填充后）/ `session_id` /
`trace_id` / `vin_masked`（掩码后的 VIN，仅保留后 4 位 + 前缀哈希）

### 质量域（5 列）
`parse_status`（OK/UNPARSED/TRUNCATED/ENCODING_ERROR）/ `parser_name` / `parser_version` /
`encoding` / `anomaly_flags`（list，见下方"异常标记"）

### 分区列（1 列）
`dt`（`component`+`dt` 双键 Hive 分区，加速按日期/组件的下推过滤）

**异常标记枚举**（`anomaly_flags` 可能包含的值，定义于 `models.py`）：
`OUT_OF_ORDER`（乱序）/ `CLOCK_JUMP`（时钟跳变）/ `STORM`（日志风暴）/
`GIANT_LINE`（超长行截断）/ `BINARY_GARBAGE`/ `DECODE_ERROR`/ `MULTILINE`（多行合并记录）

---

## `files`（20 列）—— 每个源文件一行

`file_id` / `archive_path` / `rel_path` / `file_name` / `file_sha256`（**L2 验证的文件级锚点**）/
`size_bytes` / `mtime_utc` / `encoding` / `encoding_conf` / `component` / `parser_name` /
`line_count` / `record_count` / `ts_min` / `ts_max` / `is_rotated` / `rotation_group` /
`rotation_index` / `alias_of`（物理重复文件指向首现 `file_id`）/ `is_binary`

## `templates`（10 列）—— MiniDrain 模板聚类结果

`template_id` / `template_text`（含 `<*>` 通配符）/ `template_hash` / `param_count` /
`occurrences` / `first_seen_utc` / `last_seen_utc` / `components` / `level_mode` /
`is_error_like`（正则启发式：命中 fail/error/exception/超时/失败等词）

## `clock_anchors`（9 列）—— 强锚点（同行双时间戳）

`anchor_id` / `boot_id` / `monotonic_ns` / `wall_utc` / `source_file_id` / `source_line_no` /
`method` / `residual_ms`（拟合残差）/ `weight`（`_anchor_base` 选锚点时按此排序）

## `parse_errors`（5 列）—— 解析失败明细

`file_id` / `line_no` / `byte_offset` / `reason` / `raw_snippet`

## `runs`（15 列，通常只有一行）—— 本次建库的运行元数据

`run_id` / `started_at_utc` / `finished_at_utc` / `pipeline_version` / `schema_version` /
`input_archive` / `input_sha256` / **`config_hash`**（参数与规则集的联合指纹，跨 run 比较
可复现性的依据） / `total_files` / `total_bytes` / `total_lines` / `total_records` /
`unparsed_records` / `merkle_root` / `tenant_id`

---

## 4 个视图（`evidence/gold.py`）

| 视图 | 用途 |
|---|---|
| `v_errors` | 全部 ERROR/FATAL 级行，供快速鸟瞰 |
| `v_storm_windows` | 日志风暴窗口（`gold.storm_threshold_per_sec` 阈值以上） |
| `v_phase_spans` | 每个 OTA 阶段的起止时间与行数（`phase_timeline` 工具的底层查询） |
| `v_component_stats` | 按组件汇总的行数/错误数/时间置信度均值 |

## FTS 索引

对 `msg_tokens` 建 DuckDB `fts` 扩展索引（BM25 排序），支持中英混合关键词检索；
扩展加载失败时 `has_fts()` 返回 `False`，`search_logs(mode="keyword")` 自动降级为
`LIKE` 子串匹配（语义不变，只是召回排序退化）。

---

## 为什么是 53 列而不是更"干净"的设计

这是证据链系统的常见张力：**列越多，单行的"自解释性"越强**（不需要 join 就能回答
"这行是哪个文件第几字节、属于哪个模板、时间置信度多少"），代价是写入吞吐略降
（约 3,000 行/秒/核，见 `scripts/bench.py`）。POC 阶段选择"自解释优先"，因为这套系统
的核心价值就是"每一条结论都要能独立核验到具体字节"——少一列，就多一次 join，就多一个
"证据链在这一步断裂"的风险点。

# 机制映射表：两份原始文档 → 代码位置

本文档回答一个问题："交底书/技术方案里说的每一条机制，具体是哪个文件的哪个函数？"
供代码审查、面试问答、以及未来接手者快速定位实现。

---

## 一、技术方案《OTA车端日志预处理与列式取证库技术方案》

| 文档章节（原文档编号，供参照） | 机制 | 代码位置 | 验证方式 |
|---|---|---|---|
| 安全解包 | zip-slip 防护 / 符号链接拒绝 / 解压炸弹三重上限 / 嵌套包展开 | `evidence/unpack.py::extract` | `tests/test_evidence_pipeline.py::test_zip_slip_is_rejected` |
| 编码探测 | UTF-8/GB18030/UTF-16/Latin-1 多候选打分，确定性无外部依赖 | `evidence/discover.py::detect_encoding` | `test_detect_encoding_prefers_utf8_then_gb18030` |
| 组件归属 + 滚动组识别 | 路径前缀规则匹配 + `.N`/`.gz` 滚动切片识别 | `evidence/discover.py::_component_for` / `_rotation` | 仿真器 13 个 Sink 全部命中，见 `sim/emitters.py` |
| 42/53 列 Schema | `log_lines` 表：标识/时间/来源/组件/级别/指纹/业务关联/质量/分区 9 大域 | `evidence/models.py::LOG_LINES_SCHEMA` | `test_empty_row_matches_schema_exactly` |
| 三级指纹（L1/L2/L3） | `raw_hash`（原始字节 BLAKE3-128）/ `norm_hash`（规范化 xxh3-64）/ `row_hash`（引用锚点） | `evidence/fingerprint.py::fingerprints` + `util/hashing.py` | `test_row_hash_binds_path_and_line` / `test_norm_hash_ignores_volatile_params` |
| L2 规范化规则集 | 时间戳/UUID/HEX/PID/IP/纯数字 → 占位符，含"数字紧贴单位后缀"边界情形 | `util/textutil.py::CANON_RULES` | `canon-v2`（v1 曾漏掉 `231ms` 这类情形，已修复升版） |
| 时间戳六形态 + 锚点对齐 | ISO/斜杠/BSD/glog/uptime/无日期六种解析 + 强锚点（同行双戳）优先 | `evidence/timeline.py::TimestampNormalizer` | `test_ts_confidence_ranks_wall_above_monotonic` 等 6 例 |
| 时间置信度打分（§7.7） | WALL≈0.95 / MONO,BOOT≈0.80 / DERIVED≈0.60，缺时区/年份/精度扣分，时钟不单调再扣 | `evidence/timeline.py::compute_ts_confidence` | `test_ts_confidence_penalises_*` 3 例 |
| MiniDrain 模板挖掘 | 固定深度解析树 + 长度分桶 + 数字/HEX 归一 + 相似度阈值匹配，纯规则确定性 | `evidence/template.py::MiniDrain` | `test_minidrain_clusters_same_shape_lines` / `_summary_is_sorted_by_id` |
| DuckDB + Parquet 双层架构 | Bronze（原始批量）→ Silver（全局排序+稠密 line_id+Hive 分区）→ Gold（analysis.duckdb + 索引 + 视图 + FTS） | `evidence/writer.py` / `evidence/gold.py` | `test_build_produces_all_layers` |
| OTA 阶段识别 + 前向填充 | 9 条阶段正则规则；`last_value IGNORE NULLS` 窗口函数填充空档 | `evidence/pipeline.py::_phase_matchers` + `evidence/gold.py` | `test_ota_phase_is_forward_filled` |
| Agent 12 工具契约 | 鸟瞰 6 + 下钻 6，统一 `ToolResult`（rows/total_matches/elapsed_ms/truncated/notes） | `query/tools.py::TOOL_SPECS` + `query/api.py::LogQueryAPI` | `tests/test_query_api.py` 27 例，详见 `docs/TOOLS.md` |
| QA 报告七项校验 | 行数对账/未解析率/时间置信度占比/无缺失时间戳/模板已生成/line_id 稠密唯一/row_hash 完整 | `evidence/qa.py::build_report` | `test_qa_report_all_checks_pass` |

---

## 二、专利技术交底书《基于预算感知证据压缩与可追溯证据链…》

七大机制的代码落点：

### 机制一：预算感知证据压缩 + 压缩痕迹回馈闭环

分级保留（**与通用摘要"保高频丢低频"相反**——根因常在低频侧）：

```
N3 白名单封顶（错误语义词/ERROR级，每模板最多 whitelist_cap_per_template 条，超出保留首尾）
N2 稀有模板豁免（全库出现 ≤ rare_template_max_count 次，整体保留——根因常在此）
N1 模板配额（其余按模板每类保留 template_quota_lines 条，其余折叠为计数摘要）
   ↓ 仍超预算
滑窗摘要（按 slide_window_seconds 分块，块级统计替代明细，ERROR 级明细优先保留）
```

- 实现：`agent/compress.py::EvidenceCompressor.compress` / `_slide`
- **压缩痕迹**（告诉模型"哪些被折叠了、如何取回"）：`CompressionResult.trace`，含
  `folded`（每类折叠条目的模板/时间范围/样例）+ `notice`（取回指引）
- 双水位预算：轮次级 `round_evidence_tokens` / 会话级 `session_evidence_tokens`
  （= 轮次 × `session_evidence_multiplier`），见 `config.py::BudgetProfile`
- 测试：`tests/test_agent.py` 的 6 个 `test_compressor_*` / `test_slide_window_*`

### 机制二：row_hash 引用锚点 + 系统级引用校验 + 证据快照双源解析

- **row_hash 引用锚点**：`util/hashing.py::row_hash`（`H(原文‖路径‖行号)`），全库唯一
- **系统级引用校验（不信任模型自述）**：`agent/citations.py::verify_citations`——
  报告里每个 `[[EV:row_hash]]` 必须（1）语法合法（2）存在于本轮证据集（3）在库中可解析且指纹一致；
  三条任一不满足即为**悬空引用**，计入 `dangling_citation_rate` 质量闸门
- **幻觉自测开关**：`gateway/mock.py` 的 `inject_hallucinated_citations`，故意伪造不存在的
  row_hash 来验证校验器真的能抓住（`test_mock_verifier_flags_hallucinated_citation`）
- **证据快照双源解析**：`evidencepack/snapshot.py::resolve_citation`——留存期内优先实时查库
  （`source=live`），库中不可解析时回退归档快照并显式标注来源（`source=snapshot`），
  两者皆不可用则诚实返回 `UNRESOLVABLE`
- 测试：`tests/test_agent.py` 的 5 个 citation 用例 + `tests/test_evidencepack.py` 的 4 个 snapshot 用例

### 机制三：两段式检索 + 程序化历史规避

```
第一段（宽召回）：本地确定性哈希向量 ∪ 词面命中 —— 混合召回，取 Top-N
                （纯向量召回实测会漏掉词面高度相关但向量夹角不占优的技能，
                 见 agent/skills.py::retrieve 内的说明与修复记录）
第二段（精遴选）：紧凑表示（标题+触发条件+摘要+探针）交给模型择一
```

- **程序化历史规避（不是"提示模型别选"，是候选集里物理不存在）**：
  `agent/state.py::SessionState.excluded_skills` = 已用技能 ∪ 未产出新证据的技能，
  在 `agent/graph.py::node_plan` 里作为 `exclude=` 参数传给 `retrieve()`，
  模型在结构上不可能重复选中
- 兜底：即使模型硬是输出了一个已剔除的技能 ID，`node_plan` 会判定非法并转入
  "无可用假设"分支（`plan.illegal_skill` 事件 + 指标，评测要求恒为 0）
- 测试：`tests/test_agent.py::test_agent_never_reselects_used_skill_within_session`

### 机制四：鸟瞰-下钻工具护栏

- 工具分两类：`BIRDSEYE`（6 个，先看分布）/ `DRILLDOWN`（6 个，再取明细），
  见 `query/tools.py`
- 护栏三件套（`query/guard.py::Guardrail`）：
  - `clamp_limit`：单次明细拉取硬上限（超出强制截断 + 回注提示）
  - `clamp_context`：上下文行数上限（超出等比缩减）
  - `wide_result_hint`：命中数超过告警阈值时回注"建议先鸟瞰再下钻"的提示
- SQL 逃生舱沙箱（`query/guard.py::SqlGuard`）：只读 SELECT/WITH 白名单、禁止关键字与函数、
  表白名单、强制 LIMIT、拒绝多语句
- 租户强制谓词：`query/guard.py::tenant_predicate`，`LogQueryAPI._check_tenant` 在每次调用前校验
- 测试：`tests/test_query_api.py` 的 guardrail/SQL 沙箱共 8 例

### 机制五：时间基准推断与置信度传播

见上文技术方案表格的"时间戳六形态"与"时间置信度打分"两行——两份文档在这一机制上是同一套实现。
额外的置信度**传播**体现在：`agent/graph.py::_root_cause` 会检测证据链中是否存在
`ts_confidence < 0.6` 的项，若有则在 `root_cause["time_uncertainty"]` 标记，报告模板
（`gateway/mock.py::_report`）据此在结论中显式声明"时间不确定性"，而不是静默假装精确。

### 机制六：双层编排 + 分级事件双通道推送

- **双层编排**：`agent/graph.py::AgentGraph` 的七节点图
  `plan → retrieve → compress → verify → report`（+ `human_gate` / `unanswerable` 两个终止节点）
- **分级事件双通道**：`obs/events.py::EventBus`——`PROGRESS`（高频可丢，用于前端进度条）与
  `MILESTONE`/`ALERT`（低频不可丢，同步落盘 JSONL + fsync）；单调 `event_id` 支持断线重连续传
- **模型网关的统一出口**：`gateway/base.py::LLMGateway.chat`——脱敏→预算预检→降级链调用→计量→审计，
  是"全部大模型流量的唯一出口"这一要求的具体实现
- 测试：`tests/test_obs_and_config.py` 的 5 个 EventBus 用例

### 机制七：知识自增强闭环

- `agent/graph.py::node_distill` 在会话成功产出根因后调用 `distiller` 逻辑模型，
  把本次会话蒸馏为技能候选（`{id, title, trigger, summary, keywords, tools, root_cause_label}` +
  置信度 + 理由），写入 `workspace/knowledge/candidates.jsonl`（`status=pending_review`，
  即**候选**而非自动生效——知识入库仍需人工复核这一闭环的最后一环）
- 与技能库的关系：`config/skills/builtin.yaml` 是"已复核并生效"的技能；
  `candidates.jsonl` 是"待复核"的技能——生产化时把两者接一个复核工作流即可打通全环

---

## 三、两份文档共享的交叉机制

有两处两份文档各自单独描述、但在代码里是**同一个实现**，值得注意以避免重复造轮子：

1. **证据包（技术方案 §6.4）与 row_hash 引用锚点（交底书机制二）**——共用
   `evidencepack/builder.py::EvidenceBuilder`：`item_digest` 覆盖二者的引用需求，
   `merkle_root` 满足技术方案"离线批量验证"的诉求，`row_hash`/`raw_hash_b3_128` 满足
   交底书"逐条引用可核验"的诉求。
2. **时间置信度（两份文档均有描述）**——`evidence/timeline.py::compute_ts_confidence`
   是唯一实现，技术方案关注"打分规则"本身，交底书关注"打分结果如何影响推理层的置信度声明"，
   两者在 `agent/graph.py::_root_cause` 的 `time_uncertainty` 字段处汇合。

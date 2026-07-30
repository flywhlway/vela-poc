# 双驱动架构升级与跨域泛化实施方案

> 目标：实现诊断能力的**持续进化**与**跨域泛化**
> 架构主线：技能驱动 → **技能 + 证据双驱动**
> 运营主线：手工维护 → **自动化知识闭环**
> 基础：本方案以前三份文档的 P0/P1 条目为前置，不重复其内容

---

## 0. 执行摘要

### 0.1 两项升级不是并列关系，而是互为燃料的进化引擎

这是本方案的核心认识：

```
        ┌──────────────── 双驱动架构 ────────────────┐
        │  技能通道（先验假设） ──┐                    │
        │                        ├──► 仲裁器 ──► 分歧信号
        │  证据通道（数据假设） ──┘                    │
        └──────────────────────────┬─────────────────┘
                                   │ 分歧 = 知识缺口的精确定位
                                   ▼
        ┌──────────────── 知识闭环 ──────────────────┐
        │  分歧样本 → 候选合成 → 准入验证 → 技能入库  │
        └──────────────────────────┬─────────────────┘
                                   │ 技能覆盖率提升
                                   ▼
                          分歧率下降 → 进化收敛
```

**关键洞察**：单驱动架构下，「知识缺口」是不可观测的——技能库没覆盖的故障，系统会静默误判为近邻标签（已实测的 FM-1），没有任何信号提示"这里缺知识"。双驱动架构的真正价值不在于"多一条推理路径"，而在于**它把知识缺口变成了一个可测量、可定位、可自动采集的信号**。没有这个信号，知识闭环就没有燃料，只能依赖人工事后复盘。

因此两项升级必须一起做：**双驱动提供信号，闭环消费信号，闭环产出降低分歧率——这是一条自我强化的曲线，也是"持续进化"的技术定义。**

### 0.2 跨域泛化的量化结论：成本远低于直觉

实测代码耦合边界：

| 维度 | 数据 | 含义 |
|---|---|---|
| 领域无关代码 | **4,096 行**（util/evidence/query/evidencepack/gateway/obs） | 63% 完全可复用 |
| 含耦合代码 | 2,374 行（agent/sim/eval） | 其中 sim 为仿真器，生产不需要 |
| **真实结构耦合点** | **仅 56 处**，集中于 `query/api.py`(16)、`gold.py`(7)、`graph.py`(5) | 可精确改造 |
| Schema 领域专属列 | **3 / 53 列（5.7%）**：`ota_task_id`/`campaign_id`/`ota_phase` | 改造面极小 |
| **领域语义定义** | **`ota_phases.yaml` 仅 41 行**（9 阶段规则 + 15 NRC 条目） | 新域只需写一份同规模配置 |

**结论**：VELA 事实上已经是一个「领域无关的证据平台 + 薄领域适配层」的结构，只是这一点未被显式设计与命名。跨域泛化的工作不是重写平台，而是**把已经存在的隐式分层显式化**——把 41 行的 OTA 语义提升为「领域包」契约。

### 0.3 与前三份文档的关系

| 文档 | 定位 | 本方案如何依赖 |
|---|---|---|
| 技能知识库分析 | 诊断问题（闭集天花板） | 本方案的 L2 开放式根因 = 证据通道的输出形式 |
| 真实 LLM 归因 | 诊断问题（编排缺陷） | D1/D3/D4 必须先修，否则双通道也走不通 |
| 多专家联合评审 | 修正认知 + 改造清单 | **阶段 0 仪表校准是硬前置**；C-15 提取器框架是本方案的双重枢纽 |

**硬前置声明**：本方案的任何效果都无法在「零引用报告被判满分」（F-01）与「无方差基线」（F-02）的度量体系下被验证。**阶段 0 必须先完成。**

---

## 1. 双驱动架构设计

### 1.1 当前单驱动的信息流缺陷

```
signals ──► 技能召回 ──► 技能探针 ──► 证据 ──► verify(技能标签) ──► report(技能标签)
                                        ▲                              ▲
                                        └── 证据只能【确认】假设 ────────┘
                                            永远不能【生成】假设
```

代码层面的体现（已核实）：

- `_root_cause()` 的 `label` 只能来自 `sk.get("root_cause_label")`
- `decisive` 要求 `self.skills.label_of(skill_id) is not None`
- 证据池 `evidence_pool` 只被用于**填充报告的证据链**，从未被用于**推断根因是什么**

**这是一个信息论层面的浪费**：系统投入了大量工程（53 列 Schema、三级指纹、时间置信度、模板聚类）把日志变成了高度结构化的证据，却在推理阶段只用它做"是/否支撑"的二值判断。

### 1.2 证据驱动通道：四个证据原语

证据通道的任务是：**不依赖任何技能，仅从证据结构本身生成根因假设**。

设计四个领域无关的证据原语（每个都可由现有 12 个工具直接计算）：

#### P1 断点定位（Rupture Point）

过程在哪一步断裂——**这是最强的单一信号**。

```python
def primitive_rupture(api) -> dict:
    """定位过程断点：最后一个正常完成的阶段 → 第一个出现错误的阶段。

    领域无关性：只依赖"过程有阶段序列"这一假设，OTA/远程诊断/应用启动皆适用。
    """
    ph = api.call("process_timeline")          # 跨域后的通用名
    rows = ph.rows
    for i, r in enumerate(rows):
        if r["errors"] > 0:
            return {"rupture_phase": r["process_phase"],
                    "last_healthy_phase": rows[i-1]["process_phase"] if i else None,
                    "rupture_ts": r["started_at"],
                    "errors_at_rupture": r["errors"],
                    "phases_not_reached": [x["process_phase"] for x in rows[i+1:]]}
    return {"rupture_phase": None}
```

#### P2 错误簇拓扑（Error Cluster Topology）

哪些组件在报错、时序关系如何、谁是源头谁是连锁。

```python
def primitive_cluster(api, window_s: float = 5.0) -> dict:
    """错误簇拓扑：按时间窗聚类错误，识别首发组件与传播链。

    首发组件（first_reporter）通常最接近根因；
    大量组件在极短窗口内同时报错，通常是级联而非多重根因。
    """
    errs = api.call("search_logs", query="", min_level="ERROR",
                    order="severity", limit=200).rows
    clusters = _cluster_by_time(errs, window_s)
    return {"cluster_count": len(clusters),
            "primary_cluster": {
                "first_reporter": clusters[0][0]["component"] if clusters else None,
                "participants": _ordered_components(clusters[0]) if clusters else [],
                "span_ms": _span(clusters[0]) if clusters else 0,
                "is_cascade": len(_ordered_components(clusters[0])) >= 3 if clusters else False}}
```

#### P3 稀有性异常（Rarity Anomaly）

**根因藏在低频模板里**——这是本项目数据层已经验证的先验（`top_templates(sort="rare")` 的设计依据）。

```python
def primitive_rarity(api) -> dict:
    """稀有错误模板 = 根因高发区。与"高频模板是噪声"互为镜像。"""
    rare = api.call("top_templates", sort="rare", limit=30).rows
    return {"rare_error_templates": [
        {"template_id": r["template_id"], "text": r["template_text"],
         "occurrences": r["occurrences"], "components": r["components"]}
        for r in rare if r["is_error_like"] and r["occurrences"] <= 5]}
```

#### P4 因果时序（Temporal Precedence）

第一个异常与后续异常的先后关系，**受 `ts_confidence` 门控**。

```python
def primitive_precedence(api, min_conf: float = 0.6) -> dict:
    """时序先行关系。低置信度时间戳不得用于因果推断——只能给出相关性。

    这是"机制五名实相符"的落地点（前文档 F-06 指出 ts_confidence 从未真正把关）。
    """
    errs = api.call("search_logs", query="", min_level="WARN",
                    min_ts_confidence=min_conf, limit=100).rows
    if not errs:
        return {"causal_claim_allowed": False,
                "reason": "无足够时间置信度的证据，仅可作相关性陈述"}
    return {"causal_claim_allowed": True,
            "first_anomaly": _slim(errs[0]),
            "precedence_chain": [_slim(e) for e in errs[:8]],
            "min_confidence_in_chain": min(e["ts_confidence"] for e in errs[:8])}
```

#### 证据假设合成

```python
@dataclass
class EvidenceHypothesis:
    """证据侧假设：无技能标签，由证据结构直接推出。"""
    description: str                  # 自然语言因果叙述（由 reporter 模型基于四原语生成）
    rupture_phase: str | None
    culprit_component: str | None      # P2 的 first_reporter
    supporting_row_hashes: list[str]
    causal_claim_allowed: bool         # P4 门控：能否声称因果而非相关
    confidence: float                  # 由原语完备度加权
    primitives: dict                   # P1~P4 原始产出，供审计
    label_suggestion: str | None       # 形如 "novel:flash_erase_hal_error"
```

**关键设计**：证据通道**不消耗技能库**，因此在任何域、任何未知故障上都可运行。它产出的是「有结构、有证据、无标签」的假设——正是知识闭环最需要的输入形态。

### 1.3 仲裁器：双通道汇合

```python
def arbitrate(skill_hyp: dict | None, ev_hyp: EvidenceHypothesis) -> dict:
    """双通道仲裁。分歧本身是最有价值的输出。"""
```

| 象限 | 技能通道 | 证据通道 | 判定 | 置信度 | 知识闭环价值 |
|---|---|---|---|---|---|
| **Q1 双证** | 有假设 | 一致 | `confirmed` | 高 | 低（已知且正确） |
| **Q2 技能孤证** | 有假设 | 不支持/矛盾 | `suspected` + 并列两说 | 中低 | **高**（技能可能过拟合或标签定义有误） |
| **Q3 证据孤证** | 无假设 | 有假设 | `novel` | 中 | **最高**（知识缺口精确定位） |
| **Q4 双缺** | 无 | 无 | `insufficient` | — | 中（可能是采集缺失，需查覆盖） |

一致性判定（避免落入"字符串比对"的老陷阱，前文档 D3 教训）：

```python
def _agree(skill_hyp: dict, ev_hyp: EvidenceHypothesis) -> tuple[bool, list[str]]:
    """结构化一致性判定：比对断点阶段、责任组件、证据交集，而非比对标签字符串。"""
    reasons = []
    phase_ok = skill_hyp.get("fail_phase") == ev_hyp.rupture_phase
    comp_ok = skill_hyp.get("culprit") == ev_hyp.culprit_component
    overlap = set(skill_hyp.get("row_hashes", [])) & set(ev_hyp.supporting_row_hashes)
    evid_ok = len(overlap) >= 2                     # 至少两条共同证据
    if not phase_ok: reasons.append(f"断点阶段不一致：技能={skill_hyp.get('fail_phase')} 证据={ev_hyp.rupture_phase}")
    if not comp_ok:  reasons.append(f"责任组件不一致：技能={skill_hyp.get('culprit')} 证据={ev_hyp.culprit_component}")
    if not evid_ok:  reasons.append(f"证据交集不足：仅 {len(overlap)} 条共同引用")
    return (phase_ok and evid_ok), reasons          # 组件不一致不否决，但降置信
```

**Q2 象限的价值需要特别说明**：它捕获的是「技能说是 A，但证据结构不支持 A」——这正是已实测的 FM-1（静默误诊）的形态。**在单驱动架构下 FM-1 完全不可检测；在双驱动下它成为一个显式告警。** 这是双驱动最直接的安全收益。

### 1.4 分歧率作为知识成熟度的度量

```
disagreement_rate = (Q2 + Q3) / 总会话数
novel_rate        = Q3 / 总会话数
overfit_rate      = Q2 / 总会话数
```

这三个指标构成**可观测的进化曲线**：

- 知识库幼年期：`novel_rate` 高（很多没覆盖）
- 知识库成长期：`novel_rate` 下降，`overfit_rate` 可能上升（技能开始互相干扰）
- 知识库成熟期：两者都低，`Q1` 占比高

**这是"持续进化"从口号变成可管理工程的关键**——没有这条曲线，知识库扩张就只能靠感觉判断"是不是够了"。

### 1.5 实施措施

| ID | 措施 | 文件 | 验收 | 前置 |
|---|---|---|---|---|
| **M-01** | 四个证据原语实现 | 新增 `agent/primitives.py` | 每个原语有独立单测 + 领域无关性检查 | — |
| **M-02** | `EvidenceHypothesis` 合成节点（新增第八节点 `evidence_reason`） | `graph.py` | 在零技能条件下能产出假设 | M-01 |
| **M-03** | 仲裁器 + 四象限判定 | 新增 `agent/arbiter.py` | 构造四象限用例各一，判定正确 | M-02 |
| **M-04** | P4 门控接入：低 `ts_confidence` 时因果降级为相关性 | `arbiter.py`, `prompts.py` | 机制五名实相符（补前文档 F-06） | M-01 |
| **M-05** | 分歧三指标入报表 | `eval/` | 报告输出 Q1~Q4 分布 | M-03, C-13 |
| **M-06** | Q2/Q3 样本自动落盘为知识候选 | `graph.py`, `knowledge/` | 分歧样本 100% 被采集 | M-03 |

**M-02 的预算影响需注意**：证据通道会增加 4 个工具调用 + 1 次模型调用。建议证据通道**仅在以下时机运行**（避免每轮都跑）：
1. 首轮（与鸟瞰探针合并，复用其中 3 个调用的结果）
2. 技能通道收敛前的最后一轮（做仲裁）
3. 技能通道判定 `unanswerable` 时（兜底）

---

## 2. 自动化知识闭环

### 2.1 闭环的五个输入源（不只是 Jira）

前文档只讨论了 Jira 挖掘与会话蒸馏两个来源。完整的闭环有五个：

| 源 | 产出 | 自动化程度 | 价值密度 |
|---|---|---|---|
| **S1 双通道分歧（Q2/Q3）** | 精确定位的知识缺口 + 现成证据 | 全自动采集 | ⭐⭐⭐⭐⭐ |
| **S2 未解释错误（L0 哨兵）** | 探针覆盖盲区 | 全自动采集 | ⭐⭐⭐⭐ |
| **S3 提取器未匹配** | 新日志形态 → 提取器补全 | 全自动采集 | ⭐⭐⭐⭐ |
| **S4 历史 Jira 工单** | 冷启动批量知识 | 半自动 | ⭐⭐⭐ |
| **S5 人工确认反馈** | 唯一的 ground truth | 需产品化 | ⭐⭐⭐⭐⭐ |

**S1 是本方案新增的最高价值源**：它不仅告诉你"这里缺知识"，还附带了完整的证据链、断点定位、责任组件——技能草案的大部分字段可以直接从中填充，人工只需确认标签与处置建议。

**S5 是闭环能否成立的命门**：没有人工确认的真实根因，系统永远不知道自己对不对，所有"进化"都是自说自话。这必须产品化——最小形态是报告页一个「结论是否正确 / 实际根因是什么」的反馈入口。

### 2.2 自动化程度分级：明确「人在环」的最小必要位置

**原则：可自动化验证的环节全自动，涉及价值判断的环节必须人工。**

| 环节 | 自动化 | 理由 |
|---|---|---|
| 分歧样本采集 | ✅ 全自动 | 纯机械记录 |
| 症状指纹提取 | ✅ 全自动 | 确定性计算（复用 §1.2 原语） |
| 聚类与去重 | ✅ 全自动 | 有客观相似度阈值 |
| 探针合成 | ✅ 全自动 + 自动验收 | 可用留出集召回率客观验证 |
| Schema/安全校验 | ✅ 全自动 | 规则明确 |
| 影响面分析（影子评测） | ✅ 全自动 | 回归可客观判定 |
| **标签命名** | ❌ **必须人工** | 涉及领域概念定义，错误会污染整个标签体系 |
| **处置建议** | ❌ **必须人工** | 错误建议直接误导工程师，代价最高 |
| **鉴别诊断规则** | ❌ **必须人工** | 需要领域因果知识，非数据可推 |

**这个分级本身就是一项设计决策**：不追求"全自动知识库"，而是**把人工投入压缩到不可替代的三个点上**。这三点的共同特征是「错误代价高且无法自动验证」。

### 2.3 边际收益递减与停止条件

知识库不能无限扩张。需要度量：

```
marginal_gain(n) = accuracy(n 个技能) - accuracy(n-1 个技能)
```

**实施方法**：每次新增技能进入 `active` 后，记录其**首次成为决定性技能的会话数**与**对整体准确率的贡献**（可用留一法近似：临时剔除该技能重跑评测集，准确率下降幅度即其边际贡献）。

停止/告警条件：
- 某技能连续 N 个月 `decisive_count = 0` → 候选退役（对应前文档的 `review_due` 机制）
- 新增技能的 `marginal_gain < 0.5pp` 且 `overfit_rate` 上升 → **知识库已接近饱和，应转向证据通道能力建设而非继续加技能**

**这一条防止了一个常见失败模式**：团队持续加技能，准确率不升反降（技能互相干扰），却因为没有边际收益度量而看不到拐点。

### 2.4 实施措施

| ID | 措施 | 验收 | 前置 |
|---|---|---|---|
| **M-07** | 五源统一采集管道 `knowledge/collect.py`，统一候选 Schema | 五源样本均可入池 | M-06, C-22 |
| **M-08** | 症状指纹复用证据原语，候选自动去重（Jaccard > 0.7） | 重复候选不入池（补前文档 F-19） | M-01 |
| **M-09** | 探针自动合成 + 留出集召回率自动验收（≥ 0.8） | 不达标自动退回，不进人工队列 | M-08 |
| **M-10** | 人工评审工作台 `vela knowledge review`：仅呈现三个必须人工的字段 | 单条候选评审 ≤ 3 分钟 | M-09, C-27 |
| **M-11** | 边际收益度量（留一法）+ 技能退役建议 | 输出每技能边际贡献排名 | C-12, C-28 |
| **M-12** | 结论反馈入口（S5）：报告页确认/纠正实际根因 | 生产准确率可观测 | — |

---

## 3. 跨域泛化

### 3.1 量化的耦合边界

已实测（见 §0.2）。关键结论：**领域语义总量仅 41 行 YAML**。

真实结构耦合点分布（56 处）：

| 位置 | 处数 | 耦合内容 | 改造方式 |
|---|---|---|---|
| `query/api.py` | 16 | `ota_phase` 列名、`phase_timeline` 工具、`uds_nrc` 字典 | 列名泛化 + 工具改名 + 字典配置化 |
| `evidence/gold.py` | 7 | 阶段前向填充 SQL、`v_phase_spans` 视图 | 列名泛化 |
| `agent/graph.py` | 5 | `fail_phase` 信号、`_SUGGEST` | 提取器配置化（C-15）+ 建议迁 YAML（C-32） |
| `evidence/pipeline.py` | 4 | `_phase_matchers` | 领域包驱动 |
| `evidence/models.py` | 3 | 3 个领域专属列 | 列名泛化 + 兼容视图 |
| 其余 | 21 | 分散（qa/parsers/builder/snapshot/config/cli/compress） | 逐点改造 |

### 3.2 「领域包」抽象设计

把 `ota_phases.yaml` 提升为标准契约 `config/domains/<domain>.yaml`：

```yaml
# config/domains/ota.yaml  —— 以现有 41 行为基础重构
domain:
  id: ota
  name: 整车 OTA 升级
  version: 1.0.0

# ---------- 过程模型（P1 断点定位依赖） ----------
process:
  id_columns: {process_id: ota_task_id, batch_id: campaign_id}   # 映射到通用列
  phases: [INIT, QUERY, DOWNLOAD, VERIFY, TRANSFER, FLASH, ACTIVATE, ROLLBACK, REPORT]
  phase_rules:                       # 原 ota_phase_rules，格式不变
    - {phase: DOWNLOAD, pattern: "download|chunk|cdn", priority: 10}
    ...
  terminal_markers:                  # 【新增】过程终止标记，多形态（补 F-04）
    - {kind: abort, pattern: "campaign aborted at (\\w+) phase reason=(\\w+)",
       captures: [phase, reason]}
    - {kind: abort, pattern: "OTA_ABORT: err=(0x[0-9A-Fa-f]+)", captures: [code]}
    - {kind: abort, pattern: "\\[FOTA\\] session terminated, cause: (\\w+)", captures: [reason]}
    - {kind: abort, pattern: "升级失败[：:]\\s*(.+)", captures: [reason_zh]}
    - {kind: success, pattern: "status=SUCCESS|升级成功"}
    - {kind: implicit_abort, rule: last_error_then_silence, silence_s: 120}  # 无显式中止行

# ---------- 错误码字典（error_code_lookup 工具依赖） ----------
code_dictionaries:
  uds_nrc:
    "0x72": {name: generalProgrammingFailure, hint: "编程失败，多为 Flash 擦写错误/坏块/掉电"}
    ...

# ---------- 组件拓扑（P2 错误簇拓扑依赖） ----------
component_roles:
  orchestration: [ota_master, campaign_client]      # 突发式打点，静默非故障
  communication: [uds_stack, diag_router]           # 应持续交互，静默即故障信号
  transport: [downloader, tbox_comm]
  execution: [flash_agent, verify]
  platform: [storage_svc, powerd, kernel]

# ---------- 领域技能与提取器 ----------
skills_dir: skills/ota/
extractors: extractors/ota.yaml
```

#### 第二个域示例：远程诊断（DTC 读取与清除）

```yaml
# config/domains/remote_diag.yaml
domain: {id: remote_diag, name: 远程诊断, version: 0.1.0}
process:
  id_columns: {process_id: diag_session_id, batch_id: diag_task_id}
  phases: [SESSION_OPEN, SECURITY_ACCESS, DTC_READ, FREEZE_FRAME, DTC_CLEAR, SESSION_CLOSE]
  phase_rules:
    - {phase: SECURITY_ACCESS, pattern: "0x27|securityAccess|seed|key", priority: 10}
    - {phase: DTC_READ, pattern: "0x19|readDTC|DTC count", priority: 10}
    - {phase: DTC_CLEAR, pattern: "0x14|clearDiagnosticInformation", priority: 10}
  terminal_markers:
    - {kind: abort, pattern: "session aborted.*nrc=(0x[0-9A-Fa-f]{2})", captures: [code]}
    - {kind: abort, pattern: "security access denied.*attempt=(\\d+)", captures: [attempts]}
code_dictionaries:
  uds_nrc: {$include: shared/uds_nrc.yaml}     # 【复用】与 OTA 共享 NRC 字典
component_roles:
  communication: [uds_stack, diag_router, tbox_comm]
  orchestration: [diag_master]
skills_dir: skills/remote_diag/
extractors: extractors/remote_diag.yaml
```

**注意 `$include` 的价值**：UDS NRC 字典在 OTA 与远程诊断两域完全共享。**领域包之间可以共享词典**，这大幅降低同协议族新域的成本。

#### 第三个域示例：车机应用异常（无阶段机的域）

```yaml
# config/domains/ivi_app.yaml
domain: {id: ivi_app, name: 车机应用异常, version: 0.1.0}
process:
  id_columns: {process_id: app_session_id}
  phases: []                                   # 【无阶段机】
  phase_model: none                            # 显式声明
  terminal_markers:
    - {kind: crash, pattern: "FATAL EXCEPTION|signal \\d+ \\(SIG\\w+\\)"}
    - {kind: anr,   pattern: "ANR in ([\\w.]+)", captures: [package]}
component_roles:
  application: [ivi_app, launcher, media_svc]
  platform: [kernel, surfaceflinger]
```

**这个例子暴露了一个重要边界**：无阶段机的域，**P1 断点定位原语不适用**。必须显式声明 `phase_model: none`，仲裁器据此跳过 P1，仅依赖 P2/P3/P4。这是诚实的能力边界，不应假装通用。

### 3.3 Schema 泛化与兼容迁移

3 列改造（5.7%）：

| 现列名 | 通用列名 | 迁移策略 |
|---|---|---|
| `ota_phase` | `process_phase` | 重命名 + 建兼容视图 `log_lines_ota`（含 `ota_phase AS process_phase` 别名） |
| `ota_task_id` | `process_id` | 同上 |
| `campaign_id` | `batch_id` | 同上 |

工具改名（保留旧名为别名，避免破坏已有技能配置）：

| 现工具 | 通用名 | 兼容 |
|---|---|---|
| `phase_timeline` | `process_timeline` | `TOOLS_BY_NAME` 同时注册两个名字，旧名标 deprecated |

**迁移风险**（必须与前文档 F-10 一并处理）：Schema 版本变更会改变 `config_hash`，历史证据包不可比。**建议与 C-11（config_hash 补齐）在同一次变更中完成**，一次性承担指纹断代成本，并记录版本映射表。

### 3.4 能力可迁移性的诚实边界

| 能力 | 可迁移性 | 说明 |
|---|---|---|
| 安全解包 / 编码探测 / 组件归属 | ✅ 完全 | 与领域无关 |
| 13 个解析器 / 三级指纹 / 规范化 | ✅ 完全 | 日志格式与领域正交（新域可能需补解析器，但框架不变） |
| 时间归一 / 时间置信度 | ✅ 完全 | 纯时间语义 |
| 模板挖掘（MiniDrain） | ✅ 完全 | 纯文本聚类 |
| 列式存储 / 索引 / FTS | ✅ 完全 | 仅 3 列需改名 |
| 证据包 / 三级验证 / Merkle | ✅ 完全 | 领域无关的可信性基础设施 |
| 引用校验 / 压缩 / 护栏 / 预算 | ✅ 完全 | 领域无关 |
| **证据原语 P2/P3/P4** | 🟡 需调参 | 时间窗、稀有阈值需按域校准 |
| **证据原语 P1（断点定位）** | 🟡 有条件 | 依赖阶段机，无阶段域不适用 |
| **阶段规则 / 终止标记** | ❌ 每域重写 | 领域包内容（约 20~40 行） |
| **错误码字典** | 🟡 同协议族可共享 | UDS 系可共享，应用层需新建 |
| **技能库** | ❌ 每域重建 | 但方法论（Schema v2/lint/闭环）完全复用 |
| **处置建议** | ❌ 每域重建 | 领域知识 |

**量化结论**：新域落地的增量工作 ≈ 领域包（40 行 YAML）+ 提取器配置（30 行）+ 初始技能 5~10 个 + 解析器补充（视日志格式）。**平台代码改动为零**（在完成 §3.3 泛化改造后）。

### 3.5 新域落地剧本（SOP）

| 步 | 动作 | 产出物 | 验收 |
|---|---|---|---|
| 1 | 采集 20~30 个真实故障日志包 + 人工标注根因 | 真实基准（该域） | 标注一致性 > 0.9 |
| 2 | 跑 `vela build`，检查 QA 报告 | 解析成功率报告 | 未解析率 < 5%；否则补 `parsers.yaml` |
| 3 | 编写领域包（阶段/终止标记/组件角色/码表） | `domains/<d>.yaml` | `vela domain lint` 通过 |
| 4 | **零技能基线测量**：仅证据通道跑全部用例 | 基线准确率 | 记录为 `zero_skill_accuracy` |
| 5 | 从 Q3(novel) 样本合成初始技能 5~10 个 | `skills/<d>/` | 经五道闸门 |
| 6 | 双通道评测 | 该域准确率 + 分歧分布 | 与成熟域对比算迁移衰减 |
| 7 | 进入知识闭环常态运营 | — | `novel_rate` 持续下降 |

**第 4 步是本剧本的关键创新**：**先测零技能基线，再加技能**。这个基线量化了「证据通道的独立能力」，也使第 6 步的迁移衰减可计算。它同时是一个诚实性检验——如果零技能基线接近加技能后的水平，说明该域的故障模式主要由证据结构就能判定，不需要重投技能；反之则说明该域强依赖领域先验。

### 3.6 迁移衰减：跨域能力的核心 KPI

```
transfer_decay = 1 - (新域零技能准确率 / 成熟域零技能准确率)
```

- `transfer_decay ≈ 0`：证据通道真正跨域，平台泛化能力强
- `transfer_decay > 0.5`：证据原语被 OTA 域隐式调优了，需要重新审视原语的领域无关性

**这个指标是对本方案自身的检验**——如果证据通道只在 OTA 上有效，那"跨域泛化"就是空话。建议在第二个域落地时**首先测量它**。

### 3.7 实施措施

| ID | 措施 | 验收 | 前置 |
|---|---|---|---|
| **M-13** | 领域包契约定义 + `ota.yaml` 重构 | 现有 10 场景行为不变（回归门） | C-15 |
| **M-14** | Schema 3 列泛化 + 兼容视图 + 工具改名（保留别名） | 全部 177 测试通过 | C-11 同批 |
| **M-15** | `_phase_matchers`/`gold.py` 前向填充改为领域包驱动 | 支持 `phase_model: none` | M-13 |
| **M-16** | 多形态终止标记（≥6 种，含 `implicit_abort`） | 真实日志识别率 ≥ 0.85 | M-13, C-16 |
| **M-17** | `vela domain lint` + `vela domain scaffold <id>`（新域脚手架） | 新域从零到可跑 < 1 天 | M-13 |
| **M-18** | 第二个域 PoC（建议远程诊断，可复用 UDS 字典）+ 迁移衰减测量 | 输出 `transfer_decay` 基线 | M-13~M-17, M-01 |

---

## 4. 进化度量体系

现有指标度量「当前有多准」，缺少度量「进化得多快」与「跨域能力如何」。

| 指标族 | 指标 | 定义 | 目标 | 用途 |
|---|---|---|---|---|
| **双驱动健康** | `q1_agreement_rate` | 双通道一致占比 | 上升趋势 | 知识成熟度 |
| | `overfit_rate` (Q2) | 技能有假设但证据不支持 | ≤ 0.10 | **捕获 FM-1 静默误诊** |
| | `novel_rate` (Q3) | 证据有假设但无技能 | 下降趋势 | 知识缺口规模 |
| | `insufficient_rate` (Q4) | 双通道皆无 | ≤ 0.10 | 采集覆盖问题 |
| **进化速度** | `novel_to_skill_days` | novel 发现 → 技能生效的中位天数 | ≤ 14 | 闭环效率 |
| | `novel_conversion_rate` | novel 样本转化为技能的比例 | ≥ 0.30 | 闭环产出率 |
| | `marginal_gain` | 每新增技能的准确率边际贡献 | 监控拐点 | 防止饱和后无效扩张 |
| **跨域能力** | `zero_skill_accuracy` | 零技能条件下的准确率（每域） | ≥ 0.40 | 证据通道独立能力 |
| | `transfer_decay` | 新域相对成熟域的衰减 | ≤ 0.30 | **跨域泛化核心 KPI** |
| | `domain_onboarding_days` | 新域从零到达标的天数 | ≤ 10 | 平台可扩展性 |
| **覆盖健康** | `unexplained_error_rate` | 未解释错误占比 | ≤ 0.05 | 承前文档 C-22 |
| | `unmatched_terminal_marker_rate` | 终止标记未匹配率 | ≤ 0.15 | 驱动提取器补全 |

**`zero_skill_accuracy` 是本方案最重要的新增指标**：它直接度量「不依赖知识库的诊断能力」，即架构从单驱动升级到双驱动的实际成效。当前系统的这一指标值为 **0**（无技能则结构性失效）。

---

## 5. 实施措施总表与优先级

### 依赖关系

```
【前置：前三份文档】
阶段0 仪表校准（C-01/02/11/12/13/14/28）
        │
阶段1 逻辑止血（C-03~C-10, C-22, C-23）
        │
C-15 可配置提取器框架 ★双重枢纽★
        ├──────────────────────────┐
        ▼                          ▼
【本方案 A 线：双驱动】      【本方案 B 线：跨域】
M-01 证据原语                M-13 领域包契约
M-02 证据推理节点            M-14 Schema 泛化
M-03 仲裁器                  M-15 阶段驱动改造
M-04 P4 时序门控             M-16 多形态终止标记
M-05 分歧指标                M-17 domain lint/scaffold
M-06 分歧样本采集            M-18 第二域 PoC + 迁移衰减
        └──────────┬───────────────┘
                   ▼
        【C 线：知识闭环】
        M-07 五源采集 → M-08 去重 → M-09 探针合成
        → M-10 评审工作台 → M-11 边际收益 → M-12 反馈入口
```

### 优先级判定

| 优先级 | 措施 | 理由 |
|---|---|---|
| **P0**（与前文档阶段 0/1 并行） | — | 本方案无 P0；仪表与逻辑缺陷优先 |
| **P1** | M-01, M-02, M-03, M-04, M-05, M-06 | 双驱动是架构主线，且 M-03 直接捕获 FM-1 |
| **P1** | M-13, M-14 | 与 C-11 同批完成，一次性承担指纹断代 |
| **P2** | M-07, M-08, M-09, M-12 | 闭环需先有分歧信号（M-06） |
| **P2** | M-15, M-16, M-17 | 跨域工程化 |
| **P3** | M-10, M-11, M-18 | 需运营数据积累 |

---

## 6. 分阶段路线图

### 第 I 期：双驱动最小闭环（3~4 周，依赖前文档阶段 0/1 完成）

M-01 → M-02 → M-03 → M-04 → M-05 → M-06

**验收**：
- `zero_skill_accuracy` 首次可测且 **≥ 0.40**（当前为 0）
- 消融实验中 FM-1（静默误诊）被 Q2 象限捕获，捕获率 ≥ 0.8
- Q1~Q4 分布进入评测报告
- 仿真基准回归门：已通过用例回归数 = 0

**这一期的核心价值**：把「技能库覆盖外结构性失效」变成「技能库覆盖外降级但仍可用」。

### 第 II 期：跨域基础设施（2~3 周，可与第 I 期部分并行）

M-13 → M-14（与 C-11 同批）→ M-15 → M-16 → M-17

**验收**：
- 现有 10 场景行为完全不变（回归门）
- 177 测试全通过
- `vela domain scaffold` 可生成新域骨架
- 真实日志终止标记识别率 ≥ 0.85

### 第 III 期：知识闭环运营化（3~4 周）

M-07 → M-08 → M-09 → M-12 →（M-10, M-11）

**验收**：
- 五源候选统一入池，去重生效
- 探针自动合成通过留出集验收（召回率 ≥ 0.8）
- 结论反馈入口上线，生产准确率可观测
- `novel_to_skill_days ≤ 14`

### 第 IV 期：跨域验证（3~4 周）

M-18：第二个域（远程诊断）落地

**验收**：
- `transfer_decay ≤ 0.30`
- `domain_onboarding_days ≤ 10`
- 该域真实基准准确率 ≥ 0.70（新域首期不设 80%）

---

## 7. 风险与边界

| ID | 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|---|
| **XR-1** | 证据通道产出大量低质量假设，Q3 泛滥为噪声 | 中 | 高 | 设最低证据门槛（≥2 组件 + ≥3 条错误证据）；`novel_rate` 超阈值告警 |
| **XR-2** | 双通道使 token 成本翻倍 | 高 | 中 | 证据通道仅在 3 个时机运行（见 §1.5）；复用鸟瞰探针结果 |
| **XR-3** | 证据原语被 OTA 隐式调优，跨域即失效 | 中 | 高 | M-18 首先测 `transfer_decay`；原语单测须含跨域用例 |
| **XR-4** | 仲裁一致性判定过严/过松 | 中 | 中 | 阈值先宽后紧；用四象限人工抽检校准 |
| **XR-5** | Schema 泛化破坏历史数据 | 中 | 高 | 兼容视图 + 与 C-11 同批一次性断代 + 版本映射表 |
| **XR-6** | 无阶段机的域（如 IVI）能力显著弱于 OTA | 高 | 中 | 显式声明 `phase_model: none`，**不承诺同等能力**；该域目标值单独设定 |
| **XR-7** | 人工评审成为闭环瓶颈 | 高 | 中 | M-10 把人工压缩到 3 个字段；候选按 `evidence_cases` 排序优先处理高价值 |
| **XR-8** | S5 反馈入口采纳率低，ground truth 不足 | 高 | 高 | 与工单系统集成而非独立入口；把反馈嵌入工程师既有工作流 |

### 明确的能力边界声明

1. **无阶段机的域，P1 原语不适用**，诊断能力弱于有明确过程模型的域——这是原理性限制，不是实现缺陷
2. **零技能准确率不会达到有技能水平**。证据通道的目标是「从结构性失效变为可用降级」，不是替代知识库
3. **跨域泛化指平台与方法论泛化，不指知识泛化**。每个新域仍需自建技能库与处置知识
4. **本方案不解决多根因/级联推理**（前文档决策 6 已延后），级联故障仍可能被判为其直接症状

---

## 8. 结语

补充结论指出的方向是准确的，本方案把它落到了可执行层面，并给出了两个关键的量化发现：

**第一，双驱动的核心价值被低估了。** 它通常被理解为"多一条推理路径提升准确率"。但从代码结构看，它更根本的价值是**把不可观测的知识缺口变成可测量的信号**——`overfit_rate`（Q2）直接捕获已实测的静默误诊 FM-1，`novel_rate`（Q3）精确定位知识缺口。在单驱动架构下，这两类问题都是完全不可见的。**双驱动首先是一套可观测性设施，其次才是推理能力增强。**

**第二，跨域泛化的成本远低于直觉。** 实测数据：53 列 Schema 中仅 3 列（5.7%）领域专属，领域语义定义仅 41 行 YAML，真实结构耦合仅 56 处。VELA 事实上**已经是**「领域无关证据平台 + 薄领域层」的结构，只是这个分层从未被显式设计与命名。跨域工作的本质是**把隐式分层显式化**，而不是重构平台。

两者结合形成的进化引擎有一条可观测曲线：`novel_rate` 下降代表知识在积累，`zero_skill_accuracy` 上升代表证据能力在增强，`transfer_decay` 下降代表平台在真正泛化。**这三条曲线就是"持续进化与跨域泛化"的工程化定义**——没有它们，进化只是修辞。

最后一点必须重申：本方案的一切效果都建立在度量可信的前提上。在「零引用报告被判满分」（F-01）与「无方差基线」（F-02）修复之前，双通道的分歧率、零技能准确率、迁移衰减——这些新指标同样会失真。**先让尺子变准，再谈进化速度。**

# VELA 技能知识库：依赖度剖析、泛化能力与知识治理演进方案

> 分析对象：`vela-poc` v1.0.0（61 个源文件 / 177 测试 / 12 内置技能）
> 分析方法：代码静态剖析 + **消融实验实测**（非推测）
> 文档定位：架构决策依据，面向后续生产化改造

---

## 0. 执行摘要

### 0.1 核心结论

**当前系统对 `config/skills/` 的依赖是「结构性总依赖」而非「增强性依赖」**——技能库不是让诊断"更好"的加分项，而是决定诊断"能否给出根因"的唯一开关。代码层面存在 4 个硬耦合点，其中最关键的一条：

```python
# src/vela/agent/graph.py:234-235
decisive = (bool(supported) and has_error_evidence and skill_id is not None
            and self.skills.label_of(skill_id) is not None)
```

**根因标签只能来自技能配置的 `root_cause_label` 字段**。技能库里没有的故障模式，系统在架构上不可能正确命名它。

### 0.2 消融实验：两个已实测的失效模式

对 S3（UDS NRC 0x72 刷写失败）逐步剔除技能，观察真实降级行为：

| 实验组 | 剔除技能 | 轮次 | 判定根因 | 悬空引用率 | 性质 |
|---|---|---|---|---|---|
| baseline | 无 | 1 | `uds_nrc_programming_failure` ✅ | 0.0 | 正确 |
| drop_correct | SK-UDS-NRC | 4 | `ecu_no_response` ❌ | 0.0 | **静默误诊** |
| drop_flash_family | +SK-POWER, SK-ECU-SILENT | 6 | `no_fault_found` ❌ | 0.0 | **假阴性** |

两个失效模式都**不会触发任何现有告警**——悬空引用率均为 0.0，引用校验全部通过，报告看起来完全可信。

**FM-1（静默误诊）**：剔除正确技能后，系统选中语义近邻的 `SK-ECU-SILENT`，输出权威口吻的错误处置建议——"检查目标 ECU 上下电时序与总线负载"。真实根因是 Flash 坏块（`erase sector failed at block 47, hal_status=-5`）。工程师会被导向完全错误的排查方向，且报告中每一条引用都真实可核验，反而强化了错误结论的可信度。

**FM-2（假阴性）**：剔除三个技能后，系统输出"未发现故障证据（本次升级日志无错误级事件）"。但库中**确实存在 5 条 ERROR 行**，包括显式的中止标记：

```
uds_stack   | TRANSFER | NRC received: sid=0x36 nrc=0x72 generalProgrammingFailure ecu=0x1A block=47
flash_agent | FLASH    | erase sector failed at block 47, hal_status=-5 retry exhausted
ota_master  | TRANSFER | ERROR flash session exception ecu=0x1A
ota_master  | FLASH    | ERROR campaign aborted at FLASH phase reason=UDS_NRC_0x72 ecu=0x1A
ota_master  | FLASH    | ERROR report result to tsp task=TASK-10069 status=FAILED fail_phase=FLASH
```

**根本原因**：`_root_cause` 的 `has_error` 判据检查的是 `st.evidence_pool`（探针实际取回的行），而非数据库全集。**系统的结论上界被"执行过的探针恰好检索到了什么"所界定，而不是"库里实际有什么"**。存活技能的探针没有覆盖到这 5 行，系统就"看不见"它们——即使其中一行明文写着 `campaign aborted ... reason=UDS_NRC_0x72`。

这是一个**廉价可修**的架构缺口：一次全局 `SELECT count(*) FROM log_lines WHERE level_num>=40` 的不变量检查即可捕获（详见 §3.3 L0）。

### 0.3 建议优先级

| 优先级 | 措施 | 解决问题 | 成本 |
|---|---|---|---|
| **P0** | 全局未解释错误哨兵（L0 不变量） | FM-2 假阴性 | 极低（~50 行） |
| **P0** | 根因置信度分级 + 近邻误判抑制 | FM-1 静默误诊 | 低（~150 行） |
| **P1** | 技能职责解耦（标签/探针/建议三分离） | 泛化能力天花板 | 中 |
| **P1** | 技能库三维分类与规模化治理 | 可维护性 | 低（加载器已支持） |
| **P2** | Jira 工单知识挖掘管线 | 冷启动知识规模 | 高 |
| **P2** | 知识准入五道闸门 + 影子评测 | 知识质量与投毒防护 | 中 |

---

## 1. 技能配置依赖度剖析

### 1.1 四个硬耦合点（代码级证据）

#### 耦合点 A：候选集入口——技能决定「能想到什么假设」

```python
# graph.py::node_plan
cands = self.skills.retrieve(_retrieval_query(st), top_n=8,
                             exclude=st.excluded_skills())
```

规划模型只能在 `retrieve()` 返回的候选中择一。技能库是**假设空间的物理边界**——不在库中的故障模式，模型在结构上无法提出。这不是"提示模型注意"，而是候选集里物理不存在（这本是机制三"程序化历史规避"的设计优点，但同时也构成了泛化的硬约束）。

#### 耦合点 B：探针即取证策略——技能决定「会去看哪些证据」

```python
actions = out.get("actions") or (self.skills.probes_of(sid) if sid else [])
```

12 个技能共定义 25 条探针，工具分布：`search_logs`×14 / `aggregate`×4 / `top_templates`×2 / `phase_timeline`×2 / `timeline`×2 / `find_gaps`×1。**探针参数是硬编码的固定查询**，这带来确定性与可复现的好处，但也意味着：技能选错 → 探针查错 → 证据池里就没有正确证据 → 后续所有推理都建立在错误的证据子集上。FM-2 正是这条链路的终点。

#### 耦合点 C：根因标签唯一来源——技能决定「能叫出什么名字」

```python
# graph.py:468-471, 492
label = sk.get("root_cause_label")
if not label:
    for s in reversed(st.used_skills):
        lab = self.skills.label_of(s)          # 仍然只在技能库里找
        ...
return {"label": label or "undetermined", ...}
```

`root_cause_label` 覆盖率 10/12（`SK-PHASE-OVERVIEW`、`SK-STORM` 是编排/辅助类技能，无标签）。**没有任何路径能产出技能库之外的标签**。所谓"根因识别"在当前实现下本质是**一个 10 类闭集分类器**，而不是开放域推理。

#### 耦合点 D：处置建议硬编码——技能标签决定「给什么建议」

```python
# graph.py:552  —— 独立于 YAML 的 Python 字典
_SUGGEST = {
    "download_cdn_timeout": [...],
    "signature_verify_fail": [...],
    ...
}
```

这是**比 YAML 更糟的耦合**：新增一个技能必须同时改 Python 源码，否则处置建议为空。它把"领域知识"泄漏到了代码层，违反了项目自身"业务代码不硬编码"的设计原则（`config/*.yaml` 承诺）。

### 1.2 依赖强度评级

| 维度 | 依赖强度 | 无技能时的行为 | 是否可降级 |
|---|---|---|---|
| 假设生成 | 🔴 总依赖 | 候选集为空 → 诚实停止 | 否 |
| 证据获取 | 🔴 总依赖 | 无探针 → 仅剩鸟瞰层证据 | 部分（鸟瞰探针是硬编码的） |
| 根因命名 | 🔴 总依赖 | `undetermined` / 错误近邻标签 | 否 |
| 处置建议 | 🟠 强依赖 | 空列表 + 兜底话术 | 是 |
| 引用校验 | 🟢 无依赖 | 正常工作 | — |
| 证据包/三级验证 | 🟢 无依赖 | 正常工作 | — |
| 压缩/预算/护栏 | 🟢 无依赖 | 正常工作 | — |

**值得肯定的部分**：证据链、引用校验、压缩、护栏这些"可信性基础设施"完全独立于技能库。这意味着**改造技能层不会动摇系统的可核验性根基**——这是一个良好的分层结果，为后续演进留出了安全空间。

### 1.3 症结：技能承担了四种本应分离的职责

当前一个 YAML 条目同时是：

1. **检索锚点**（`keywords` / `title` / `trigger` → 被召回）
2. **取证策略**（`probes` → 查什么）
3. **分类标签**（`root_cause_label` → 叫什么）
4. **处置知识**（隐式对应 `_SUGGEST` → 怎么办）

四者绑死带来的直接后果：**任何一个新故障模式都必须四件套齐备才能被系统处理**。而现实中这四类知识的成熟速度完全不同——工程师往往先知道"怎么查"（探针）和"现象长什么样"（症状），很久之后才对"这类问题该叫什么"（标签）形成共识，处置方案更是随供应商反馈持续演进。

**改造方向**：解耦为独立可组合的三层（详见 §3.2、§5.1）。

---

## 2. 技能库分类管理体系（问题 1）

### 2.1 现状与规模化瓶颈

```
config/skills/builtin.yaml   # 单文件，12 个技能，flat 列表
```

好消息：**加载器已经支持多文件**，无需任何代码改动即可拆分：

```python
# config.py:37-45
for p in sorted(d.glob("*.yaml")):        # 已经是 glob
    out.extend(data.get("skills", []))
return sorted(out, key=lambda s: s["id"])  # 按 id 稳定排序
```

坏消息：单文件在 30+ 技能时会出现——评审冲突（多人改同一文件）、无归属（谁负责这条）、无生命周期（哪条已废弃）、检索退化（关键词空间重叠严重）。

### 2.2 分类模型：一维目录 + 多维标签

**不建议**按 ECU / 应用模块 / 分析场景建三套平行目录——同一个技能天然跨维度（"BMS 电压过低导致刷写中止"同时属于 BMS-ECU、flash 模块、power 场景），三套目录必然产生软链或重复。

**建议**：**目录按「最稳定的归属维度」单维划分，其余维度用结构化标签表达**。

最稳定的维度是**分析场景（故障域）**——因为它随业务变化最慢：ECU 型号会换代、应用模块会重构，但"下载失败""刷写失败""激活回滚"这些故障域跨车型跨代际稳定存在。

```
config/skills/
├── _schema.yaml                    # 技能 Schema v2 定义（供 lint 校验）
├── _taxonomy.yaml                  # 受控词表：ECU/模块/场景/标签的合法取值
├── 00-orchestration/               # 编排类（无根因标签）
│   ├── phase-overview.yaml
│   └── log-storm.yaml
├── 10-transport/                   # 传输域：下载/网络/CDN
│   ├── download-timeout.yaml
│   └── network-link-flap.yaml
├── 20-integrity/                   # 完整性域：签名/依赖/版本
│   ├── signature-verify.yaml
│   └── dependency-mismatch.yaml
├── 30-flash/                       # 刷写域：UDS/擦写/时序
│   ├── uds-nrc.yaml
│   ├── ecu-silent.yaml
│   └── transfer-timing.yaml
├── 40-resource/                    # 资源域：存储/电源/内存
│   ├── storage-insufficient.yaml
│   └── power-voltage-drop.yaml
├── 50-activation/                  # 激活域：回滚/自检
│   └── activate-rollback.yaml
├── 60-timebase/                    # 时基域
│   └── clock-drift.yaml
└── 90-derived/                     # 自动蒸馏产出（灰度中，见 §6）
    └── candidates-2026Q3.yaml
```

目录前缀数字保证 `sorted(glob)` 的加载顺序稳定可预期（与现有排序逻辑兼容）。

### 2.3 技能 Schema v2

在现有 10 个字段（`id/version/title/trigger/summary/tags/keywords/tools/probes/root_cause_label`）基础上扩展：

```yaml
skills:
  - id: SK-FLASH-UDS-NRC
    version: 2.1.0                    # 语义化版本，变更需升版
    status: active                    # draft | shadow | active | deprecated
    title: UDS 否定响应码（NRC）根因分析
    trigger: FLASH/TRANSFER 阶段出现 UDS 否定响应
    summary: ...

    # ---------- 分类维度（受控词表，由 _taxonomy.yaml 约束） ----------
    domain: flash                     # 主域，与目录一致（单值，冗余存储便于校验）
    ecu_scope:                        # ECU 维度：适用范围
      ids: ["0x1A", "0x22", "0x28"]   # 具体 ECU（空 = 全部）
      roles: [flashable]              # 或按角色：flashable/gateway/sensor
      suppliers: []                   # 可按供应商收窄（同一 NRC 不同厂商语义有别）
    module_scope: [uds_stack, flash_agent, diag_router]   # 应用模块维度
    phase_scope: [TRANSFER, FLASH]    # OTA 阶段维度
    vehicle_scope:                    # 车型维度（平台差异大时收窄）
      platforms: []                   # 空 = 全平台
      exclude_models: []

    # ---------- 检索锚点 ----------
    keywords: [uds, nrc, "0x72", transferdata, 刷写, 否定响应]
    symptoms:                         # 【新增】结构化症状，泛化推理用（见 §5.2）
      - {signal: abort_reason, match: "UDS_NRC_*"}
      - {signal: error_template, match: "NRC received*nrc=0x7*"}
      - {signal: phase_stalled, match: FLASH}

    # ---------- 取证策略 ----------
    probes:
      - tool: search_logs
        args: {query: "NRC nrc=0x7", mode: substring, min_level: WARN, limit: 60}
      - tool: error_code_lookup
        args: {code: "0x72"}

    # ---------- 结论与处置（从 _SUGGEST 迁出，见 §2.5） ----------
    root_cause_label: uds_nrc_programming_failure
    confidence_policy:                # 【新增】何时才敢下这个结论
      require_error_evidence: true
      min_distinct_components: 2      # 至少两个组件的证据交叉印证
      require_signals: [abort_reason] # 缺失关键信号时降级为"疑似"
    remediation:                      # 【新增】处置建议，不再硬编码在 Python 里
      - 联系 ECU 供应商核查 Flash 擦写失败块（坏块/寿命）
      - 刷写前增加 Flash 健康自检与失败块重映射策略
    differential:                     # 【新增】鉴别诊断：易混淆项与区分点
      - label: power_voltage_drop
        distinguish: 检查同窗口 powerd 电压曲线；电压正常则排除
      - label: ecu_no_response
        distinguish: NRC 有响应即非静默；静默场景无 NRC 帧

    # ---------- 治理元数据 ----------
    owner: ota-diagnosis-team         # 责任团队
    source: manual                    # manual | jira_mined | session_distilled
    provenance:                       # 【新增】来源可追溯
      jira_issues: [OTA-1234, OTA-2871]
      sessions: []
    evidence_cases: 47                # 支撑该技能的历史案例数
    created_at: 2026-03-01
    reviewed_at: 2026-07-15
    review_due: 2027-01-15            # 到期未复核自动转 deprecated 候选
```

### 2.4 受控词表 `_taxonomy.yaml`

```yaml
domains: [orchestration, transport, integrity, flash, resource, activation, timebase]
ecu_roles: [flashable, gateway, sensor, actuator, hmi]
modules: [ota_master, campaign_client, downloader, uds_stack, flash_agent,
          diag_router, storage_svc, powerd, tbox_comm, ivi_app, kernel, verify]
phases: [INIT, QUERY, DOWNLOAD, VERIFY, TRANSFER, FLASH, ACTIVATE, ROLLBACK, REPORT]
root_cause_labels:                    # 标签是受控的——防止同义标签泛滥
  - {label: uds_nrc_programming_failure, domain: flash, aliases: [nrc_0x72_failure]}
  - {label: power_voltage_drop, domain: resource, aliases: [low_voltage_abort]}
  ...
```

**`root_cause_labels` 受控是关键**——否则自动蒸馏会很快制造出 `flash_fail` / `flash_failure` / `flash_error` 三个语义相同的标签，评测指标随即失去意义（Top-1 命中率会因标签分裂而虚假下降）。

### 2.5 配套代码改造（小而明确）

| 改动 | 文件 | 说明 |
|---|---|---|
| 处置建议迁出硬编码 | `graph.py::_SUGGEST` → 读 `skill["remediation"]` | 消除耦合点 D；保留 `_SUGGEST` 作为无技能时的兜底 |
| 新增技能 lint | `cli.py` 新增 `vela skills lint` | Schema 校验 + 词表校验 + ID 唯一性 + 探针工具名合法性 + 关键词冲突检测 |
| 新增技能检视 | `cli.py` 新增 `vela skills list --domain flash` | 按维度过滤查看，支持 `--status`、`--owner`、`--review-due` |
| 加载期校验 | `config.py::load_skills` | 重复 ID 报错（当前静默后者覆盖前者的风险）；status≠active 的技能默认不加载 |

**`vela skills lint` 的检查项（建议实现清单）**：

1. Schema 必填字段完整性
2. `id` 全局唯一、命名符合 `SK-<DOMAIN>-<NAME>` 规范
3. `domain` 与所在目录一致
4. `ecu_scope.ids` / `module_scope` / `phase_scope` 取值在词表内
5. `root_cause_label` 在受控标签表内
6. `probes[].tool` 是 12 个合法工具之一，`args` 通过对应工具的 JSON Schema 校验
7. **关键词冲突检测**：任意两个技能的 `keywords` 交集占比 > 60% 时告警（预示召回会混淆——这正是 FM-1 的诱因）
8. `status: active` 的技能必须有 `owner` 和未过期的 `reviewed_at`

### 2.6 规模化后的检索改造

当前混合召回（稠密哈希向量 ∪ 词面命中，`skills.py::retrieve`）在 12 技能规模下实测 100% 正确命中。但技能到 100+ 时会退化，改造顺序建议：

1. **先加维度预过滤**（成本最低、收益最直接）：用 `signals` 里已有的 `fail_phase` / `ecu_id` / 涉事组件，先按 `phase_scope`/`ecu_scope`/`module_scope` 把候选池从 100+ 收窄到 10~20，再做语义召回。这一步是**纯程序化过滤，不消耗模型 token，且不会引入语义误差**。
2. **再换真实 embedding**（`embed_local` → 方舟 `/embeddings`，接口已在 `gateway/openai_compat.py::embed` 备好）。
3. **最后考虑向量库**（技能到千级再上 FAISS/Milvus；百级规模下内存内余弦计算完全够用，引入向量库反而增加运维面）。

---

## 3. 未覆盖根因场景的诊断保障（问题 2）

### 3.1 当前三条降级路径与真实风险

| 路径 | 触发条件 | 实测行为 | 风险等级 |
|---|---|---|---|
| 近邻误判 | 存在语义相近但错误的技能 | 输出错误标签 + 错误处置建议，**零告警** | 🔴 极高 |
| 探针盲区假阴性 | 存活技能探针未覆盖真实错误 | `no_fault_found`，**与库中事实矛盾** | 🔴 极高 |
| 诚实停止 | 候选集全零分 | `unanswerable` + 说明缺什么 | 🟢 可接受 |

前两条的共同特征：**系统对自己的无知没有感知**。所有现有质量闸门（悬空引用率、引用校验、证据包三级验证）都只能验证"引用的证据是真的"，无法验证"结论是对的"。这是一个**校验维度的空白**：当前系统校验了 *evidence integrity*，但没有校验 *conclusion coverage*。

### 3.2 设计原则：从闭集分类到开集推理

| | 当前（闭集） | 目标（开集） |
|---|---|---|
| 根因来源 | 技能 `root_cause_label` | 技能标签 **或** 证据驱动的开放描述 |
| 无匹配时 | 强行归入近邻 / 判无故障 | 显式标记 `novel`，输出证据摘要与假设 |
| 置信度 | 无（二元 answered/not） | 分级（confirmed / probable / suspected / novel / insufficient） |
| 技能角色 | 分类器 | 取证策略 + 先验知识 |

### 3.3 五层保障机制

#### L0 全局未解释错误哨兵（P0，直接修复 FM-2）

**在 `report` 与 `unanswerable` 节点之前，强制执行一次全局不变量检查**：

```python
# 建议新增 graph.py::_unexplained_error_sweep
def _unexplained_error_sweep(self, st: SessionState) -> dict:
    """结论落地前的最后一道闸：库里是否存在从未被任何探针取回的错误级证据？

    FM-2 实测：三个技能被剔除后系统输出 no_fault_found，而库中确实存在 5 条
    ERROR 行（含明文 'campaign aborted ... reason=UDS_NRC_0x72'）。根因是
    has_error 判据只看 evidence_pool（探针取回的），不看数据库全集。
    这一层用一次廉价聚合查询封住该缺口。
    """
    total = self.api._q("SELECT count(*) n FROM log_lines WHERE level_num>=40")[0]["n"]
    seen = {r.get("row_hash") for r in st.evidence_pool}
    if total == 0:
        return {"clean": True, "unexplained": 0}
    rows = self.api._q("""
        SELECT row_hash, component, ota_phase, level_norm,
               substr(raw_line,1,200) AS preview
        FROM log_lines WHERE level_num>=40
        ORDER BY ts_utc LIMIT 50""")
    unexplained = [r for r in rows if r["row_hash"] not in seen]
    return {"clean": not unexplained, "total_errors": total,
            "unexplained": len(unexplained), "samples": unexplained[:10]}
```

**接入点与语义**：

- `node_report` 之前调用；若 `unexplained > 0`，**禁止输出 `no_fault_found`**，强制降级为 `insufficient_coverage` 并把未解释错误行附在报告里
- `unanswerable` 之前同样调用；把未解释错误行作为"下一步该看什么"的具体线索交给人工，而不是空手转人工
- 发 `ALERT` 级事件 `coverage.unexplained_errors`
- 新增评测指标 `unexplained_error_rate`，目标 ≤ 0.05

**这一层的价值在于它不依赖任何模型判断**——纯 SQL 不变量，成本近乎为零，却能把 FM-2 这类"与事实直接矛盾"的结论完全挡住。

#### L1 通用证据优先兜底技能（P0）

新增一个**无 `root_cause_label` 的通用技能**，在候选全零分时兜底：

```yaml
- id: SK-GENERIC-EVIDENCE-FIRST
  status: active
  domain: orchestration
  title: 通用证据优先排查（无匹配已知模式时）
  trigger: 无已知故障模式匹配，但存在错误级证据
  summary: 不预设根因，按"错误聚集点 → 首个异常 → 上下文 → 跨组件关联"顺序取证
  keywords: []                        # 【关键】空关键词：永不参与常规竞争
  fallback_only: true                 # 【新增字段】仅在候选全零分时激活
  probes:
    - {tool: aggregate, args: {group_by: [component, ota_phase], filters: {min_level: ERROR}, limit: 30}}
    - {tool: search_logs, args: {query: "", mode: substring, min_level: ERROR, order: severity, limit: 80}}
    - {tool: top_templates, args: {sort: rare, limit: 30}}
    - {tool: find_gaps, args: {min_gap_seconds: 30, limit: 15}}
  root_cause_label: null              # 【关键】不贴标签，交由 L2 生成开放描述
  owner: ota-diagnosis-team
```

配套改造 `skills.py::retrieve`：`fallback_only: true` 的技能从常规召回中排除，仅当其余候选全零分时才注入。

#### L2 开放式根因假设（P1）

放宽 `decisive` 判据与 `_root_cause`，允许无标签路径产出结论：

```python
# 当前（graph.py:234）：无技能标签则永远不 decisive
decisive = (bool(supported) and has_error_evidence and skill_id is not None
            and self.skills.label_of(skill_id) is not None)

# 建议：证据充分即可收敛，标签有无只影响置信度分级
decisive = bool(supported) and has_error_evidence and _evidence_sufficient(cr)
```

`_root_cause` 增加开放分支：当无技能标签但有错误证据时，调用 `reporter` 模型基于证据链生成**自由文本根因描述**，并标记：

```python
{
  "label": "novel:flash_erase_hal_error",   # novel: 前缀，与受控标签空间隔离
  "label_kind": "novel",                     # known | novel | insufficient
  "confidence": "suspected",
  "title": "（未匹配已知模式）Flash 擦写 HAL 层返回 -5，重试耗尽",
  "novel_candidate": True,                   # 标记为知识蒸馏的高价值输入
}
```

**`novel:` 前缀是刻意设计**：它让开放式结论在评测统计中天然与受控标签分离，不会污染 `top1_root_cause_accuracy` 指标，同时又是知识库补全的最佳线索来源（见 §6.7）。

#### L3 竞争性假设与鉴别诊断（P1，抑制 FM-1）

FM-1 的本质是**系统只考察了一个假设就收敛**。改造：

1. **强制多假设并行**：`node_plan` 一轮内执行 Top-2 技能的探针（预算允许时），而非只执行 Top-1
2. **引入 `differential` 字段**（见 §2.3 Schema）：结论前检查易混淆项的区分点。例如判定 `uds_nrc_programming_failure` 前，检查同窗口 `powerd` 电压曲线以排除 `power_voltage_drop`
3. **置信度随竞争态势下调**：Top-1 与 Top-2 的证据支撑度接近时（差距 < 阈值），置信度从 `confirmed` 降为 `probable`，并在报告中并列两种可能

#### L4 置信度分级与拒答策略（P0）

替换当前二元的 `answered / unanswerable`：

| 等级 | 判据 | 报告呈现 |
|---|---|---|
| `confirmed` | 已知标签 + 多组件交叉印证 + 无未解释错误 + 通过鉴别诊断 | 直接给结论与处置 |
| `probable` | 已知标签 + 单一证据源 或 竞争假设接近 | 给结论 + 并列备选 + 建议验证动作 |
| `suspected` | 已知标签但关键信号缺失（`confidence_policy` 未满足） | 标注"疑似"，重点给验证方法 |
| `novel` | 有错误证据但无匹配标签 | 给证据链与开放描述，明确"未匹配已知模式" |
| `insufficient_coverage` | 存在未解释错误但证据不足以推断 | 列出未解释错误行 + 建议补采数据 |
| `no_fault_found` | **全局无错误行**（L0 通过） | 判定正常完成 |

### 3.4 改造清单汇总

| 优先级 | 改动 | 文件 | 规模 |
|---|---|---|---|
| P0 | `_unexplained_error_sweep` + 接入两处 | `graph.py` | ~50 行 |
| P0 | 置信度分级替换二元状态 | `graph.py::_root_cause`, `state.py` | ~80 行 |
| P0 | `SK-GENERIC-EVIDENCE-FIRST` + `fallback_only` | `skills/`, `skills.py::retrieve` | ~40 行 |
| P1 | 开放式根因（`novel:` 分支） | `graph.py`, `prompts.py`, `mock.py` | ~120 行 |
| P1 | 鉴别诊断（`differential` 消费） | `graph.py::node_verify` | ~90 行 |
| P1 | 处置建议迁出 `_SUGGEST` | `graph.py`, Schema v2 | ~30 行 |
| P1 | 新增指标 4 项 | `eval/runner.py`, `report.py` | ~60 行 |

**新增评测指标**（应加入 `_TARGETS`）：

```python
"unexplained_error_rate":        (0.05, "<="),  # 结论落地时未解释的错误行占比
"misdiagnosis_rate_under_ablation": (0.20, "<="),  # 消融实验下的误诊率（新增消融评测集）
"novel_detection_recall":        (0.80, ">="),  # 剔除技能后能否正确标记为 novel 而非误判
"confidence_calibration_error":  (0.15, "<="),  # confirmed 结论的实际正确率与声称置信度的偏差
```

**特别建议新增「消融评测集」**：把现有 10 场景 × 逐个剔除正确技能，构造 10 个"未知故障"用例。这是**唯一能持续度量泛化能力**的手段——否则技能库越全，评测分数越高，但泛化能力反而无从观测（当前 Top-1=1.0 的漂亮数字，恰恰掩盖了 §0.2 揭示的脆弱性）。

---

## 4. 基于历史 Jira 工单的知识自动化提取（问题 3）

### 4.1 数据资产盘点

典型 Jira OTA 工单可用字段与其知识价值：

| 字段 | 知识价值 | 提取难度 |
|---|---|---|
| Summary / Description | 症状描述（自然语言） | 低 |
| 附件日志包 | **黄金证据**——可直接建库 | 低（复用 `vela build`） |
| Resolution / Root Cause 自定义字段 | 根因标签（若规范填写） | 低~中 |
| 评论区排查过程 | **探针合成的最佳来源**（工程师实际查了什么） | 高 |
| Linked Issues | 类案聚类线索 | 低 |
| Component / Labels / 车型 / ECU 字段 | 分类维度 | 低 |
| 修复 commit / 版本 | 处置方案 | 中 |

**准入前提（必须先确认，否则整个管线是空中楼阁）**：

1. 附件日志包的**留存率**与**可解析率**——抽样 100 个工单实测，若可用率 < 30%，管线的性价比需重估
2. 根因字段的**规范化程度**——自由文本 vs 下拉枚举，决定 §4.4 走自顶向下还是自底向上
3. **数据合规**：日志含 VIN/位置/用户信息，进入知识库前必须过 `gateway/redact.py` 同款脱敏；建议在管线入口即脱敏，而非出口

### 4.2 五阶段管线

```
[1 抽取] Jira API → 结构化工单记录 + 附件下载
     ↓
[2 对齐] 工单 ⟷ 日志包配对，建库（复用 vela build），产出可查询证据库
     ↓
[3 归纳] 症状特征提取 → 聚类 → 候选故障模式（含标签归一）
     ↓
[4 合成] 每个簇 → 技能草案（keywords/symptoms/probes/label/remediation/differential）
     ↓
[5 验证] 留出集回测 → 影响面分析 → 人工评审 → 灰度（见 §6）
```

#### 阶段 1：抽取

```python
# 建议新增 src/vela/mining/jira_extract.py
@dataclass
class TicketRecord:
    key: str                        # OTA-1234
    summary: str
    description: str
    root_cause_text: str | None     # 自定义字段原文
    resolution: str | None
    components: list[str]
    labels: list[str]
    ecu_hints: list[str]            # 从字段或正文正则抽取的 ECU ID
    vehicle_model: str | None
    created_at: str
    attachments: list[Path]         # 已下载的日志包
    comments: list[str]             # 排查过程
```

#### 阶段 2：对齐与建库（这是最有价值的一步）

**关键洞察**：Jira 工单的日志附件与本项目的输入格式**完全同构**——都是车端上传的日志压缩包。这意味着 `vela build` 可以直接复用，无需任何适配。

```python
for t in tickets:
    for zp in t.attachments:
        if not is_log_archive(zp):
            continue
        ws = mining_root / t.key / zp.stem
        try:
            r = build(zp, ws, progress=False)      # 复用现有管线
        except Exception as e:
            record_failure(t.key, zp, e); continue
        # 产出：可用 12 个工具查询的证据库 + QA 报告
```

**副产品价值极高**：这一步会自然产出一个**真实日志的回归数据集**——比仿真数据更能暴露解析器覆盖不足（新格式、新编码、新组件路径）。建议把 `qa_report.json` 的 `未解析率` 与 `ts_confidence 占比` 做成看板，**驱动 `parsers.yaml` 的持续补全**。这条反馈回路本身就值得单独立项。

#### 阶段 3：归纳（症状特征提取 + 聚类）

对每个成功建库的工单，程序化提取**症状指纹**（不依赖模型，确定性）：

```python
def extract_symptom_vector(api: LogQueryAPI) -> dict:
    """从证据库提取结构化症状——这是聚类与技能匹配的公共特征空间。"""
    pt = api.call("phase_timeline")
    tt = api.call("top_templates", sort="error_only", limit=30)
    ag = api.call("aggregate", group_by=["component", "level_norm"],
                  filters={"min_level": "ERROR"}, limit=20)
    gaps = api.call("find_gaps", min_gap_seconds=30, limit=10)
    return {
        "fail_phase": pt.summary.get("last_phase"),
        "abort_reason": _parse_abort_reason(pt.summary.get("abort_markers")),
        "error_templates": [r["template_text"] for r in tt.rows],       # 归一化模板
        "error_components": [(r["component"], r["n"]) for r in ag.rows],
        "silent_components": [r["component"] for r in gaps.rows],
        "nrc_codes": _scan_nrc(api),
        "ecu_ids": _scan_ecus(api),
    }
```

**聚类特征优先用 `template_id` 而非原始文本**——模板已经把 VIN、时间、块号等参数归一化了（`MiniDrain` 的产出），天然具备跨工单可比性。这是本项目数据层设计在知识挖掘场景下的意外红利。

聚类策略：
- 一级：按 `fail_phase` + `abort_reason` 硬分组（强信号，确定性）
- 二级：组内按 `error_templates` 的 Jaccard 相似度做层次聚类
- 三级：人工/模型对簇命名（映射到受控标签表，或提议新标签）

#### 阶段 4：技能合成（探针反向工程）

**这是整条管线技术含量最高的一步**：从"工程师当初怎么查的"反推探针。

三个信息源，可靠性递减：

1. **从证据本身反推（最可靠，纯程序化）**
   簇内共现的错误模板 → 直接生成 `search_logs` 探针：
   ```python
   common = templates_appearing_in(cluster, min_ratio=0.8)   # 80% 案例都有的模板
   probe = {"tool": "search_logs",
            "args": {"query": distinctive_terms(common), "mode": "substring",
                     "min_level": "WARN", "limit": 60}}
   ```
   同理，簇内高频的 `nrc_codes` → `error_code_lookup` 探针；`silent_components` 显著 → `find_gaps` 探针。

2. **从工单评论反推（信息最丰富，噪声也最大）**
   评论里的"我看了 xx 日志发现 yy"用模型抽取为查询意图，再映射到 12 个工具。**必须过验证闸**（阶段 5），不可直接采信。

3. **从修复 commit 反推处置建议**
   commit message + diff 摘要 → `remediation` 草案。

**探针质量的硬性验收标准**：合成的探针必须在**该簇的留出案例上实际召回到关键证据**。这是可自动化验证的——把簇按 70/30 切分，用 70% 合成探针，在 30% 上跑，要求关键错误行召回率 ≥ 0.8。达不到就退回人工。

#### 阶段 5：验证（详见 §6）

### 4.3 去重、合并与冲突处理

| 情形 | 判定 | 处理 |
|---|---|---|
| 新簇 ≈ 已有技能（症状 Jaccard > 0.7） | 重复 | 不新建；把案例数并入已有技能的 `evidence_cases`，`provenance.jira_issues` 追加 |
| 新簇与已有技能部分重叠 | 细化 | 建议新建**子技能**（`ecu_scope`/`vehicle_scope` 收窄），保留父技能 |
| 新簇与已有技能症状相同但标签不同 | **冲突** | 🔴 阻断，必须人工裁决——这通常意味着已有标签定义有歧义 |
| 新簇标签不在受控表内 | 新标签提议 | 走标签评审流程（比技能评审更严格，因为影响评测口径） |

**冲突必须阻断而非自动合并**——症状相同标签不同，要么是两个真的不同的根因（需要新增区分信号），要么是标签体系本身有问题。任何自动处理都会把问题掩盖到知识库深处。

### 4.4 标签体系：自底向上 vs 自顶向下

| | 自顶向下（先定标签表，再归类） | 自底向上（先聚类，再命名） |
|---|---|---|
| 适用 | Jira 根因字段规范（下拉枚举） | 根因字段是自由文本 |
| 优点 | 标签稳定、与现有 10 标签对齐 | 能发现未预料的故障模式 |
| 风险 | 现实故障塞不进预设分类 | 标签爆炸、粒度不一 |

**建议混合**：以现有 10 个受控标签为骨架自顶向下归类；归不进去的残差样本单独聚类，产出新标签提议。**残差比例本身就是一个重要指标**——残差 > 30% 说明现有标签体系覆盖不足，需要重新设计而非缝缝补补。

### 4.5 风险控制

| 风险 | 后果 | 缓解 |
|---|---|---|
| **知识投毒** | 错误工单结论固化为技能，持续误导 | 单一工单不可成技能（`evidence_cases ≥ 5`）；人工终审不可跳过 |
| **评测集污染** | 挖掘用的工单进了评测集，指标虚高 | 工单在管线入口即按 `key` 哈希切分 train/holdout，holdout **永不参与**技能合成 |
| **标签漂移** | 自动命名产生同义标签，指标失真 | 受控词表 + 新标签走独立评审 |
| **幸存者偏差** | 只有"查清楚了"的工单进知识库，疑难杂症反而缺失 | 单独统计未结案工单的症状分布，作为知识盲区看板 |
| **隐私合规** | VIN/位置进入知识库 | 入口脱敏 + `evidence_cases` 只存统计量不存原文 |

---

## 5. RCA 推理泛化能力提升（问题 4）

### 5.1 泛化的三个层次

| 层次 | 含义 | 当前状态 | 关键改造 |
|---|---|---|---|
| L1 参数泛化 | 同一模式的不同参数（不同 ECU/块号/车型） | ✅ 已具备（模板归一化 + 正则探针） | — |
| L2 组合泛化 | 已知模式的新组合（如"存储不足 → 下载重试 → 超时"级联） | ❌ 不具备（单技能收敛，一轮定论） | 技能协同、因果链 |
| L3 开放泛化 | 全新故障模式 | ❌ 不具备（闭集分类） | §3.3 的 L1/L2 层 |

**当前系统只有 L1**。这解释了为什么 Top-1 能到 1.0（10 个场景都是已知模式的参数变体），却在消融实验下立刻崩溃。**指标漂亮与泛化能力强是两回事**——这一点值得在任何对外汇报中如实说明。

### 5.2 症状本体（Symptom Ontology）：泛化的基础设施

当前技能匹配依赖**关键词字符串命中**（`mock.py::_weighted_signal`），这是最脆弱的一环——换个日志措辞就失效。

**改造**：引入结构化症状层，把"日志文本"与"技能匹配"解耦。

```yaml
# config/symptoms.yaml —— 症状是可复用的原子单元，多个技能可共享
symptoms:
  - id: SYM-ABORT-WITH-REASON
    kind: abort_marker
    extractor: {tool: phase_timeline, field: abort_markers, pattern: "reason=(\\w+)"}
  - id: SYM-UDS-NEGATIVE-RESPONSE
    kind: protocol_error
    extractor: {tool: search_logs, query: "nrc=0x", capture: "nrc=0x([0-9A-Fa-f]{2})"}
  - id: SYM-COMPONENT-SILENCE
    kind: temporal_anomaly
    extractor: {tool: find_gaps, min_gap_seconds: 30, scope: [uds_stack, diag_router]}
  - id: SYM-VOLTAGE-EXCURSION
    kind: physical_signal
    extractor: {tool: search_logs, query: "voltage", capture: "voltage=([0-9.]+)"}
```

技能通过引用症状 ID 匹配，而非裸关键词：

```yaml
symptoms:
  - {ref: SYM-UDS-NEGATIVE-RESPONSE, value_in: ["72", "73"]}
  - {ref: SYM-ABORT-WITH-REASON, value_match: "UDS_NRC_*"}
```

**收益**：
- 症状提取器集中维护，日志格式变化只改一处
- 症状可被多个技能复用，避免关键词在 N 个技能里重复且各自漂移
- 症状是**可组合的**——为 L2 组合泛化提供原语
- 症状提取是**程序化确定性的**，不消耗模型 token，且可单独测试

### 5.3 因果图与组合泛化（L2）

在症状之上定义**因果边**，而非只定义"症状→根因"的扁平映射：

```yaml
# config/causal_graph.yaml
edges:
  - {cause: SYM-STORAGE-LOW, effect: SYM-DOWNLOAD-RETRY, confidence: 0.8,
     mechanism: 磁盘写满导致分片落盘失败触发重试}
  - {cause: SYM-DOWNLOAD-RETRY, effect: SYM-DOWNLOAD-TIMEOUT, confidence: 0.7}
  - {cause: SYM-VOLTAGE-EXCURSION, effect: SYM-UDS-NEGATIVE-RESPONSE, confidence: 0.6,
     mechanism: 供电不稳导致 ECU 编程失败返回 NRC}
```

**推理方式**：当观测到多个症状时，在因果图上找**最小解释集**（能解释最多观测症状的最少根因）。这直接解决"存储不足伪装成下载超时"这类级联故障——当前系统会命中 `SK-DL-TIMEOUT`（直接症状），因果图能回溯到 `storage_insufficient`（真实根因）。

**实现建议**：不必上图数据库，几十个节点用邻接表 + 反向可达性搜索即可，纯 Python 百行内。**关键是先积累因果边**——这正是 Jira 挖掘（§4）的高价值产出：工单里"因为 A 所以 B"的因果陈述，比根因标签本身更稀缺。

### 5.4 类案检索增强（RAG over 历史工单）

把 §4 建成的历史证据库变成**可检索的类案库**：

```
当前会话症状向量 → 检索 Top-K 相似历史工单 → 把"当时的根因 + 排查路径 + 处置"
                                              作为参考注入 planner 上下文
```

**关键纪律（否则会重蹈闭集覆辙）**：
- 类案是**参考**不是**答案**——必须明确提示模型"以下是相似历史案例，仅供参考，结论仍须由本次证据支撑"
- 类案引用与证据引用**分离标记**，类案不得计入 `[[EV:]]` 证据链（它们不是本次日志的证据，混入会破坏证据链的可核验性根基）
- 类案相似度需展示给用户，低相似度时不注入

这一条与本项目现有的引用校验体系是**正交且兼容**的——类案走独立通道，不污染 `row_hash` 引用空间。

### 5.5 方案优先级矩阵

| 方案 | 泛化收益 | 实现成本 | 依赖 | 建议时序 |
|---|---|---|---|---|
| L0 未解释错误哨兵 | 中（堵假阴性） | 极低 | 无 | **立即** |
| 置信度分级 | 中（暴露不确定性） | 低 | 无 | **立即** |
| 通用兜底技能 | 中 | 低 | 无 | **立即** |
| 开放式根因（novel） | 高 | 中 | 置信度分级 | 短期 |
| 症状本体 | 高 | 中 | 无 | 短期 |
| 鉴别诊断 | 中高（抑制误诊） | 中 | Schema v2 | 短期 |
| 因果图 | 很高（L2 组合泛化） | 中高 | 症状本体 + 因果边积累 | 中期 |
| 类案 RAG | 高 | 中高 | Jira 管线 | 中期 |
| 真实 embedding | 中 | 低 | 方舟接入 | 按技能规模触发 |

---

## 6. 知识蒸馏结果的统一治理与准入（问题 5）

### 6.1 现状缺口

```python
# graph.py::node_distill —— 只写候选，无任何入库路径
append_jsonl(p, {..., "status": "pending_review", **out})
```

`grep -rn "candidates.jsonl"` 全项目**仅一处写入，零处读取**。这是刻意的安全设计（未复核知识不得自动生效），但也意味着**闭环缺失最后一环**。同时，Jira 挖掘（§4）会产出第二个知识来源，两条来源必须统一治理，否则会出现"同一故障模式两个来源各建一个技能"的分裂。

### 6.2 统一知识生命周期

```
   ┌──────────┐   ┌──────────┐
   │ 会话蒸馏  │   │ Jira挖掘 │        两个来源，一套流程
   └────┬─────┘   └────┬─────┘
        └───────┬───────┘
                ▼
          [draft 草案]  ──────► 五道闸门 ──────► [shadow 影子]
                                    │                  │
                              任一不通过              影子期观察
                                    ▼                  ▼
                              [rejected]         [active 生效]
                                                       │
                                              review_due 到期
                                                       ▼
                                              [deprecated 退役]
```

状态存于技能 YAML 的 `status` 字段，`load_skills()` 默认只加载 `active`（`shadow` 仅在影子评测时加载）。

### 6.3 五道闸门

| 闸门 | 检查内容 | 自动化 | 不通过处理 |
|---|---|---|---|
| **G1 结构** | Schema v2 校验、词表合规、ID 唯一、探针工具名与参数合法 | 全自动（`vela skills lint`） | 直接 reject |
| **G2 安全** | 无 PII 泄漏（脱敏检查）、无提示注入模式、探针不触发全表扫描 | 全自动 | 直接 reject |
| **G3 证据** | `evidence_cases ≥ 5`、探针在留出集召回率 ≥ 0.8、症状区分度达标 | 全自动 | 退回补充案例 |
| **G4 影响面** | 影子评测：对现有全部评测用例的指标影响 | 全自动 | 指标退化则 reject |
| **G5 人工** | 领域专家终审：标签命名、处置建议正确性、鉴别诊断合理性 | 人工 | 退回修改 |

**G4 影响面分析是最关键也最容易被忽略的一道**。新增一个技能不只是"多了一种能力"——它会进入所有会话的候选集，可能抢占原本正确技能的召回位次。FM-1 揭示的正是这种机制的破坏力。

### 6.4 影子评测设计

```python
# 建议新增 src/vela/eval/shadow.py
def shadow_eval(candidate_skill: dict, baseline_result: EvalResult) -> ShadowReport:
    """把候选技能加入技能库后重跑完整评测，逐用例对比。

    重点不是"新技能自己表现如何"，而是"它有没有把原本正确的用例带偏"——
    §0.2 的 FM-1 表明，一个语义近邻的技能足以让正确结论被错误结论取代。
    """
    with_candidate = load_skills() + [candidate_skill]
    new_result = EvalRunner(...).run(skills=SkillRegistry(with_candidate))
    return ShadowReport(
        regressions=[c for c in new_result.cases                    # 🔴 一票否决
                     if _was_correct(baseline_result, c.case_id) and not c.top1_hit],
        improvements=[c for c in new_result.cases
                      if not _was_correct(baseline_result, c.case_id) and c.top1_hit],
        metric_delta=_diff(baseline_result.metrics(), new_result.metrics()),
        recall_position_shifts=_skill_rank_changes(baseline_result, new_result),
    )
```

**准入判据**：
- `regressions` 非空 → **一票否决**（宁可不增加能力，也不能破坏已有能力）
- `false_positive_rate` 上升 → 否决
- `unexplained_error_rate` 上升 → 否决
- 无回归且至少一项改善 → 进入 `shadow` 状态

### 6.5 影子期与灰度

进入 `shadow` 状态后，技能**参与召回与探针执行，但其结论不对外呈现**——只记录"如果采信它会得出什么"，与实际采信的结论并列存档。

```yaml
status: shadow
shadow_since: 2026-08-01
shadow_policy:
  min_sessions: 50          # 至少观察 50 个真实会话
  min_days: 14
  promote_if:
    agreement_with_human: ">= 0.85"   # 与人工最终结论的一致率
    no_regression: true
```

影子期结束后，用真实会话数据（而非仿真评测集）做最终判断。这是**唯一能验证"知识在真实分布上是否成立"**的手段——仿真评测集再全面也只覆盖已设计的场景。

### 6.6 知识注册表

```
config/skills/_registry.yaml     # 自动生成，人工只读
```

```yaml
generated_at: 2026-08-01T10:00:00Z
config_hash: sha256:...
skills:
  - {id: SK-FLASH-UDS-NRC, version: 2.1.0, status: active, domain: flash,
     owner: ota-diagnosis-team, source: manual, evidence_cases: 47,
     last_eval_top1_contribution: 0.11, reviewed_at: 2026-07-15, review_due: 2027-01-15}
  - {id: SK-AUTO-A3F2E1, version: 0.1.0, status: shadow, domain: flash,
     source: jira_mined, evidence_cases: 8, shadow_since: 2026-08-01,
     provenance: {jira_issues: [OTA-1234, OTA-2871, ...]}}
totals: {active: 34, shadow: 5, draft: 12, deprecated: 3}
```

注册表纳入 `config_hash` 计算，使**每一次诊断都能追溯到当时生效的确切知识版本**——这与项目现有的 `run.config_hash` 证据链设计一脉相承，是"结论可复现"承诺的必要组成部分。

### 6.7 与现有 `candidates.jsonl` 的衔接

最小改造路径（不破坏现有设计）：

1. `node_distill` 输出增加 `provenance` 与 `symptom_vector`（供后续聚类与去重）
2. 新增 `vela knowledge promote --from candidates.jsonl --gate all`：读取候选 → 跑五道闸门 → 通过者写入 `config/skills/90-derived/` 并置 `status: draft`
3. 新增 `vela knowledge review --status draft`：交互式人工评审（G5）
4. 新增 `vela knowledge shadow-report --id SK-XXX`：查看影子期表现
5. `novel:` 前缀的开放式结论（§3.3 L2）自动进入候选池——**这是知识库自我补全的主回路**：泛化能力发现新模式 → 蒸馏为候选 → 验证后入库 → 下次直接命中

第 5 点值得强调：**L2 开放式根因与知识蒸馏构成正反馈**。没有 L2，系统永远只能在闭集内打转，蒸馏出的也只是已知模式的重复；有了 L2，系统才真正具备"发现未知"并把它转化为"已知"的能力。这是整套方案里最有杠杆的一环。

---

## 7. 实施路线图

### 第一阶段：止血（1~2 周，不依赖外部数据）

目标：**消除两个已实测的失效模式**，让系统对自己的无知有感知。

- [ ] L0 全局未解释错误哨兵（P0）
- [ ] 置信度六级分级替换二元状态（P0）
- [ ] `SK-GENERIC-EVIDENCE-FIRST` 兜底技能 + `fallback_only` 机制（P0）
- [ ] **消融评测集**：10 场景 × 剔除正确技能，新增 4 项泛化指标
- [ ] 处置建议从 `_SUGGEST` 迁入 YAML（消除耦合点 D）

**验收**：消融实验下 `misdiagnosis_rate ≤ 0.2`，`novel_detection_recall ≥ 0.8`，`unexplained_error_rate ≤ 0.05`。注意：**此阶段现有 Top-1 指标可能不升反降**——因为部分原本"蒙对"的用例会被正确识别为低置信度。这是预期且正确的行为，不应视为退化。

### 第二阶段：解耦与治理（3~4 周）

- [ ] 技能 Schema v2 + `_taxonomy.yaml` 受控词表
- [ ] 技能库按域拆分为多文件（加载器已支持，零代码改动）
- [ ] `vela skills lint` / `list` 子命令
- [ ] 症状本体 `symptoms.yaml` + 提取器
- [ ] 鉴别诊断 `differential` 消费逻辑
- [ ] 开放式根因 `novel:` 分支

### 第三阶段：知识挖掘（6~8 周，需 Jira 数据准入）

- [ ] **前置**：抽样 100 工单，实测附件可用率与根因字段规范度（决定是否继续）
- [ ] 抽取 + 对齐 + 批量建库（副产品：真实日志回归集，驱动 `parsers.yaml` 补全）
- [ ] 症状聚类 + 标签归一（含残差分析）
- [ ] 技能草案合成 + 探针反向工程
- [ ] train/holdout 严格切分，防评测污染

### 第四阶段：闭环治理（4~6 周）

- [ ] 五道闸门 + `vela knowledge promote/review`
- [ ] 影子评测 + 影子期观察机制
- [ ] 知识注册表 + `config_hash` 纳入
- [ ] 因果图与组合泛化（L2）
- [ ] 类案 RAG（独立引用通道）

---

## 8. 风险登记册

| ID | 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|---|
| R1 | 技能库扩张导致召回混淆，误诊率上升 | 高 | 高 | 关键词冲突 lint + 维度预过滤 + 影子评测一票否决 |
| R2 | Jira 附件可用率过低，管线投入产出比失衡 | 中 | 高 | **第三阶段前置抽样验证**，可用率 < 30% 则重估方案 |
| R3 | 自动挖掘知识投毒 | 中 | 极高 | `evidence_cases ≥ 5` + 五道闸门 + 人工终审不可跳过 |
| R4 | 标签体系分裂，评测口径失效 | 高 | 中 | 受控词表 + 新标签独立评审 + 别名映射 |
| R5 | 评测集被挖掘数据污染，指标虚高 | 中 | 高 | 入口按工单 key 哈希切分，holdout 永不参与合成 |
| R6 | 开放式根因（novel）泛滥，退化为"什么都不确定" | 中 | 中 | novel 需满足最低证据门槛；novel 率纳入监控看板 |
| R7 | 置信度分级后"确定"结论减少，用户感知能力下降 | 高 | 中 | **主动沟通**：这是暴露既有不确定性而非引入新问题；配套给出"如何提升置信度"的具体建议 |
| R8 | 影子期过长拖慢知识迭代 | 中 | 低 | 按技能风险分级设定影子期（高风险域长、低风险域短） |

---

## 9. 结语：一个需要如实面对的结论

本项目当前的黄金评测成绩（Top-1 = 1.0，假阳性 = 0，悬空引用 = 0）是真实且经得起复现的——但它度量的是**闭集分类能力**，不是**开放域诊断能力**。§0.2 的消融实验用三行代码就把这个区别暴露无遗：剔除一个技能，系统立刻从"完美"变成"自信地给出错误答案"，而所有现有质量闸门无一告警。

这不是实现缺陷，而是**架构选择的必然结果**——把根因标签绑定在技能配置上，就等于声明"我只认识我被告知的东西"。对 POC 而言这是合理的取舍（它换来了确定性、可复现和完整的证据链）；但要走向生产，必须补上"知道自己不知道"的能力。

值得强调的是，本项目**最有价值的部分恰恰不依赖技能库**：证据链、三级验证、引用校验、预算压缩、护栏——这些"可信性基础设施"在消融实验中始终正常工作（悬空引用率恒为 0.0）。这意味着上述所有改造都是在一个**稳固的地基上做加法**，而不是推倒重来。

因此本方案的第一阶段刻意只做"止血"：不追求提升准确率，只追求**让系统的不确定性变得可见**。一个诚实地说"我不确定，这是我看到的证据"的诊断系统，比一个自信地给出错误 ECU 排查建议的系统，在真实生产环境中的价值高得多——后者浪费的是工程师排查一整天的时间，以及对整个系统的信任。

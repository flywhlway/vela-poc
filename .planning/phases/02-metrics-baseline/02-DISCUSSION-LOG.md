# Phase 2: 度量可信与真实基线 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-31
**Phase:** 2-度量可信与真实基线
**Mode:** `--auto`
**Areas discussed:** 引用闸门语义, config_hash 覆盖与断代, 重复评测与置信区间, LLM 缓存与 reuse-workspace, 过程指标与消融集, 真实基线与 NR-1, 成本延迟与 TokenLedger, 阶段纪律与执行顺序

---

## 引用闸门语义

| Option | Description | Selected |
|--------|-------------|----------|
| 零引用 → ok=False，dangling_rate=None，has_citations=False | 严格闭合 F-01；与 METR-01/02 字面一致 | ✓ |
| 零引用仅告警、ok 仍 True | 保留旧行为，仅加指标 | |
| 零引用时 dangling_rate=1.0 | 用 1.0 表示最差，而非 None | |

**User's choice:** [auto] 零引用 → ok=False，dangling_rate=None，has_citations=False（recommended default）
**Notes:** citation_coverage 用确定性句切分启发式；ORCH-08 reporter 重试留给 Phase 3（D-04）

`[auto] 引用闸门语义 — Q: "零引用时质量闸门如何判定？" → Selected: "ok=False + dangling_rate=None + has_citations" (recommended default)`

`[auto] 引用闸门语义 — Q: "citation_coverage 事实句如何定义？" → Selected: "确定性句切分启发式（句号/换行）" (recommended default)`

---

## config_hash 覆盖与断代

| Option | Description | Selected |
|--------|-------------|----------|
| 纳入 skills + budget + llm + prompts.py，保留原三 YAML；env_checks 排除；docs 映射表 | 严格 METR-03 + Phase 1 D-16 | ✓ |
| 仅纳入 skills，其余下阶段 | 缩小断代面 | |
| 全 config/ 目录哈希 | 过宽，诊断文件也会断代 | |

**User's choice:** [auto] 纳入 skills/budget/llm/prompts；映射表 `docs/CONFIG_HASH_HISTORY.md`
**Notes:** 一次性承担 NR-6 断代成本

`[auto] config_hash — Q: "指纹纳入范围？" → Selected: "skills+budget+llm+prompts，排除 env_checks" (recommended default)`

`[auto] config_hash — Q: "版本映射表放哪？" → Selected: "docs/CONFIG_HASH_HISTORY.md" (recommended default)`

---

## 重复评测与置信区间

| Option | Description | Selected |
|--------|-------------|----------|
| 显式 --repeat N；默认单次；Student t 95% CI；成熟统计库 | 小样本 N≥3 标准做法 | ✓ |
| 默认永远 repeat=3 | 改默认行为、拖慢日常 eval | |
| Bootstrap CI | 更重，N=3 时无优势 | |

**User's choice:** [auto] --repeat 显式 + t 区间 95%
**Notes:** D-01 允许 scipy/numpy

`[auto] 重复评测 — Q: "CI 方法与默认行为？" → Selected: "Student t 95% CI；无 flag 仍单次" (recommended default)`

---

## LLM 缓存与 reuse-workspace

| Option | Description | Selected |
|--------|-------------|----------|
| 项目级 .cache/vela/llm/；键四元组；--no-cache；reuse 跳过已有完好库 | 与 METR-06/07 字面一致 | ✓ |
| 缓存进 workspace/ 每次评测目录 | 不利于跨 run 命中率 | |
| 仅内存缓存 | 进程结束即失，达不到 >90% 迭代目标 | |

**User's choice:** [auto] 磁盘四元组键 + --reuse-workspace 跳过完好库
**Notes:** 半成品库不得 silently 复用

`[auto] 缓存/reuse — Q: "缓存落盘与键？" → Selected: ".cache/vela/llm/ + (provider,model,prompt_sha,params)" (recommended default)`

`[auto] 缓存/reuse — Q: "reuse-workspace 语义？" → Selected: "完好库则跳过 build，否则重建/失败" (recommended default)`

---

## 过程指标与消融集

| Option | Description | Selected |
|--------|-------------|----------|
| 聚合既有状态入报表；运行时 mask 正确技能；四指标进 _TARGETS 不要求达标；novel 等用代理口径 | 可测性优先，不改推理 | ✓ |
| 改 builtin.yaml 落盘残缺技能库 | 污染源技能库 | |
| 本阶段强行实现 novel: 以算真召回 | 越界 Phase 5 | |

**User's choice:** [auto] 运行时 mask + 代理口径 + 不要求达标
**Notes:** 报表注释标明代理口径待 Phase 5 替换

`[auto] 过程/消融 — Q: "消融如何构造？" → Selected: "运行时 mask 正确技能，不改 YAML 源" (recommended default)`

`[auto] 过程/消融 — Q: "依赖 Phase 5 的指标？" → Selected: "代理定义 + 文档标注" (recommended default)`

---

## 真实基线与 NR-1

| Option | Description | Selected |
|--------|-------------|----------|
| N≥3、--no-cache、volcengine；落盘 phase baseline/；废止 44.4% 对比 | ROADMAP Success Criteria 5 + NR-1 | ✓ |
| 继续口头引用 44.4% 直至 Phase 3 | 违反 ADR-2/NR-1 | |
| N=1 单点刷新数字 | 无置信区间，重蹈 F-02 | |

**User's choice:** [auto] 方差基线落盘 + 废止 44.4%
**Notes:** realllm 排除；仿真门非能力宣称

`[auto] 真实基线 — Q: "基线如何落盘与取代 44.4%？" → Selected: "baseline/ md+json；后续禁止引用 44.4%" (recommended default)`

---

## 成本延迟与 TokenLedger

| Option | Description | Selected |
|--------|-------------|----------|
| 扩 bench.py + TokenLedger 归集；上限进 budget.yaml；ALERT 不替代硬切断 | PERF-01/02 | ✓ |
| 新建独立成本服务 | 过重、破坏本地优先 | |
| 超限即硬失败替代 BudgetExceeded | 混淆两套语义 | |

**User's choice:** [auto] 归集+告警与硬切断分离；与 METR-09 共用实测
**Notes:** —

`[auto] PERF — Q: "成本如何观测与告警？" → Selected: "TokenLedger 归集 + yaml 上限 + EventBus ALERT" (recommended default)`

---

## 阶段纪律与执行顺序

| Option | Description | Selected |
|--------|-------------|----------|
| 先 METR-01~08+PERF-02，收尾 METR-09/PERF-01；禁止改推理图 | ROADMAP Depends on 建议 | ✓ |
| 先跑真实基线再修闸门 | 基线建立在坏尺子上 | |
| 顺带修 ORCH 首轮 stop | 范围蔓延至 Phase 3 | |

**User's choice:** [auto] 基础设施先行、基线收尾；D-24 拒改推理
**Notes:** —

`[auto] 纪律 — Q: "阶段内顺序与改动边界？" → Selected: "先尺子后基线；不改 AgentGraph 行为" (recommended default)`

---

## Claude's Discretion

- 句切分细节、缓存文件格式、CLI 旗标命名、统计库选型、bench/eval 是否共用内部 API

## Deferred Ideas

- ORCH-08 引用重试、编排止血、六级置信度真口径、Phase 6 FM-1 Q2 捕获、G4 真实标注 → 见 CONTEXT.md `<deferred>`

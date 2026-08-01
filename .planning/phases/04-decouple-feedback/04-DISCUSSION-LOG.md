# Phase 4: 去循环耦合与反馈闭环 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-01
**Phase:** 4-去循环耦合与反馈闭环
**Mode:** `--auto`
**Areas discussed:** 提取器框架边界, 六形态语料与指标, 反馈闭环字段契约, 注入安全与对抗回归, 指纹波次与回归门

---

## 提取器框架边界

| Option | Description | Selected |
|--------|-------------|----------|
| 仅中止/reason/fail_phase/隐式中止可配置；tool 路由与 find_gaps 留 Python（recommended） | 对齐 C-15 枢纽目标，避免伪配置化 | ✓ |
| `_absorb_signals` 整段迁入 YAML | 过度配置化，find_gaps 启发式难表达 | |
| 只抽 `reason=` 一条正则到 YAML，其余不动 | 不满足「新增形态零改 Python」 | |

**User's choice:** [auto] 仅中止相关信号可配置（recommended default）
**Notes:** schema 对齐 parsers.yaml；隐式中止用 `kind: implicit_abort`；现有 reason=/phase 规则首批迁入。

---

## 六形态语料与指标

| Option | Description | Selected |
|--------|-------------|----------|
| 合成对抗语料验收 ≥0.85；不改 10 场景 emitter（recommended） | 保护仿真回归门 | ✓ |
| 改 emitter 让黄金集覆盖六形态 | 污染 golden / 回归归因 | |
| 六形态仅文档约定、无语料门 | 不满足 DECP-02 字面 | |

**User's choice:** [auto] 合成对抗语料 + 保留现有仿真主路径
**Notes:** unmatched_abort_marker_rate 入报表；NR-2 靠指标持续驱动补全。

---

## 反馈闭环字段契约

| Option | Description | Selected |
|--------|-------------|----------|
| 按归因 D2 五键：evidence_so_far / compression_trace / guardrail_notes / prior_verdicts / open_questions（recommended） | 与探索文档字面一致 | ✓ |
| 只塞 evidence_pool 原文前 N 行 | token 爆炸且无压缩/判定上下文 | |
| 等 Phase 5 置信度再补闭环 | 违反 ROADMAP 依赖顺序 | |

**User's choice:** [auto] D2 五键字面契约
**Notes:** SessionState 可增轻量 unresolved；不引入六级置信度。

---

## 注入安全与对抗回归

| Option | Description | Selected |
|--------|-------------|----------|
| DECP-04 与五项约束同批；guard 扩展 sanitize→truncate→wrap；确定性对抗单测（recommended） | ROADMAP 硬约束 | ✓ |
| 先合反馈闭环、下一批再消毒 | 明确禁止（打开注入面） | |
| 仅靠提示词声明、无程序化剥离 | 违反程序化校验优先 | |

**User's choice:** [auto] 同批落地 + sanitize_log_for_llm + 确定性回归
**Notes:** 阈值进 config 并进 config_hash；只进 user 永不进 system。

---

## 指纹波次与回归门

| Option | Description | Selected |
|--------|-------------|----------|
| extractors(+注入配置)进 config_hash；波次 01→02/03→04+05+06→07（recommended） | ADR-5 + 同批注入 | ✓ |
| extractors 不进 hash（纯诊断） | 错误——提取改变诊断语义 | |
| 先做反馈闭环再做提取器 | 违反 DECP-01 优先 | |

**User's choice:** [auto] 进 hash + 硬顺序波次
**Notes:** CONFIG_HASH_HISTORY.md 追加断代行；回归门 177 + 仿真回归 0。

---

## Claude's Discretion

- extractors.yaml 字段微命名
- `_evidence_brief` 是否拆文件
- 合成语料目录位置
- sanitize 函数名与 get_lines 复用细节
- avg_llm_tokens 挂载点

## Deferred Ideas

- symptoms.yaml → v2.0
- Phase 5/6 能力
- 改仿真 emitter 覆盖六形态
- F-11/F-17 检查点脱敏
- 双驱动 M-13 领域包重构

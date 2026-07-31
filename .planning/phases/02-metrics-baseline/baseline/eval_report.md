# Phase 2 真实方差基线（METR-09 / PERF-01）

> **仿真回归门基线，非能力宣称。G4 真实标注集本期未测。**
> **NR-1：自本报告落盘起，禁止再引用 44.4% 作为后续对比基线。** Phase 3~6 一律以本目录为准。
> 分数可能因引用闸门变准而低于旧数——属预期，不是回归。

## 采集条件

| 字段 | 值 |
|------|-----|
| provider | `volcengine` |
| no_cache | `True` |
| N (repeat) | `3` |
| config_hash | `sha256:c1377375a18671772f4101bbdf4584dfb84ec9fc14ddd5a7981ecc375eba3c3e` |
| doctor.local_ok | `True` |

## 聚合准确率（Student t 95% CI）

| 指标 | mean | std | ci95 | n |
|------|------|-----|------|---|
| top1_root_cause_accuracy | 0.5185 | 0.12834496484085375 | [0.19967343272556498, 0.837326567274435] | 3 |

## PERF（末次 run）

| 指标 | 值 |
|------|-----|
| diagnose_p50_s | 42.8679 |
| diagnose_p95_s | 109.809 |
| avg_llm_tokens | 11167.5 |

---

# VELA 黄金评测报告

- profile: `-`  provider: `volcengine`
- 用例总数: **10**（故障 9 / 健康 1）
- 总耗时: 609.32 s

## 核心指标与达标情况

| 指标 | 实测 | 目标 | 结论 |
|---|---|---|---|
| top1_root_cause_accuracy | 0.6667 | >= 0.8 | ❌ 未达标 |
| healthy_specificity | 1.0 | >= 1.0 | ✅ 达标 |
| false_positive_rate | 0.0 | <= 0.0 | ✅ 达标 |
| dangling_citation_rate | 0.0 | <= 0.015 | ✅ 达标 |
| citation_coverage | 0.2293 | >= 0.9 | ❌ 未达标 |
| illegal_skill_reselect_total | 0 | <= 0 | ✅ 达标 |
| evidence_pack_verify_pass | 1.0 | >= 1.0 | ✅ 达标 |
| unexplained_error_rate | 0.6259 | <= 0.5 | ❌ 未达标 |

## 其它指标

| 指标 | 值 |
|---|---|
| fail_phase_accuracy | 0.5556 |
| culprit_component_hit | 0.6667 |
| skill_selection_hit | 0.8889 |
| avg_compression_ratio | 0.8333 |
| avg_rounds | 2.2 |
| avg_llm_tokens | 11167 |
| zero_citation_cases | 4 |
| citation_gate_pass_rate | 0.6 |
| premature_stop_rate | 0.0 |
| llm_parse_failure_rate | 0.7 |
| llm_truncation_rate | 0.2645 |
| verdict_supported_ratio | 0.25 |
| skill_switch_per_session | 0.5 |
| diagnose_p50_s | 42.87 |
| diagnose_p95_s | 109.81 |

> 注：过程/消融指标为代理口径（聚合自 SessionState/events/audit），Phase 3 前允许偏高；依赖六级置信度或 novel: 的字段 Phase 5 后替换。


## 每轮决策轨迹

| case_id | round_no | selected_skill | stop | actions |
|---|---|---|---|---|
| S4_POWER_DROP | 1 | SK-POWER | False | 1 |
| S4_POWER_DROP | 2 | — | False | 0 |
| S6_ECU_SILENT | 1 | SK-ECU-SILENT | False | 1 |
| S6_ECU_SILENT | 2 | — | False | 0 |
| S2_SIGNATURE_FAIL | 1 | SK-PHASE-OVERVIEW | False | 1 |
| S2_SIGNATURE_FAIL | 2 | SK-SIG-VERIFY | False | 1 |
| S2_SIGNATURE_FAIL | 3 | SK-TIMEBASE | False | 1 |
| S2_SIGNATURE_FAIL | 4 | — | False | 0 |
| S9_TIME_DRIFT | 1 | SK-TIMEBASE | False | 1 |
| S9_TIME_DRIFT | 2 | — | False | 0 |
| S7_DEP_MISMATCH | 1 | SK-DEP-VER | False | 1 |
| S1_DOWNLOAD_TIMEOUT | 1 | SK-PHASE-OVERVIEW | False | 1 |
| S1_DOWNLOAD_TIMEOUT | 2 | SK-DL-TIMEOUT | False | 1 |
| S1_DOWNLOAD_TIMEOUT | 3 | SK-NET-LINK | False | 1 |
| S1_DOWNLOAD_TIMEOUT | 4 | — | False | 0 |
| S0_HEALTHY | 1 | SK-PHASE-OVERVIEW | False | 1 |
| S0_HEALTHY | 2 | — | False | 0 |
| S8_ACTIVATE_ROLLBACK | 1 | SK-PHASE-OVERVIEW | False | 1 |
| S8_ACTIVATE_ROLLBACK | 2 | SK-ECU-SILENT | False | 1 |
| S5_STORAGE_FULL | 1 | SK-STORAGE | False | 1 |
| S5_STORAGE_FULL | 2 | — | False | 0 |
| S3_UDS_NRC72 | 1 | SK-UDS-NRC | False | 1 |

## 重复评测聚合（均值 ± 标准差 / 95% CI）

| 指标 | mean | std | ci95 | n |
|---|---|---|---|---|
| avg_compression_ratio | 0.8616666666666667 | 0.03416962588810903 | [0.7768, 0.9465] | 3 |
| avg_llm_tokens | 10621.0 | 603.4997928748609 | [9121.8234, 12120.1766] | 3 |
| avg_rounds | 2.066666666666667 | 0.11547005383792526 | [1.7798, 2.3535] | 3 |
| cases_faulty | 9.0 | 0.0 | [nan, nan] | 3 |
| cases_healthy | 1.0 | 0.0 | [nan, nan] | 3 |
| cases_total | 10.0 | 0.0 | [nan, nan] | 3 |
| citation_coverage | 0.22406666666666666 | 0.052346569451429514 | [0.0940, 0.3541] | 3 |
| citation_gate_pass_rate | 0.4666666666666666 | 0.11547005383792512 | [0.1798, 0.7535] | 3 |
| culprit_component_hit | 0.6296666666666666 | 0.06414361490696742 | [0.4703, 0.7890] | 3 |
| dangling_citation_rate | 0.0 | 0.0 | [nan, nan] | 3 |
| diagnose_p50_s | 43.63333333333333 | 3.6257734806980593 | [34.6264, 52.6403] | 3 |
| diagnose_p95_s | 110.88666666666666 | 16.61119000352874 | [69.6222, 152.1512] | 3 |
| evidence_pack_verify_pass | 1.0 | 0.0 | [nan, nan] | 3 |
| fail_phase_accuracy | 0.48146666666666665 | 0.06420134993388636 | [0.3220, 0.6410] | 3 |
| false_positive_rate | 0.0 | 0.0 | [nan, nan] | 3 |
| healthy_specificity | 1.0 | 0.0 | [nan, nan] | 3 |
| illegal_skill_reselect_total | 0.0 | 0.0 | [nan, nan] | 3 |
| llm_parse_failure_rate | 0.6333333333333333 | 0.11547005383792512 | [0.3465, 0.9202] | 3 |
| llm_truncation_rate | 0.24626666666666666 | 0.03572874659617005 | [0.1575, 0.3350] | 3 |
| premature_stop_rate | 0.0 | 0.0 | [nan, nan] | 3 |
| skill_selection_hit | 0.7778 | 0.11110000000000003 | [0.5018, 1.0538] | 3 |
| skill_switch_per_session | 0.5 | 0.0 | [nan, nan] | 3 |
| top1_root_cause_accuracy | 0.5185 | 0.12834496484085375 | [0.1997, 0.8373] | 3 |
| total_elapsed_s | 602.8466666666667 | 35.752260534591855 | [514.0331, 691.6602] | 3 |
| unexplained_error_rate | 0.6321 | 0.046610299291036536 | [0.5163, 0.7479] | 3 |
| verdict_supported_ratio | 0.3715333333333333 | 0.18046972968709554 | [-0.0768, 0.8198] | 3 |
| zero_citation_cases | 5.333333333333333 | 1.1547005383792517 | [2.4649, 8.2018] | 3 |

## 逐次 run 明细

- run 1: top1=0.4444 fp=0.0 dangling=0.0
- run 2: top1=0.4444 fp=0.0 dangling=0.0
- run 3: top1=0.6667 fp=0.0 dangling=0.0

## 逐用例明细

| 用例 | 期望根因 | 判定根因 | Top1 | 阶段 | 模块 | 技能 | 轮次 | 压缩比 | 悬空率 | 证据包 | 诊断秒 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S4_POWER_DROP | power_voltage_drop | power_voltage_drop | ✅ | ✅ | ✅ | ✅ | 2 | 0.8116 | 0.0 | ✅ | 79.2 |
| S6_ECU_SILENT | ecu_no_response | — | — | — | — | ✅ | 2 | 1.0 | None | — | 35.3 |
| S2_SIGNATURE_FAIL | signature_verify_fail | signature_verify_fail | ✅ | ✅ | ✅ | ✅ | 4 | 1.0 | 0.0 | ✅ | 109.8 |
| S9_TIME_DRIFT | time_sync_drift | — | — | — | — | ✅ | 2 | 1.0 | None | — | 33.8 |
| S7_DEP_MISMATCH | dependency_mismatch | dependency_mismatch | ✅ | ✅ | ✅ | ✅ | 1 | 1.0 | 0.0 | ✅ | 42.9 |
| S1_DOWNLOAD_TIMEOUT | download_cdn_timeout | download_cdn_timeout | ✅ | — | ✅ | ✅ | 4 | 1.0 | 0.0 | ✅ | 106.8 |
| S0_HEALTHY | （健康） | — | ✅ | — | — | — | 2 | 1.0 | None | — | 31.8 |
| S8_ACTIVATE_ROLLBACK | activate_rollback | — | — | — | — | — | 2 | 1.0 | None | — | 24.5 |
| S5_STORAGE_FULL | storage_insufficient | storage_insufficient | ✅ | ✅ | ✅ | ✅ | 2 | 0.0756 | 0.0 | ✅ | 92.8 |
| S3_UDS_NRC72 | uds_nrc_programming_failure | uds_nrc_programming_failure | ✅ | ✅ | ✅ | ✅ | 1 | 0.4454 | 0.0 | ✅ | 52.3 |

## 备注

- **S4_POWER_DROP**: REUSED_WORKSPACE
- **S6_ECU_SILENT**: REUSED_WORKSPACE
- **S2_SIGNATURE_FAIL**: REUSED_WORKSPACE
- **S9_TIME_DRIFT**: REUSED_WORKSPACE
- **S7_DEP_MISMATCH**: REUSED_WORKSPACE
- **S1_DOWNLOAD_TIMEOUT**: REUSED_WORKSPACE
- **S0_HEALTHY**: REUSED_WORKSPACE
- **S8_ACTIVATE_ROLLBACK**: REUSED_WORKSPACE
- **S5_STORAGE_FULL**: REUSED_WORKSPACE
- **S3_UDS_NRC72**: REUSED_WORKSPACE

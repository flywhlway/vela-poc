---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: 真实 LLM 生产级可信化与双驱动架构升级
status: executing
stopped_at: Completed 03-02-PLAN.md
last_updated: "2026-08-01T06:02:01.648Z"
last_activity: 2026-08-01
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 21
  completed_plans: 16
  percent: 33
---

# Project State

## Current Position

Phase: 3
Plan: 3 of 7
Status: Ready to execute
Last activity: 2026-08-01
Total Plans in Phase: 7

**Progress:** [████████░░] 76%

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| Phase 01-llm P02 | 6min | 2 tasks | 6 files |
| Phase 01-llm P01 | 1min | 3 tasks | 3 files |
| Phase 01-llm P03 | 3min | 3 tasks | 3 files |
| Phase 01-llm P04 | 3min | 3 tasks | 4 files |
| Phase 01-llm P05 | 3min | 3 tasks | 6 files |
| Phase 01-llm P06 | 3min | 2 tasks | 2 files |
| Phase 01-llm P07 | 3min | 2 tasks | 2 files |
| Phase 01 P08 | continuation | 2 tasks | 8 files |
| Phase 03 P01 | 4min | 2 tasks | 3 files |
| Phase 03 P02 | 3min | 2 tasks | 4 files |

## Decisions

- [Phase 01]: D-01 落地口径：「能用成熟三方开源库解决的一律不手写实现；新增依赖只需满足纯本地可安装、不引入必须联网才能跑通主链路的服务」——四份权威文档口径已对齐（01-02）
- [Phase 01]: 五层配置优先级链「显式函数参数 > 进程环境变量 > .env > config/*.yaml > 代码内默认值」已写入 STACK.md；Plan 03 须逐字复制到 config.py docstring（01-02）
- [Phase 01]: ENV-01 由 Plan 01/02/03/08 共同交付，完成勾选留给 Plan 08 实测验收（01-02）
- [Phase 01]: 解释器约定：所有 make/pytest 用 PYTHON=.venv/bin/python3（01-01） — 系统 python3 缺 duckdb/pyarrow；install-dev 装进 .venv，后续 Plan 沿用
- [Phase 01]: python-dotenv/openai 为必需依赖（D-03），realllm 默认排除（D-19）（01-01） — Task2 人工 approved 后写入；付费用例默认不被 make test 收集
- [Phase 01]: dotenv_report() 契约固定为 {path, loaded, keys, shadowed}，只含键名绝不含值——供 Plan 06 doctor 直接消费（01-03）
- [Phase 01]: ENV-01 实现主体已落地（config.py 导入期静默加载 + conftest 锁定），REQUIREMENTS.md 勾选仍留给 Plan 08 实测验收（01-03）
- [Phase 01]: PYTHONHASHSEED 是 conftest 唯一保留的 setdefault——运行期赋值对哈希随机化无效（01-03）
- [Phase 01]: Open Question 2：删除 llm.yaml 死键（chat_path/embed_path/retry_backoff_s），不保留注释标注失效——死键诱导运维改不生效的值（01-04）
- [Phase 01]: Open Question 3：SDK 异常一律包成 LLMError 并继续走降级链，不引入不可重试中断（01-04）
- [Phase 01]: probe() 返回固定五键 dict + 八类 SDK 异常归因表，供 Plan 06 doctor 用 hasattr 消费；不扩展 Provider 契约（01-04）
- [Phase 01]: EnvChecker 放 src/vela/ 顶层；返回 {name,ok,detail,kind}；env_checks.yaml 不进 config_hash（01-05）
- [Phase 01]: mask_secret：前 keep 后 keep + 固定 4 星，阈值 keep*2+4；掩码在 EnvChecker 数据层统一施加（01-05）
- [Phase 01]: 跳过网络时前三项 warn 跳过；第 4 项仍本地 models_for，保证输出含四个逻辑模型名（01-06）
- [Phase 01]: doctor --json 顶层键：vela_version/python/config_dir/config_hash/provider/probed/dotenv/checks/checks_passed/local_ok——供 Phase 2 环境指纹（01-06）
- [Phase 01]: rc∈{0,3} 均视为 diagnose 链路走完；不把 rc==0 作硬断言（D-19）（01-07）
- [Phase 01]: 付费用例模块级 pytestmark=realllm + autouse 凭证守卫；报告取 sessions/*.state.json（01-07）
- [Phase 01]: 方舟 BASE_URL 同时接受 /api/v3 与 /api/plan/v3；形态坏例改用 /api/v2（01-08）
- [Phase 01]: realllm doctor 连通性断言收紧为四项全绿；ENV 四条需求在 Plan 08 实测后统一勾选（01-08）
- [Phase 02]: 规划为 6 plans / 4 waves；Wave1 并行闸门+指纹+缓存成本；METR-09/PERF-01 收尾 Plan 06；ADR-2 禁止改 graph 推理
- [Phase 03]: Wave 0 不改生产代码；旧 excluded 测保留，新 unproductive_only xfail 锁定契约（03-01）
- [Phase 03]: ORCH 需求勾选留给实现 plan；03-01 仅建立采样连续性（03-01）
- [Phase 03]: 空 dict 视为解析失败并重试；跨段 find/rfind 分支删除（03-02）
- [Phase 03]: truncation 观测落在 AgentGraph._llm；单测用 object.__new__ 避免 test-fast 拉 built（03-02）

## Session

Last session: 2026-08-01T06:02:01.643Z
Stopped at: Completed 03-02-PLAN.md
Resume file: None

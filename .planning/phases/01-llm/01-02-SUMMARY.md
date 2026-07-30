---
phase: 01-llm
plan: 02
subsystem: docs
tags: [dependency-policy, config-priority-chain, python-dotenv, openai, documentation, d-01, d-10]

requires:
  - phase: 01-llm 讨论阶段（01-CONTEXT.md）
    provides: D-01 依赖纪律项目级永久变更、D-02 保留铁律清单、D-10 五层优先级链原文
provides:
  - AGENTS.md / PROJECT.md / REQUIREMENTS.md / STACK.md 四份权威文档的 D-01 新纪律口径（「三方库优先」）
  - STACK.md 中五层配置优先级链逐字文本（供 Plan 03 复制到 `src/vela/config.py` docstring）
  - AGENTS.md 中 `realllm` pytest 标记语义登记（供 Plan 01 注册、Plan 07 编写用例）
affects: [01-01, 01-03, 01-04, phase-02, phase-03, phase-04, phase-05, phase-06]

tech-stack:
  added: []  # 纯文档计划；python-dotenv / openai 的 manifest 落盘归 Plan 01
  patterns: [五层配置优先级链「显式函数参数 > 进程环境变量 > .env > config/*.yaml > 代码内默认值」]

key-files:
  created: []
  modified:
    - AGENTS.md
    - .planning/PROJECT.md
    - .planning/REQUIREMENTS.md
    - .planning/codebase/STACK.md
    - README.md
    - Makefile

key-decisions:
  - "D-01 落地口径：「能用成熟三方开源库解决的一律不手写实现；新增依赖只需满足纯本地可安装、不引入必须联网才能跑通主链路的服务」（T-02-02 限定显式保留）"
  - "五层优先级链在 STACK.md 中按 D-10 原文书写且不加反引号包裹，保证与 Plan 03 将写入 config.py docstring 的文本逐字一致"
  - "ENV-01 由 Plan 01/02/03/08 四个 plan 共同交付，本 plan 仅完成需求原文改写；完成勾选留给 Plan 08 实测验收后执行，避免追踪表提前虚报"

patterns-established:
  - "文档级 D-01 纪律表述 = 新纪律 + 本地优先限定 + 当前依赖清单三要素齐备，后续阶段引用时不得裁掉限定语"

requirements-completed: []  # ENV-01 为多 plan 共同交付，见 key-decisions 第 3 条

duration: 6min
completed: 2026-07-31
---

# Phase 1 Plan 2: 依赖纪律（D-01）与五层配置优先级链（D-10）文档口径改写 Summary

**四份权威文档 + README + Makefile help 完成 D-01「三方库优先」纪律口径替换，STACK.md 落地 D-10 五层优先级链（含 `.env` 层）并登记 `override=False` 静默加载语义，D-02 保留的其余架构铁律经 grep 正向断言逐条仍在。**

## Performance

- **Duration:** 约 6 min
- **Started:** 2026-07-30T17:57:06Z
- **Completed:** 2026-07-30T18:02:30Z
- **Tasks:** 2 / 2
- **Files modified:** 6

## Accomplishments

- AGENTS.md 代码约定中「依赖最小化」条目替换为「三方库优先」新纪律（含 D-01 项目级永久变更标注与本地优先限定），pytest 标记清单补登 `realllm` 语义
- PROJECT.md §Constraints 的 Tech stack 条目、REQUIREMENTS.md ENV-01 括号约束同步改写，旧口径（`依赖最小化是既定纪律` / `先评估 stdlib` / `stdlib 实现，不新增运行期依赖`）在三份文档中归零
- STACK.md 优先级链改写为五层并新增 `.env` 自动加载条目（模块导入时一次、`override=False`、完全静默、命中路径与被遮蔽键名收到 `vela doctor`）；README 与 Makefile help 的依赖清单补齐 `python-dotenv` / `openai`

## 供 Plan 03 复制的逐字文本

五层优先级链（写入 `.planning/codebase/STACK.md` 第 68 行，Plan 03 须逐字复制到 `src/vela/config.py` docstring）：

```
显式函数参数 > 进程环境变量 > .env > config/*.yaml > 代码内默认值
```

## Task Commits

Each task was committed atomically:

1. **Task 1: 改写依赖纪律口径（AGENTS.md / PROJECT.md / REQUIREMENTS.md）** - `0d34ebf` (docs)
2. **Task 2: 改写配置加载优先级链与依赖清单（STACK.md / README.md / Makefile）** - `c8faca4` (docs)

**Plan metadata:** 见文末最终提交（docs: complete plan）

## Files Created/Modified

- `AGENTS.md` - 依赖纪律条目改写 + `realllm` 标记登记（仅 2 行变动，D-02 保留项零改动）
- `.planning/PROJECT.md` - §Constraints Tech stack 条目改为 D-01 新纪律表述（仅 1 行变动）
- `.planning/REQUIREMENTS.md` - ENV-01 括号约束改写 + §ENV 引言补注「stdlib 约束已被 D-01 推翻」
- `.planning/codebase/STACK.md` - 五层优先级链 + `.env` 自动加载条目 + 必需依赖补 2 项（计数 4→6）
- `README.md` - 目录树中 `requirements.txt` 依赖描述补 2 项
- `Makefile` - 仅 help 的 `@echo` 行补 2 个依赖名，全部目标命令体零改动

## Decisions Made

- **ENV-01 不在本 plan 勾选完成**：frontmatter `requirements: [ENV-01]` 标记的是贡献范围（本 plan 交付「需求原文改写」部分）；ENV-01 的功能交付（`.env` 真正被自动加载）依赖 Plan 01（依赖落盘）、Plan 03（实现）、Plan 08（实测验收）。提前勾选会让 Traceability 表虚报，完成标记留给 Plan 08。
- **五层链文本不加反引号**：STACK.md 原行的 `config/*.yaml` 有反引号包裹，改写后链条本体（`.env` 与 `config/*.yaml`）均不加反引号——验收 grep 模式与 Plan 03 docstring 均为无包裹纯文本，两处必须逐字一致。
- **新纪律文案显式保留本地优先限定**：「纯本地可安装、不引入必须联网才能跑通主链路的服务」写入 AGENTS.md 与 PROJECT.md 两处，防止 D-01 被读成「任意依赖均可引入」（威胁登记 T-02-02）。

## Deviations from Plan

None - plan executed exactly as written.

（说明：plan 验收串末尾的 `wc -l | grep -qx '0'` 在 macOS 下因 `wc -l` 输出前导空格永不匹配，属验证脚本的可移植性问题而非计划内容偏差；实际断言意图「Makefile 增删行全部落在 @echo」已用等价的 `wc -l | tr -d ' ' | grep -qx '0'` 验证通过，计数为 0。）

## Issues Encountered

- plan 自带 verify 命令在 macOS 下末段恒失败（`wc -l` 前导空格 vs `grep -qx '0'`）。逐项拆分运行确认全部断言实质通过，`make help` 退出码 0，Makefile 非 @echo 增删行数为 0。未改动任何计划内容。

## User Setup Required

None - no external service configuration required.

## Threat Model 处置核对

| Threat ID | 处置 | 核对结果 |
|-----------|------|---------|
| T-02-01 | 只改依赖纪律一条 + 标记清单一行 | `git diff AGENTS.md` 仅 2 行；`查询唯一收口` / `gateway/redact.py` / `不使用 logging 模块` / `PARSE_UNPARSED` / `不吞异常` grep 正向断言全部 ≥1 |
| T-02-02 | 新纪律显式保留本地优先限定 | AGENTS.md 与 PROJECT.md 两处均含「纯本地可安装、不引入必须联网才能跑通主链路的服务」 |
| T-02-03 | `.env` 说明只写变量名与语义 | STACK.md 新增条目无任何形似真实 key 的值 |
| T-02-04 | Makefile 仅 @echo 变动 | `git diff -U0 Makefile` 增删行 100% 落在 `@echo`，`make help` 退出码 0 |

## Next Phase Readiness

- Plan 03 可直接复制本 SUMMARY 中的五层链逐字文本到 `config.py` docstring；STACK.md 与 docstring 两处表述一致性已有锚点
- Plan 01 注册 `realllm` 标记时可引用 AGENTS.md 第 34 行的语义定义，保持两处口径一致
- 后续 Phase 2~6 的依赖选型读到的是 D-01 新纪律，无需再逐案报批

## Self-Check: PASSED

- 全部 6 个改动文件 + 本 SUMMARY 均存在于磁盘
- 任务提交 `0d34ebf`（Task 1）、`c8faca4`（Task 2）均存在于 git 历史
- 无文件删除（两次提交 `git diff --diff-filter=D` 均为空）

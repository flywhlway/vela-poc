---
phase: 01-llm
plan: 03
subsystem: infra
tags: [python-dotenv, dotenv, config, ENV-01, conftest, override=False]

requires:
  - phase: 01-llm/01-01
    provides: python-dotenv 必需依赖已安装；realllm 默认排除
  - phase: 01-llm/01-02
    provides: 五层优先级链逐字文本（STACK.md / 本 SUMMARY 复制源）
provides:
  - config.py 模块导入期静默加载项目根 .env（override=False）
  - dotenv_report() 供 Plan 06 cmd_doctor 消费（只出键名不出值）
  - conftest 测试作用域锁定（VELA_LLM_PROVIDER=mock 无条件赋值）
  - 十条约回归护栏（优先级 / 锚点 / 静默 / report / provider 锁定）
affects: [01-llm/01-06, 01-llm/01-07, 01-llm/01-08]

tech-stack:
  added: []
  patterns:
    - "锚点回溯 _find_project_root（pyproject.toml|.git），不用 find_dotenv(usecwd=True)"
    - "root 可注入的 _apply_dotenv(root) 便于单测脱离真实 .env"
    - "conftest 先无条件写死 → 再 import 触发 override=False 加载"

key-files:
  created:
    - tests/test_dotenv_loading.py
  modified:
    - src/vela/config.py
    - tests/conftest.py

key-decisions:
  - "dotenv_report() 契约固定为 {path, loaded, keys, shadowed}，只含键名绝不含值——供 Plan 06 doctor 直接消费"
  - "ENV-01 实现主体已落地，完成勾选仍留给 Plan 08 实测验收（沿用 01-02 决策）"
  - "PYTHONHASHSEED 是 conftest 唯一保留的 setdefault（运行期赋值无效）"

patterns-established:
  - "Pattern: 模块导入期一次性 _load_dotenv_once() 幂等守卫 + 模块末尾调用"
  - "Pattern: 测试作用域变量无条件赋值，凭证键仍由 .env 以 override=False 灌入"

requirements-completed: [ENV-01]  # 实现主体本 plan 交付；REQUIREMENTS.md 勾选留给 Plan 08 实测验收

duration: 3min
completed: 2026-07-30
---

# Phase 1 Plan 3: .env 静默加载与测试作用域锁定 Summary

**`config.py` 导入期用 python-dotenv 一次性静默加载项目根 `.env`（`override=False`），暴露 `dotenv_report()`；conftest 无条件锁死 mock provider，十条约回归护栏全绿，全量 187 测试通过（基线 177 + 10）。**

## Performance

- **Duration:** 3min
- **Started:** 2026-07-30T23:19:41Z
- **Completed:** 2026-07-30T23:22:42Z
- **Tasks:** 3（含 Task 1 TDD RED+GREEN）
- **Files modified:** 3

## Accomplishments

- 五层优先级链逐字写入 `config.py` docstring；模块导入零 stdout/stderr
- `_find_project_root` 锚点回溯 + `_apply_dotenv(root)` 可注入；site-packages 无锚点时静默跳过
- conftest 将 `VELA_LLM_PROVIDER` / `VELA_CONFIG_DIR` / `VELA_PROFILE` 改为无条件赋值，杜绝 `.env` 中 `volcengine` 打付费 API
- 优先级规则（ROADMAP 成功判据 1）、锚点、静默性、report 不泄值、provider 锁定均有专门单测

## 供 Plan 06 消费：`dotenv_report()` 契约

返回浅拷贝 `dict`，**只含键名、永不含值**：

| 键 | 类型 | 含义 |
|----|------|------|
| `path` | `str \| None` | 命中的 `.env` 绝对路径；未加载则为 `None` |
| `loaded` | `bool` | 是否实际执行了 `load_dotenv` |
| `keys` | `list[str]` | 文件中声明的全部键名（已排序） |
| `shadowed` | `list[str]` | 因进程环境已存在而未被覆盖的键名（已排序） |

调用方修改返回值不影响模块内部 `_DOTENV_STATE`。

## Task Commits

1. **Task 1 RED: 失败用例** - `e724157` (test)
2. **Task 1 GREEN: config.py 静默加载** - `73ecf21` (feat)
3. **Task 2: conftest 作用域锁定** - `7e41fcf` (fix)
4. **Task 3: provider 锁定护栏补齐** - `552ac46` (test)

**Plan metadata:** `4c8bad6` (docs: complete plan)

## Files Created/Modified

- `src/vela/config.py` - `_find_project_root` / `_apply_dotenv` / `_load_dotenv_once` / `dotenv_report`；导入期调用；`config_hash` 与 `_DEFAULT_CONFIG_DIR` 零改动
- `tests/conftest.py` - 三变量无条件赋值 + `PYTHONHASHSEED` 保留 setdefault 及因果链注释
- `tests/test_dotenv_loading.py` - 10 条护栏（含浅拷贝契约）

## Decisions Made

- **report 四键契约**：与威胁模型 T-03-02 对齐，Plan 06 doctor 不得从此处读到凭证值
- **ENV-01 不在本 plan 勾选完成**：实现已满足「仅凭 .env 可读到凭证」与优先级单测；勾选留给 Plan 08 实测验收（01-02 既定）
- **额外浅拷贝用例**：Task 1 `<behavior>` 要求 `dotenv_report()` 浅拷贝，故保留 `test_dotenv_report_returns_shallow_copy`（共 10 条，≥ 计划 9 条）

## Deviations from Plan

None - plan executed exactly as written.

（ENV-01 不调用 `requirements.mark-complete` 是沿用 01-02 决策，非偏差。）

## Issues Encountered

None

## User Setup Required

None - 依赖项目根已有 `.env`（已被 `.gitignore`）；加载对调用方透明。

## Next Phase Readiness

- Plan 04 可安全改 openai SDK：测试会话 provider 已锁 mock
- Plan 06 可直接 `from vela.config import dotenv_report` 渲染 doctor 的 `.env` 加载事实
- Plan 07/08 的 `realllm` 用例需自行 `monkeypatch.setenv("VELA_LLM_PROVIDER", "volcengine")`

## TDD Gate Compliance

- RED: `e724157` test(01-03)
- GREEN: `73ecf21` feat(01-03)
- REFACTOR: 未需要单独提交

## Self-Check: PASSED

- FOUND: `src/vela/config.py`, `tests/conftest.py`, `tests/test_dotenv_loading.py`, `01-03-SUMMARY.md`
- FOUND: commits `e724157`, `73ecf21`, `7e41fcf`, `552ac46`

---
*Phase: 01-llm*
*Completed: 2026-07-30*

---
phase: 01-llm
plan: 05
subsystem: env-diagnostics
tags: [mask_secret, EnvChecker, env_checks.yaml, ENV-04, D-16, D-17, dotenv]

requires:
  - phase: 01-llm/01-01
    provides: python-dotenv 已安装；解释器约定 .venv/bin/python3
provides:
  - mask_secret(value, keep=4) 前 keep 后 keep + 固定 4 星掩码（D-17）
  - config/env_checks.yaml 形态检查规则表（不进 config_hash）
  - EnvChecker(cfg=...).run(provider, environ=...) → list[{name,ok,detail,kind}]
  - .env.example 无行尾注释，含 FALLBACK/PLANNER 与 override=False 说明
affects: [01-llm/01-06, 01-llm/01-07, 01-llm/01-08]

tech-stack:
  added: []
  patterns:
    - "cfg 可注入 + 默认 load_yaml（照抄 Redactor 构造器形状）"
    - "掩码在 EnvChecker 数据层统一施加，人读与 --json 同源（D-18）"
    - "形态规则全部进 YAML；envcheck.py 零硬编码变量名（T-05-06）"

key-files:
  created:
    - config/env_checks.yaml
    - src/vela/envcheck.py
    - tests/test_envcheck.py
  modified:
    - src/vela/util/textutil.py
    - tests/test_util.py
    - .env.example

key-decisions:
  - "EnvChecker 放 src/vela/ 顶层（非 gateway/）——跨越网关与运行期变量，直接被 CLI 消费"
  - "pattern 用 re.fullmatch；value_hygiene 用 re.search；空串视为未设置"
  - "env_checks.yaml 不进 config_hash：零改动 config.py 即满足 D-16"
  - "ENV-04 本 plan 交付形态检查基建与 .env.example 清理并勾选完成；doctor 接线属 Plan 06"

patterns-established:
  - "Pattern: 检查结果 {name, ok, detail, kind}；kind 固定 local 供退出码分层"
  - "Pattern: display=masked → mask_secret；display=plain → 明文（base_url / ep-xxxx）"
  - "Pattern: 未设置且 provider∉required → ok=True +「未设置（当前 provider 不需要）」"

requirements-completed: [ENV-04]

duration: 3min
completed: 2026-07-30
---

# Phase 1 Plan 5: ENV-04 形态检查基建 Summary

**`mask_secret` + 配置驱动 `EnvChecker`/`env_checks.yaml` 就位：`/api/plan/v3` 可被判异常并提示正确 `/api/v3`；密钥 detail 前 4 后 4 掩码；`.env.example` 行尾注释清零；`config_hash` 零触碰。**

## Performance

- **Duration:** 3min
- **Started:** 2026-07-30T23:29:39Z
- **Completed:** 2026-07-30T23:32:02Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- `mask_secret`：空值返回空、短值全掩、前 4 后 4 + 固定 4 星、`keep` 可调阈值
- `config/env_checks.yaml`：`value_hygiene` ×3 + `variables` ×9；文件头声明不进 `config_hash`
- `EnvChecker`：`cfg`/`environ` 双注入；返回契约钉死；真实 YAML 对 `/api/plan/v3` 判失败
- `.env.example`：行尾注释改独占行；补 `VELA_ARK_MODEL_FALLBACK` / `VELA_ARK_MODEL_PLANNER`；说明自动加载

## Task Commits

1. **Task 1 RED: mask_secret 失败用例** - `1a4fcea` (test)
2. **Task 1 GREEN: 实现 mask_secret** - `c3850e7` (feat)
3. **Task 2 RED: EnvChecker 失败用例** - `4d7efcc` (test)
4. **Task 2 GREEN: env_checks.yaml + EnvChecker** - `00b8d55` (feat)
5. **Task 3: 清理 .env.example** - `bca9d21` (chore)

**Plan metadata:** （本 SUMMARY 提交后回填）

## 供 Plan 06 消费：`EnvChecker.run()` 契约

### 返回 list[dict] 四键

| 键 | 类型 | 含义 |
|----|------|------|
| `name` | `str` | 环境变量名（与 YAML `variables[].name` 一致） |
| `ok` | `bool` | 该项是否通过 |
| `detail` | `str` | 人读/JSON 共用详情；`display=masked` 时值已掩码 |
| `kind` | `str` | 固定 `"local"`——形态错误属 D-14 本地硬错误（退出码 1） |

字段名 `name`/`ok`/`detail` 对齐 `evidence/qa.py`；`kind` 供 doctor 做退出码分层。

### 判定顺序（每变量）

1. 未设置（`None` 或空串）→ `provider ∈ required_for_providers` 则失败并附 `hint`，否则 `ok=True`「未设置（当前 provider 不需要）」
2. 已设置 → 先跑全部 `value_hygiene`（`re.search`），任一命中失败
3. 再跑 `pattern`（`re.fullmatch`，空 pattern 跳过），不匹配则附变量 `hint`

### `env_checks.yaml` schema

```yaml
version: "1.0"
value_hygiene:          # 通用值形态；对已设置值统一应用
  - name: str
    pattern: str        # 正则
    hint: str           # 中文修复指引
variables:
  - name: str
    display: plain | masked
    required_for_providers: [provider, ...]  # 空 = 任何 provider 不必填
    pattern: str        # 可空 = 不校验形态
    hint: str
```

已覆盖变量：`VELA_LLM_PROVIDER`、`VELA_ARK_BASE_URL`、`VELA_ARK_API_KEY`、`VELA_ARK_MODEL`、`VELA_ARK_EMBED_MODEL`、`VELA_OPENAI_BASE_URL`、`VELA_OPENAI_API_KEY`、`VELA_OPENAI_MODEL`、`VELA_PROFILE`。

### 调用示例（Plan 06）

```python
from vela.envcheck import EnvChecker
checks = EnvChecker().run(provider)          # environ 默认 os.environ
# 或 EnvChecker(cfg=...).run(provider, environ={...})  # 单测注入
local_hard = any(not c["ok"] for c in checks)  # True → doctor 退出码 1
```

## Files Created/Modified

- `src/vela/util/textutil.py` — 新增 `mask_secret`
- `tests/test_util.py` — mask_secret 六条行为护栏
- `config/env_checks.yaml` — ENV-04 规则表（新建）
- `src/vela/envcheck.py` — EnvChecker（新建）
- `tests/test_envcheck.py` — 9 个注入式用例（新建）
- `.env.example` — 无行尾注释 + FALLBACK/PLANNER + 自动加载说明

## Decisions Made

- 模块路径放 `src/vela/envcheck.py`（计划裁定），非 `gateway/`
- 空值一律当未设置，避免 `.env` 里 `KEY=` 被当成已配置
- `.gitignore` 已正确覆盖 `.env` / `!.env.example`，本 plan 未改动

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None — 纯本地基建；凭证仍由用户既有 `.env` 提供。

## Known Stubs

None

## Threat Flags

None — 威胁面均在计划 `<threat_model>` 内（T-05-01…06 已落实：掩码在数据层、样例无真实凭证、`.env` 被 ignore、`config_hash` 零改动、测试用 DUMMY- 前缀、规则全进 YAML）。

## Verification

- `make test-fast` 通过
- `pytest tests/test_envcheck.py tests/test_util.py` 全部通过
- `git diff src/vela/config.py` 为空
- 真实 YAML：`EnvChecker().run('volcengine', {BASE_URL: .../api/plan/v3})` → `ok=False` 且 detail 含 `/api/v3`
- `.env.example`：`dotenv_values` 解析后无值含 `#`；密钥右侧为空

## TDD Gate Compliance

- RED → GREEN 齐全：`1a4fcea`/`c3850e7`（mask_secret）、`4d7efcc`/`00b8d55`（EnvChecker）

## Next Phase Readiness

- Plan 06 可直接 `from vela.envcheck import EnvChecker`，将 `run()` 结果并入 doctor 的 `checks`，按 `kind=="local"` 且 `ok=False` 返退出码 1
- `dotenv_report()`（Plan 03）+ `EnvChecker`（本 plan）+ `probe()`（Plan 04）构成 doctor 三块数据源

## Self-Check: PASSED

- 文件存在：`textutil.py` / `env_checks.yaml` / `envcheck.py` / `test_envcheck.py` / `.env.example` / `01-05-SUMMARY.md`
- 提交存在：`1a4fcea` `c3850e7` `4d7efcc` `00b8d55` `bca9d21`

---
*Phase: 01-llm*  
*Plan: 05*  
*Completed: 2026-07-30*

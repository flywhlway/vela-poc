---
phase: 01-llm
reviewed: 2026-07-31T15:16:41Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - src/vela/config.py
  - src/vela/cli.py
  - src/vela/gateway/openai_compat.py
  - src/vela/gateway/volcengine.py
  - src/vela/envcheck.py
  - src/vela/util/textutil.py
  - config/env_checks.yaml
  - config/llm.yaml
  - tests/conftest.py
  - tests/test_realllm.py
  - tests/test_doctor.py
  - run_all.sh
findings:
  critical: 1
  warning: 5
  info: 3
  total: 9
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-31T15:16:41Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found
**Requirements:** ENV-01, ENV-02, ENV-03, ENV-04

## Summary

Phase 01 的核心交付（`.env` 静默加载、openai SDK provider、`EnvChecker`、`doctor` 双通道与退出码分层、`realllm` 默认排除）整体结构清晰，安全面（密钥掩码、probe 硬编码 ping、conftest 锁 mock）大多落实。对抗审查仍发现：**`run_all.sh` 在 `.env` 自动加载后仍宣称「零 API」却未钉死 mock**，以及 **`cmd_doctor` 在形态检查之后仍会因未知 provider / 缺失 `env_checks.yaml` 直接抛栈**，破坏 ENV-03/04 的「结构化自检」契约。

Advisory only — 不阻断合入；建议在进入 Phase 2 前优先处理 CR-01 与 WR-01。

## Critical Issues

### CR-01: `run_all.sh` 宣称零 API / mock，但 diagnose 继承 `.env` 的真实 provider

**File:** `run_all.sh:5-6` 与 `run_all.sh:56-60`
**Issue:** 脚本头注释写明「默认使用 mock 大模型（确定性、零 API 调用）」，第 4 步注释也写 `provider=mock`，但全程未 `export VELA_LLM_PROVIDER=mock`。Phase 01 引入模块导入期 `.env` 加载（`override=False`）后，用户若在 `.env` 写入 `VELA_LLM_PROVIDER=volcengine`，裸跑 `./run_all.sh` 会在第 4 步对真实方舟发起完整 diagnose（付费）。Plan 08 回归门靠 shell 前置 `VELA_LLM_PROVIDER=mock` 掩盖了该缺口；D-12 只明确接受「第 1 步 doctor 联网」，未授权演示诊断默认打真实模型。
**Fix:**
```bash
# run_all.sh 在 export PYTHONPATH 之后固定演示口径（仍允许调用方显式覆盖）
export VELA_LLM_PROVIDER="${VELA_LLM_PROVIDER:-mock}"
# 或更强硬：演示链路无条件钉死
# export VELA_LLM_PROVIDER=mock
```
同步修正第 4 步注释，并在 `Makefile`/`scripts/demo_end_to_end.py` 的默认路径上保持同一语义。

## Warnings

### WR-01: 未知 / 非法 provider 时 `cmd_doctor` 抛栈，形态检查结果无法呈现

**File:** `src/vela/cli.py:230-236`
**Issue:** `EnvChecker().run(provider)` 已能把 `VELA_LLM_PROVIDER=volcengin` 判为本地形态失败，但随后无条件 `build_gateway(provider)`，对未知名抛出未捕获的 `LLMError`。实测：`vela doctor --offline` 只输出 traceback，不渲染 checks / `--json`，ENV-04 提示文案丢失。退出码虽为 1，但不满足「先收集 list[dict] 再双通道渲染」契约。
**Fix:**
```python
try:
    gw = build_gateway(provider)
except Exception as e:  # LLMError / 配置缺失
    checks.append(_doctor_item(
        "provider", False, f"无法构造网关：{e}", kind="local"))
    # 跳过连通性探测，直接进入渲染与 local_bad 退出码
    ...
    return 1 if local_bad else 0
```

### WR-02: 缺失 `env_checks.yaml` 时 doctor 以 `FileNotFoundError` 崩溃

**File:** `src/vela/envcheck.py:16-17`、`src/vela/cli.py:230`
**Issue:** `EnvChecker()` 默认 `load_yaml("env_checks.yaml")`，文件不存在时抛 `FileNotFoundError`。doctor 已检查 `pipeline.yaml` 等，却不检查也不兜底 `env_checks.yaml`。在只缺该诊断规则表时，本可返回 `kind=local` 的硬错误，实际变成栈追踪。
**Fix:**
```python
# cli.py：将 env_checks.yaml 纳入本地配置存在性检查；或
try:
    for item in EnvChecker().run(provider):
        ...
except FileNotFoundError as e:
    checks.append(_doctor_item("env_checks.yaml", False, str(e), kind="local"))
```

### WR-03: `RateLimitError` 被标为三项全绿，易误判「连通性健康」

**File:** `src/vela/gateway/openai_compat.py:182-185`、`src/vela/cli.py:271-285`
**Issue:** 按 Plan 04 归因表，限流时 `reachable/authenticated/model_ok` 均为 `True`，doctor 图标为 ✅，`checks_passed` 亦可为 true，仅靠 detail 文案「限流」。自动化消费 `--json` 的 Phase 2 指纹若只看 `ok`/`checks_passed`，会把限流当成全绿。
**Fix:** 限流时至少一项 `ok=False`，或新增独立检查项 / `warn=True` 且 `ok=False`：
```python
except openai.RateLimitError as e:
    return self._probe_result(
        True, True, False, e, "限流，未能完成最小调用")
```

### WR-04: `_scrub` 仅做精确子串替换，异常回显的变形密钥可能漏掩

**File:** `src/vela/gateway/openai_compat.py:87-91`
**Issue:** 只在 `self.api_key in text` 时整体替换为 `***`。SDK/网关若回显截断密钥、`Bearer …` 分段、或大小写/空白变形，明文片段仍可进入 `LLMError` 与 `probe().detail`（最终进 doctor / 审计 error 字段）。与 `mask_secret` 的防御深度不一致。
**Fix:**
```python
def _scrub(self, text: str) -> str:
    out = text
    if self.api_key:
        out = out.replace(self.api_key, "***")
        # 额外：掩盖疑似密钥片段（按项目密钥前缀扩展）
        out = re.sub(r"(?i)(api[_-]?key|bearer)\s*[:=]?\s*\S+", r"\1=***", out)
    return out
```

### WR-05: `probed` 在未实际调用 `probe` 时仍可能为 true

**File:** `src/vela/cli.py:266-268`、`src/vela/cli.py:305`
**Issue:** `"probed": do_probe and hasattr(prov, "probe")`。当逻辑模型链为空（`physical == []`）时不会调用 `probe`，但 `--json` 仍报 `probed: true`。与 01-06-SUMMARY 对 Phase 2 的契约「本次是否实际调用了 probe」不符，会导致环境指纹误判。
**Fix:**
```python
did_probe = bool(physical) and do_probe and hasattr(prov, "probe")
# ...
"probed": did_probe,
```

## Info

### IN-01: `dotenv_report()` 浅拷贝未隔离内部 list

**File:** `src/vela/config.py:76-78`
**Issue:** `return dict(_DOTENV_STATE)` 后，`report["keys"].append(...)` 仍会改写模块内状态。现有单测只覆盖「重绑键」而非原地变异。doctor JSON 路径已 `list(...)` 拷贝，实际风险低。
**Fix:** `return {**_DOTENV_STATE, "keys": list(...), "shadowed": list(...)}`

### IN-02: `VolcengineArkProvider` 未被 `build_gateway` 使用

**File:** `src/vela/gateway/volcengine.py:24-28`、`src/vela/gateway/base.py:168-170`
**Issue:** `kind: openai_compatible` 一律实例化 `OpenAICompatProvider`；`VolcengineArkProvider` 仅为文档别名死路径。不影响行为，但易让后续维护者误以为审计 `provider` 名来自该类。
**Fix:** 在 `build_gateway` 对 `name=="volcengine"` 使用别名类，或删除别名并在文档标明仅配置名区分。

### IN-03: `config_dir()` 默认路径仍用 `parents[2]`，与 `.env` 锚点回溯不一致

**File:** `src/vela/config.py:19`、`src/vela/config.py:37`、`src/vela/config.py:81-82`
**Issue:** `.env` 已用 `_find_project_root` 处理 site-packages；`_DEFAULT_CONFIG_DIR` 仍假设 src 布局。非 editable 安装且未设 `VELA_CONFIG_DIR` 时，可能「跳过 .env」却指向错误 config 目录。POC 主路径为 editable / Makefile 显式 `VELA_CONFIG_DIR`，暂为遗留缺口。
**Fix:** 默认 config 目录改为 `(_PROJECT_ROOT / "config") if _PROJECT_ROOT else ...`，与 D-07 同源。

---

_Reviewed: 2026-07-31T15:16:41Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

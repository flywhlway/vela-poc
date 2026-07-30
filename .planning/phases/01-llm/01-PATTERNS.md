# Phase 1: 真实 LLM 环境就绪 - Pattern Map

**Mapped:** 2026-07-31
**Files analyzed:** 14（新建 4 / 修改 10，文档类合并计 1）
**Analogs found:** 12 / 14

> 本阶段无 RESEARCH.md（用户 `--skip-research`）。文件清单从 `01-CONTEXT.md` 的 `<canonical_refs> → 实现对象` 与 `<code_context> → Integration Points` 提取。
> 所有代码摘录均为**当前代码库真实内容**，行号已核对。planner 直接引用即可，不需重新搜索。

---

## File Classification（文件分类与类比对照）

| 新建/修改文件 | 角色 | 数据流 | 最近类比 | 匹配度 |
|---|---|---|---|---|
| `src/vela/config.py`（挂 `load_dotenv()`） | config-loader | 模块导入期一次性初始化 | `src/vela/config.py:17-21` 自身的 `_DEFAULT_CONFIG_DIR` / `config_dir()` | exact（同文件既有模式） |
| `src/vela/gateway/openai_compat.py`（SDK 重写） | provider-adapter | request-response | `src/vela/gateway/base.py:62-70` `Provider` 契约 + `src/vela/gateway/mock.py` 另一实现 | exact |
| **新建** env 检查消费模块（路径 planner 定） | validator-service | 规则驱动 → `list[dict]` | `src/vela/gateway/redact.py:21-43` `Redactor` | exact |
| `src/vela/cli.py::cmd_doctor`（四项自检 + 双通道） | cli-command | 检查 → `list[dict]` → 双通道渲染 | `src/vela/evidence/qa.py:41-102`（checks → JSON + MD）；`src/vela/cli.py:144-162` `cmd_evidence` | exact |
| `src/vela/cli.py::build_parser()`（doctor flags） | cli-arg-registration | — | `src/vela/cli.py:225-231`（query 的 `--list`）+ `:233-243`（agent 的 `--json-out`） | exact |
| doctor 退出码分层（D-14） | cli-exit-code | — | `src/vela/cli.py:63` / `:85` / `:118` / `:140` / `:162` / `:198` | exact |
| **新建** `config/env_checks.yaml` | config-rules | 规则表 | `config/llm.yaml:56-66` `redaction.rules` + `config/parsers.yaml:8-15` | exact |
| API key 掩码（D-17） | utility | transform | `src/vela/util/textutil.py:66-71` `mask_vin()` | role-match（需改成前 4 后 4） |
| `tests/conftest.py:12-15` | test-config | 进程环境初始化 | 自身第 12-15 行 | exact |
| `pyproject.toml`（`realllm` 标记 + 依赖） | manifest | — | `pyproject.toml:11-22` / `:33-39` | exact |
| `requirements.txt` | manifest | — | `requirements.txt:1-5`（必需）vs `requirements-optional.txt:1-6`（可选） | exact |
| **新建** `.env` 优先级 / doctor 单测 | test-unit | — | `tests/test_gateway.py:143-164` + `tests/test_cli_and_server.py:9-13` | exact |
| **新建** `realllm` 标记端到端用例 | test-e2e | — | `tests/test_cli_and_server.py:58-64` | partial（marker 排除机制无先例，见「No Analog Found」） |
| `.env.example` 注释重排 | config-template | — | `.env.example:10-11` 自身已有的「注释在变量上一行」段落 | exact |
| 文档改写 ×4（REQUIREMENTS / PROJECT / AGENTS / STACK） | docs | — | n/a | n/a |

---

## Pattern Assignments（逐文件模式指派）

### 1. `src/vela/config.py` — 挂载 `.env` 加载（D-06/D-07/D-08/D-09/D-10）

**类比：** `src/vela/config.py` 自身（同文件已有「项目根推导 + 模块级常量」模式）

**项目根推导 + 模块级常量**（第 17-21 行，D-07 要求与之同源）：

```python
_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def config_dir() -> Path:
    return Path(os.environ.get("VELA_CONFIG_DIR", str(_DEFAULT_CONFIG_DIR))).resolve()
```

> ⚠️ `parents[2]` 在 `pip install -e .` 下 = 项目根，常规安装到 site-packages 后不成立（CONTEXT Open Questions 第 1 条）。planner 需在此基础上加兜底（`find_dotenv()` 回溯 / `.git`·`pyproject.toml` 锚点检测 / 静默跳过择一）。

**需按 D-10 改写的 docstring**（第 1-6 行，当前为四层）：

```python
"""
配置加载：YAML + 环境变量覆盖。

优先级（高 -> 低）： 显式函数参数 > 环境变量 > config/*.yaml > 代码内默认值
生产接入切换点全部收敛在这里，业务代码不读 os.environ。
"""
```

改后应为：`显式函数参数 > 进程环境变量 > .env > config/*.yaml > 代码内默认值`。

**imports 惯例**（第 7-15 行，新增 `dotenv` 导入按此风格并入 stdlib 段之后、第三方段之内）：

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
```

**幂等 + 缓存惯例**（第 28-34 行，`load_dotenv` 的「只加载一次」可复用同一思路，或直接用模块级 `_LOADED` 标记）：

```python
@lru_cache(maxsize=32)
def load_yaml(name: str) -> dict[str, Any]:
    p = config_dir() / name
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {p}（可用 VELA_CONFIG_DIR 指定目录）")
    with open(p, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
```

**D-09「完全静默」的既有依据：** 本文件模块层零 `print()`，只有函数体内抛异常。`load_dotenv()` 调用点必须保持这一性质。

**D-16「不进 `config_hash`」的既有依据**（第 125-143 行）：`config_hash()` **显式枚举** 三个 YAML，新增 `env_checks.yaml` 默认不会被纳入 —— 零改动即满足 D-16，planner 只需**不去动**这段：

```python
payload = canonical_json({
    "pipeline": load_yaml("pipeline.yaml"),
    "parsers": load_yaml("parsers.yaml"),
    "phases": load_yaml("ota_phases.yaml"),
    "canon_rules_version": canon_rules_version(),
    "algos": fingerprint_algos(),
})
```

---

### 2. `src/vela/gateway/openai_compat.py` — openai SDK 重写（D-04）

**类比：** `src/vela/gateway/base.py::Provider`（契约）+ `src/vela/gateway/mock.py`（另一实现）

**必须保持的接口签名边界**（`base.py:62-70`，**不得改动**）：

```python
class Provider:
    """供应商适配器接口。新增供应商只需实现 complete()。"""
    name = "base"

    def models_for(self, logical_model: str) -> list[str]:
        raise NotImplementedError

    def complete(self, req: LLMRequest, physical_model: str, params: dict) -> LLMResponse:
        raise NotImplementedError
```

**必须原样保留的 `models_for()`**（`openai_compat.py:31-59`，CONTEXT 明示「解析与降级链逻辑保留不变」，同时是 D-15 第 2 项的现成实现）：

```python
def models_for(self, logical_model: str) -> list[str]:
    """物理模型解析顺序：逻辑模型专属环境变量 → 通用 model_env → 降级链。"""
    out: list[str] = []
    base_env = self.cfg.get("model_env", "")
    if base_env:
        v = os.environ.get(f"{base_env}_{logical_model.upper()}")
        if v:
            out.append(v)
        v = os.environ.get(base_env)
        if v:
            out.append(v)
    d = self.cfg.get("model_default") or ""
    if d:
        out.append(d)
    for env in self.cfg.get("fallback_chain", []) or []:
        v = os.environ.get(env)
        if v:
            out.append(v)
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq
```

**构造器：配置读取惯例**（第 17-28 行，SDK 客户端构造须沿用「全部字段从 `self.cfg` + 环境变量取，零厂商硬编码」）：

```python
def __init__(self, cfg: dict, name: str = "openai_compat"):
    self.name = name
    self.cfg = cfg or {}
    self.base_url = (os.environ.get(self.cfg.get("base_url_env", ""), "")
                     or self.cfg.get("base_url_default", "")).rstrip("/")
    self.api_key = os.environ.get(self.cfg.get("api_key_env", ""), "")
    self.chat_path = self.cfg.get("chat_path", "/chat/completions")
    self.embed_path = self.cfg.get("embed_path", "/embeddings")
    self.timeout_s = float(self.cfg.get("timeout_s", 120))
    self.max_retries = int(self.cfg.get("max_retries", 2))
    self.backoff = float(self.cfg.get("retry_backoff_s", 1.5))
```

> `timeout_s` → SDK `timeout`，`max_retries` → SDK `max_retries`；`retry_backoff_s`（第 28 行 / `config/llm.yaml:37,53`）SDK 不暴露 —— CONTEXT Open Questions 第 2 条留给 planner 处置。
> `chat_path` / `embed_path` 在 SDK 下由 `base_url` + SDK 内置路径决定，planner 需决定这两个配置项的去留（**注意 `config/llm.yaml:30-31,46-47` 两处 provider 段都有**）。

**待替换的错误分类逻辑**（第 61-89 行，SDK 重写后**整段消失**，但「不可重试类直接抛、其余重试」的语义是 SDK 异常映射的先例）：

```python
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")[:500]
    last = LLMError(f"HTTP {e.code}: {body}")
    if e.code in (400, 401, 403, 404):      # 不可重试
        raise last
except Exception as e:                       # 网络类错误可重试
    last = e
```

**凭证缺失的显式报错**（第 62-67 行，`tests/test_gateway.py:156-164` 正在钉这条路径，SDK 重写后**必须保留等价的前置校验**，否则该测试失败）：

```python
if not self.base_url:
    raise LLMError(f"provider={self.name} 未配置 base_url"
                   f"（环境变量 {self.cfg.get('base_url_env')}）")
if not self.api_key:
    raise LLMError(f"provider={self.name} 未配置 API Key"
                   f"（环境变量 {self.cfg.get('api_key_env')}）")
```

> ⚠️ 现有测试直接调 `p._post("/chat/completions", {})`（`test_gateway.py:164`）。`_post` 若被删除，该测试需同步改写 —— 属于**必须处理的连带项**。

**`LLMResponse` 组装契约**（第 91-115 行，SDK 版必须产出**字段完全相同**的 `LLMResponse`，因为 `LLMGateway.chat()` 依赖 `prompt_tokens`/`completion_tokens`/`latency_ms`/`finish_reason`）：

```python
t0 = time.time()
data = self._post(self.chat_path, payload)
choices = data.get("choices") or []
if not choices:
    raise LLMError(f"响应缺少 choices：{str(data)[:300]}")
msg = choices[0].get("message") or {}
usage = data.get("usage") or {}
return LLMResponse(
    text=msg.get("content") or "",
    logical_model=req.logical_model, physical_model=physical_model, provider=self.name,
    prompt_tokens=int(usage.get("prompt_tokens", 0)),
    completion_tokens=int(usage.get("completion_tokens", 0)),
    latency_ms=(time.time() - t0) * 1000,
    finish_reason=choices[0].get("finish_reason", "stop"),
    raw={"id": data.get("id"), "model": data.get("model")})
```

**上游降级链（只读参考，`base.py:113-131`）** —— 说明「为什么换 SDK 改动面可控」，也是 Open Questions 第 3 条的判定依据（当前**任何异常**都 fallback 到下一接入点）：

```python
chain = self.provider.models_for(req.logical_model)
if not chain:
    raise LLMError(f"provider={self.provider.name} 未配置任何可用物理模型：...")
last_err: Exception | None = None
for idx, phys in enumerate(chain):
    t0 = time.time()
    try:
        resp = self.provider.complete(safe, phys, params)
    except Exception as e:                             # 降级到下一个接入点
        last_err = e
        self.auditor.record(..., ok=False, error=f"{type(e).__name__}: {e}")
        continue
```

**子类别名不需改动**（`src/vela/gateway/volcengine.py:23-30`）：`VolcengineArkProvider` 只是 `super().__init__(cfg, name=name)`，SDK 重写后自动继承；`tests/test_gateway.py:167-170` 的 `issubclass` 断言天然成立。

---

### 3. **新建** env 形态检查消费模块 — `config/env_checks.yaml` 的读取方（D-16）

**类比：** `src/vela/gateway/redact.py:21-43` `Redactor` —— 项目里**唯一**的「配置驱动正则规则集 → 逐条应用 → 返回命中结果」类，与 env 形态检查的形状完全同构。

**cfg 可注入 + 默认从 YAML 取 + 构造期预编译正则**（第 22-26 行，**照抄这个构造器形状**：可注入才可单测，`tests/test_gateway.py:15-21` 正是靠这一点脱离 YAML 测 `Redactor`）：

```python
class Redactor:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg if cfg is not None else load_yaml("llm.yaml").get("redaction", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.rules = [(r["name"], re.compile(r["pattern"]), r["repl"])
                      for r in cfg.get("rules", [])]
```

**逐规则应用 + 累计命中的返回形状**（第 28-43 行）：

```python
def redact(self, text: str) -> RedactionResult:
    if not self.enabled or not text:
        return RedactionResult(text, {})
    hits: dict[str, int] = {}
    out = text
    for name, rx, repl in self.rules:
        ...
        out, n = rx.subn(repl, out)
        if n:
            hits[name] = hits.get(name, 0) + n
    return RedactionResult(out, hits)
```

**结果容器 dataclass**（第 11-18 行，env 检查结果可仿此定义，也可直接产 `list[dict]` —— 见下一节 D-18 的双通道要求）：

```python
@dataclass
class RedactionResult:
    text: str
    hits: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.hits.values())
```

> **模块路径由 planner 定**（CONTEXT 未锁）。`Redactor` 位于 `gateway/`，但 env 形态检查跨越 gateway 与运行期变量，放 `src/vela/` 顶层或 `src/vela/util/` 更贴合。**关键约束**：必须像 `Redactor` 一样支持 `cfg` 注入，否则单测被迫依赖真实 `config/` 目录。

---

### 4. `config/env_checks.yaml`（新建）— 规则表 schema（D-16）

**类比 A：** `config/llm.yaml:56-66` `redaction.rules` —— 扁平 `{name, pattern, repl}` 列表，最贴近「每变量一条规则」：

```yaml
redaction:
  enabled: true
  rules:
    - {name: vin,    pattern: '\b[A-HJ-NPR-Z0-9]{17}\b',                repl: 'VIN_<M>'}
    - {name: gps,    pattern: '\b(?:lat|lon|lng|latitude|longitude)\s*[=:]\s*-?\d{1,3}\.\d{3,}', repl: '<GEO>'}
    - {name: phone,  pattern: '\b1[3-9]\d{9}\b',                        repl: '<PHONE>'}
```

**类比 B：** `config/parsers.yaml:8-15` —— 字段更丰富的规则条目（含 `name` / `version` / `priority` / `regex` / `sample`），若 `env_checks.yaml` 需要「必填性 + 提示文案 + 样例」这种多字段形态，按此排版：

```yaml
parsers:

  - name: iso_bracket_comp
    version: "1.0"
    ts_kind: WALL
    priority: 10
    regex: '^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.,]\d{1,6})\s+\[(?P<logger>[^\]]+)\]\s+(?P<level>[A-Z]{1,5})\s+(?P<message>.*)$'
    ts_format: "iso"
    sample: '2026-07-20 11:22:33.123 [ota_master] INFO session begin task=T-1'
```

**YAML 文件头惯例**（全部 `config/*.yaml` 一致，`parsers.yaml:1-6`）—— 分隔线 + 中文用途说明 + 「新增 = 追加一条 YAML，无需改代码」的扩展点声明：

```yaml
# =====================================================================
# 解析器注册表 —— 20+ 车端日志文本格式
# 匹配顺序 = 列表顺序（先匹配先生效）；每个解析器命名捕获组即 Schema 字段
# 新增格式 = 追加一条 YAML，无需改代码（生产接入自定义格式的扩展点）
# =====================================================================
```

`env_checks.yaml` 的头部应额外声明 **「纯诊断用途，不进 `config_hash`」**（D-16）。

**待检查项的事实基准**（供 planner 写规则时对照）：
- `base_url` 正确形式 `https://ark.cn-beijing.volces.com/api/v3` —— 出处 `config/llm.yaml:28`、`docs/LLM_PRODUCTION.md:37`、`src/vela/gateway/volcengine.py:6`（三处一致）
- 接入点 ID 形态 `ep-xxxxxxxx` —— 出处 `src/vela/gateway/volcengine.py:8`、`config/llm.yaml:32`

---

### 5. `src/vela/cli.py::cmd_doctor` — 四项自检 + 双通道渲染（D-12~D-18）

**类比 A（最强）：** `src/vela/evidence/qa.py:41-102` —— 项目里**唯一**的「同一套检查结果 → JSON + 人读两种渲染」实现，正是 D-18 的形状。

**检查项收集为结构化列表**（`qa.py:41-56`）：

```python
checks = [
    ("行数对账 files.record_count == log_lines", file_recs == total,
     f"files={file_recs} log_lines={total}"),
    (f"未解析率 <= {max_unparsed:.0%}", unparsed_ratio <= max_unparsed,
     f"{unparsed_ratio:.4%} ({unparsed}/{total})"),
    ("无缺失时间戳", ts_null == 0, f"ts_utc IS NULL: {ts_null}"),
    ("模板已生成", tmpl > 0, f"templates={tmpl}"),
]
passed = all(ok for _, ok, _ in checks)
```

**通道一：JSON 渲染**（`qa.py:69,71`，`{name, ok, detail}` 三元组是既定字段名，D-18 的 `--json` key 命名应对齐）：

```python
"checks_passed": passed,
"checks": [{"name": n, "ok": bool(ok), "detail": d} for n, ok, d in checks],
...
write_json(qa_dir / "qa_report.json", stats)
```

**通道二：人读渲染**（`qa.py:80-82,99` —— 同一 `checks` 变量二次遍历，✅/❌ 图标）：

```python
"", "## 校验项", "", "| 校验 | 结果 | 详情 |", "|---|---|---|"]
for n, ok, d in checks:
    lines.append(f"| {n} | {'✅ PASS' if ok else '❌ FAIL'} | {d} |")
...
lines += ["", f"**总体结论：{'✅ 全部校验通过' if passed else '❌ 存在未通过项，见上表'}**", ""]
```

**类比 B：** `src/vela/cli.py:144-162` `cmd_evidence` —— CLI 侧「`list[dict]` 结果 → 图标化 print → 退出码」的现成形状，doctor 的人读通道照此写：

```python
for lv in res["levels"]:
    icon = "✅" if lv["ok"] else "❌"
    print(f"{icon} {lv['level']}: {lv['detail']}")
    for f in lv.get("failures", [])[:5]:
        print(f"     - {f}")
print(f"\n整体: {'通过 ✅' if res['ok'] else '未通过 ❌'}   evidence_id={res['evidence_id']}")
return 0 if res["ok"] else 5
```

**`--json` 输出的既有序列化助手**（`cli.py:23-25`，`--json` 通道直接调用它，不要另起 `json.dumps`）：

```python
def _p(obj, limit: int | None = None) -> None:
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    print(s[:limit] if limit else s)
```

> `cmd_query`（`cli.py:80-84`）已用 `_p()` 把整个结果打成 JSON 到 stdout —— **这是「stdout 纯 JSON、可被 `json.loads` 直接消费」的先例**，`tests/test_cli_and_server.py:45-50` 正在钉它。doctor 的 `--json` 应保证同样性质（此时不得混入人读行）。

**当前 `cmd_doctor` 全文**（`cli.py:172-198`，改造基线 —— 注意它是**逐项 print、无中间结构**，D-18 要求重构为「先收 `list[dict]` 再双通道」）：

```python
def cmd_doctor(a) -> int:
    from vela.config import config_dir, config_hash, load_budget, load_skills
    from vela.util.hashing import fingerprint_algos
    print(f"VELA {__version__}   Python {sys.version.split()[0]}")
    print(f"config_dir : {config_dir()}")
    ok = True
    for name in ("pipeline.yaml", "parsers.yaml", "ota_phases.yaml", "budget.yaml", "llm.yaml"):
        p = config_dir() / name
        icon = "✅" if p.exists() else "❌"
        ok &= p.exists()
        print(f"  {icon} {name}")
    print(f"skills     : {len(load_skills())} 个")
    b = load_budget()
    print(f"budget     : profile={b.name} round_evidence={b.round_evidence_tokens} "
          f"round_llm={b.round_llm_tokens} max_rounds={b.max_rounds}")
    print(f"algos      : {fingerprint_algos()}")
    print(f"config_hash: {config_hash()}")
    print(f"provider   : {os.environ.get('VELA_LLM_PROVIDER', '(配置文件 active)')}")
    for mod in ("duckdb", "pyarrow", "yaml", "xxhash", "blake3", "fastapi", "pytest"):
        try:
            __import__(mod)
            print(f"  ✅ {mod}")
        except ImportError:
            req = mod in ("duckdb", "pyarrow", "yaml")
            print(f"  {'❌' if req else '⚠️ '} {mod} {'(必需，缺失)' if req else '(可选，未安装，将降级)'}")
            ok &= not req
    return 0 if ok else 1
```

> **必需 vs 可选依赖的三态图标惯例**（`✅` / `❌ (必需，缺失)` / `⚠️  (可选，未安装，将降级)`）已就位。D-03 把 `python-dotenv`、`openai` 定为**必需**，加入第 195 行的 `req = mod in (...)` 集合即可（注意导入名是 `dotenv` 与 `openai`）。
> `config_dir()` / `config_hash()` 的展示格式（左对齐 11 字符标签 + `: `）是既有排版惯例，新增行照此对齐。
> **D-15 第 2 项可零成本复用**：`build_gateway()`（`base.py:155-174`）按 `kind` 构造 provider，doctor 拿到 provider 后直接调 `models_for("planner"/"verifier"/"reporter"/"distiller")` 即得四条链；逻辑模型名的权威来源是 `config/llm.yaml:8-12`。

**doctor 的 provider 判定依据**（`base.py:160`，D-12 的「按 provider 自动判定探测时机」应复用同一优先级，不要另写一套）：

```python
name = provider_name or os.environ.get("VELA_LLM_PROVIDER") or cfg.get("active", "mock")
```

---

### 6. `src/vela/cli.py::build_parser()` — doctor 的三个新参数

**类比：** `cli.py:225-231`（布尔开关 `--list`）与 `:233-243`（可选值参数）

```python
q = sub.add_parser("query", help="执行单个工具")
q.add_argument("--db", default="")
q.add_argument("--tool", default="describe_dataset")
q.add_argument("--args", default="")
q.add_argument("--limit", type=int, default=20)
q.add_argument("--list", action="store_true")
q.set_defaults(func=cmd_query)
```

**当前 doctor 子命令**（`cli.py:268-269`，零参数，改造基线）：

```python
dr = sub.add_parser("doctor", help="环境自检")
dr.set_defaults(func=cmd_doctor)
```

**布尔开关惯例：** 全部用 `action="store_true"`（`cli.py:215,222,230`），**无任何 `--no-xxx` 反向开关先例**。D-13 的 `--offline` / `--online` 是一对互斥开关 —— argparse 的 `add_mutually_exclusive_group()` 在本项目**无先例**，planner 可用它，也可两个独立 `store_true` + 代码内校验（后者更贴近现状）。

**注意 `cli.py:221` 的三态默认值**（`--keep-raw` 用 `default=None` 表示「未指定 → 走配置」）—— 若 `--offline`/`--online` 要区分「未指定（按 provider 自动判定）」与「显式指定」，这是既有做法。

**子命令注册的回归护栏**（`tests/test_cli_and_server.py:83-88`）：

```python
def test_build_parser_exposes_all_subcommands():
    ap = build_parser()
    sub_dest = {a.dest: a for a in ap._subparsers._group_actions}
    choices = sub_dest["cmd"].choices
    for cmd in ("sim", "build", "query", "agent", "eval", "evidence", "serve", "doctor"):
        assert cmd in choices
```

---

### 7. 退出码分层（D-14）

**类比：** `src/vela/cli.py` 全体子命令的既有约定 —— **每个子命令有专属非零码，且「软失败也返非零」是主流**：

| 位置 | 语句 | 语义 |
|---|---|---|
| `cli.py:63` `cmd_build` | `return 1 if bad else 0` | QA 有未通过项 → 1 |
| `cli.py:85` `cmd_query` | `return 0 if res.ok else 1` | 工具执行失败 → 1 |
| `cli.py:76` `cmd_query` | `return 2` | 未知工具（用法错） → 2 |
| `cli.py:118` `cmd_agent` | `return 0 if st.status == "answered" else 3` | 诊断未作答 → 3 |
| `cli.py:140` `cmd_eval` | `return 0 if ok else 4` | 评测闸门未过 → 4 |
| `cli.py:162` `cmd_evidence` | `return 0 if res["ok"] else 5` | 证据验证未过 → 5 |
| `cli.py:198` `cmd_doctor` | `return 0 if ok else 1` | 本地检查失败 → 1 |

**统一收口**（`cli.py:273-276`）：

```python
def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    return int(a.func(a) or 0)
```

> **D-14 是对既有惯例的有意偏离**：连通性失败要返 `0`（只标 ❌ 不阻断），与上表「失败即非零」的主流相反。planner 须在代码注释里写明这一偏离的理由，并指向消费方：
> - `run_all.sh:7` `set -euo pipefail` + `:30-31` 第 1 步 `python3 -m vela.cli doctor` —— 非零即整条演示链路中断
> - `Makefile:41-42` `doctor` 目标
> - `tests/test_cli_and_server.py:9-13` 断言 `rc == 0`（本地环境下必须保持）

---

### 8. `tests/conftest.py` — 环境变量无条件赋值（D-11）

**类比：** 自身第 10-15 行（改造基线）：

```python
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("VELA_CONFIG_DIR", str(ROOT / "config"))
os.environ.setdefault("VELA_LLM_PROVIDER", "mock")
os.environ.setdefault("VELA_PROFILE", "poc")
os.environ.setdefault("PYTHONHASHSEED", "0")
```

> D-11 要求第 13 行改无条件赋值。**第 12、14、15 行需逐条评估**（CONTEXT 明确要求）：
> - `VELA_CONFIG_DIR`（第 12 行）：`.env.example` 未含此变量，但用户 `.env` 可能有 → 若被 `.env` 指到别处，全部测试的配置基准漂移。
> - `VELA_PROFILE`（第 14 行）：`.env.example:24` **有** `VELA_PROFILE=poc` → 若用户改成 `production`，`tests/test_obs_and_config.py:85-89` 与全部预算相关断言的基准变化。
> - `PYTHONHASHSEED`（第 15 行）：`.env.example:27` **有** → 但该变量必须在解释器**启动前**生效，运行期赋值无效，改与不改都不影响行为（`run_all.sh:15` 才是真正生效点）。

---

### 9. `pyproject.toml` / `requirements.txt` — 依赖与 `realllm` 标记（D-03/D-19）

**必需依赖位置**（`pyproject.toml:11-16`）：

```toml
dependencies = [
  "duckdb>=1.0",
  "pyarrow>=14",
  "PyYAML>=6.0",
  "pytz>=2024.1",
]
```

**可选依赖组**（`pyproject.toml:18-22`，D-03 明确**不进**这里）：

```toml
[project.optional-dependencies]
fast = ["xxhash>=3.4", "blake3>=0.4"]
serve = ["fastapi>=0.110", "uvicorn>=0.29"]
dev = ["pytest>=8.0"]
all = ["xxhash>=3.4", "blake3>=0.4", "fastapi>=0.110", "uvicorn>=0.29", "pytest>=8.0"]
```

**pytest 标记注册**（`pyproject.toml:33-39`）：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"
markers = [
  "slow: 端到端较慢用例",
  "determinism: 确定性回归用例",
]
```

**`requirements.txt` 双文件惯例**（第 1-5 行 = 必需，含行尾注释说明理由）：

```
# ---- 核心依赖（必需，纯本地、无容器）----
duckdb>=1.0
pyarrow>=14
PyYAML>=6.0
pytz>=2024.1        # DuckDB 返回 TIMESTAMPTZ 到 Python 时需要
```

对照 `requirements-optional.txt:1-6`（每行注释写「缺失 → 如何降级」）—— 新依赖是必需项，进 `requirements.txt`，注释写「为什么必需」而非降级路径。

**不要复制的模式**（`src/vela/util/hashing.py:23-30`，CONTEXT `Established Patterns` 明确「本阶段新依赖不采用此模式」）：

```python
try:                                    # pragma: no cover - 取决于环境
    import blake3 as _blake3
    _HAS_BLAKE3 = True
except Exception:                       # pragma: no cover
    _blake3 = None
    _HAS_BLAKE3 = False
```

---

### 10. 新建测试文件

**`.env` 优先级单测（D-08）— 类比 `tests/test_gateway.py:143-153`**（`monkeypatch.setenv` 驱动的环境变量优先级断言，形状完全对口）：

```python
def test_openai_compat_models_for_reads_env(monkeypatch):
    from vela.gateway.openai_compat import OpenAICompatProvider
    monkeypatch.setenv("VELA_ARK_MODEL", "ep-default")
    monkeypatch.setenv("VELA_ARK_MODEL_PLANNER", "ep-planner")
    monkeypatch.setenv("VELA_ARK_MODEL_FALLBACK", "ep-fallback")
    cfg = {"model_env": "VELA_ARK_MODEL", "fallback_chain": ["VELA_ARK_MODEL_FALLBACK"]}
    p = OpenAICompatProvider(cfg, name="volcengine")
    chain = p.models_for("planner")
    assert chain[0] == "ep-planner"
```

**doctor 单测 — 类比 `tests/test_cli_and_server.py:9-13`**（`main([...])` + `capsys` + 返回码，doctor 的 `--offline` / `--json` 用例照此写）：

```python
def test_cli_doctor_runs_and_reports_ok(capsys):
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "config_hash" in out
```

**`--json` 可解析性断言 — 类比 `tests/test_cli_and_server.py:45-50`**：

```python
def test_cli_build_and_query_roundtrip(built, capsys):
    rc = main(["query", "--db", str(built["db"]), "--tool", "describe_dataset"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["ok"] and data["summary"]["total_records"] > 0
```

**`realllm` 端到端用例 — 类比 `tests/test_cli_and_server.py:58-64`**（D-19 断言「报告非空 + 至少一个 `[[EV:row_hash]]`」按此形状写；引用格式的权威来源见 `src/vela/agent/citations.py`）：

```python
def test_cli_agent_diagnose_end_to_end(built, tmp_path, capsys):
    rc = main(["agent", "diagnose", "--db", str(built["db"]),
              "--workspace", str(tmp_path / "cli_agent_ws"),
              "--session-id", "CLI-TEST"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "uds_nrc_programming_failure" in out
```

**测试文件的 docstring 惯例**（每个 `tests/test_*.py` 首行都是一句中文用途说明）：

```python
"""模型网关：脱敏、预算硬切断、mock 供应商契约、审计、火山引擎适配器解析。"""
"""CLI 子命令 + 本地服务路由（不依赖 FastAPI 是否安装，走内部 _handle 分发）。"""
```

**回归用例的注释惯例**（`tests/test_cli_and_server.py:30-35`）：当一个用例是为堵某类结构性漏洞而写时，docstring 里写明「为什么单元测试抓不到、只有这条路径能抓到」。`.env` 优先级用例（ROADMAP 成功判据 1 明确要求）应照此说明。

---

### 11. `.env.example` — 行尾注释重排（D-16）

**类比：** 自身第 6-15 行 —— **同一文件里已有正确写法**（注释独占一行），只需把第 22-27 段改成这个形状：

```
# ---------- 模型网关（生产接入的唯一开关面）----------
# provider: mock | volcengine | openai_compat
VELA_LLM_PROVIDER=mock

# ---- 火山引擎方舟（Ark）：优先适配 ----
# 控制台创建推理接入点后，把接入点 ID（ep-xxxx）或模型名填到 MODEL
VELA_ARK_API_KEY=
VELA_ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

**待改造段**（第 22-27 行，五处行尾注释）：

```
# ---------- 运行期 ----------
VELA_WORKSPACE=./workspace          # 产物根目录
VELA_PROFILE=poc                    # poc | production（预算档位）
VELA_TENANT=demo-tenant             # 强制租户谓词的租户标识
VELA_LOG_LEVEL=INFO
PYTHONHASHSEED=0                    # 确定性要求：固定哈希种子
```

---

### 12. 文档改写 ×4（D-01 依赖纪律 + D-10 优先级链）

无需代码类比，以下为**待改写原文**（已定位，planner 直接替换）：

| 文件:行 | 当前原文 |
|---|---|
| `.planning/REQUIREMENTS.md:21` | `...无需手工 export（stdlib 实现，不新增运行期依赖；已存在的进程环境变量优先级更高）` |
| `.planning/PROJECT.md:88` | `- **Tech stack**: Python ≥ 3.11，src/ 布局，运行期依赖仅 duckdb / pyarrow / PyYAML / pytz — 依赖最小化是既定纪律，新增依赖前先评估 stdlib 可行性` |
| `AGENTS.md:47` | `- 依赖最小化：运行期仅 duckdb / pyarrow / PyYAML / pytz，新增依赖前先评估能否用 stdlib 实现。` |
| `.planning/codebase/STACK.md:67` | `- 加载优先级（src/vela/config.py 顶部注释）：显式函数参数 > 环境变量 > config/*.yaml > 代码内默认值；...` |

**连带项（planner 自查）：**
- `AGENTS.md:34` 的 pytest 标记清单（`slow` / `determinism`）需加 `realllm`
- `.planning/codebase/STACK.md:60-66` 的环境变量清单需补 `.env` 自动加载说明
- `Makefile:15-16` help 文本中的依赖描述（`duckdb/pyarrow/PyYAML/pytz`）
- `README.md` 若含同口径描述

---

## Shared Patterns（跨文件通用模式）

### A. 配置驱动：cfg 可注入 + 默认 `load_yaml`
**来源：** `src/vela/gateway/redact.py:22-23`
**适用：** env 检查模块、任何新增读 YAML 的类
```python
def __init__(self, cfg: dict | None = None):
    cfg = cfg if cfg is not None else load_yaml("llm.yaml").get("redaction", {})
```
> 可注入是**单测前提**（`tests/test_gateway.py:15-21` 靠这一点脱离真实 `config/`）。`load_yaml` 有 `lru_cache`（`config.py:28`）—— 测试内改 YAML 文件不生效，只能靠注入。

### B. CLI 输出：只用 `print()`，✅/❌/⚠️ 三态图标
**来源：** `src/vela/cli.py:157-161`、`:180-196`、`src/vela/evidence/qa.py:82`
**适用：** doctor 全部人读输出
```python
icon = "✅" if lv["ok"] else "❌"
print(f"{icon} {lv['level']}: {lv['detail']}")
```
> 项目铁律：**不使用 `logging` 模块**（`AGENTS.md:48`）。结构化事件走 `obs/events.py::EventBus` —— 但 CLI 层现有子命令**零处**使用 EventBus，doctor 保持 `print()` 即可。错误输出到 stderr 的先例：`cli.py:74` `print(..., file=sys.stderr)`。

### C. 检查结果先收 `list[dict]`，再双通道渲染
**来源：** `src/vela/evidence/qa.py:41-102`（唯一先例）
**适用：** `cmd_doctor`（D-18）
**字段名对齐：** `{"name": str, "ok": bool, "detail": str}` + 顶层 `checks_passed: bool`

### D. 掩码惯例
**来源：** `src/vela/util/textutil.py:66-71`
**适用：** D-17 的 API key 掩码
```python
def mask_vin(vin: str) -> str:
    if not vin or len(vin) < 4:
        return "VIN_****"
    import hashlib
    pre = hashlib.blake2b(vin.encode("utf-8"), digest_size=3).hexdigest()
    return f"VIN_{pre}_{vin[-4:]}"
```
> **只借「长度不足则全掩」的短路结构**，不借哈希前缀（D-17 要求前 4 后 4 明文）。掩码函数放 `util/textutil.py` 与 `mask_vin` 同址是最贴合的选择。

### E. Provider 接口边界
**来源：** `src/vela/gateway/base.py:62-70`
**适用：** `openai_compat.py` 重写
**不变量：** `models_for(logical_model) -> list[str]` 与 `complete(req, physical_model, params) -> LLMResponse` 的签名与返回类型；`LLMGateway.chat()`（`base.py:87-148`）不得改动。

### F. 错误处理：分层显式 + 不吞异常
**来源：** `src/vela/gateway/openai_compat.py:62-67`（前置校验抛 `LLMError` 带修复指引）、`base.py:116-117`（错误信息指向 `.env.example`）
**适用：** SDK 异常映射、env 检查失败提示
```python
raise LLMError(f"provider={self.provider.name} 未配置任何可用物理模型："
               f"请设置对应环境变量（见 .env.example）")
```
> 惯例：错误信息用中文，且**必须指出下一步动作**（哪个环境变量 / 哪个文件）。

### G. 模块 docstring 与分隔注释
**来源：** 全部 `src/vela/**/*.py`
- 首行中文用途说明（`openai_compat.py:1-5`、`redact.py:1`）
- `from __future__ import annotations` 紧随 docstring
- 方法间用 `# ---...--- #` 分隔（`base.py:86`、`openai_compat.py:30`）
- CLI 子命令用右对齐分隔（`cli.py:171` `# ------------------------------------------------------------- doctor`）

---

## No Analog Found（无类比，需从零设计）

| 文件/能力 | 角色 | 数据流 | 原因 |
|---|---|---|---|
| doctor 的网络探测（D-15 最小 chat 调用） | cli-command | request-response（联网） | `cmd_doctor` 当前**零网络调用**；整个 CLI 层无任何主动联网先例。唯一可复用的是 `build_gateway()`（`base.py:155-174`）构造 provider，但「构造后发一次探测请求并按异常归因」是全新代码。 |
| openai SDK 异常 → `LLMError` 映射 | provider-adapter | error-transform | 现有分类是 HTTP 状态码硬编码集合（`openai_compat.py:83`），无 SDK 异常类型映射先例。CONTEXT Open Questions 第 3 条明确留给 planner。 |
| `realllm` 标记的**默认排除** | test-config | — | `pyproject.toml:35` `addopts = "-q --strict-markers"` **无任何 `-m` 排除**；且 `slow` / `determinism` 两个标记虽已注册，**代码库中零处使用**（`grep -rn "mark.slow\|mark.determinism" tests/` 无结果）。D-19 的「默认被 addopts 排除」需新增 `-m "not realllm"`，且要验证不破坏 `make test`（`Makefile:70-71`）与 `make test-fast`（`:73-75`）。 |
| `.env` 在 site-packages 安装下的定位兜底 | config-loader | — | 项目只有可编辑安装路径（`Makefile:39` `pip install -e .`），`parents[2]` 兜底逻辑无先例。 |

---

## Metadata

**Analog search scope:** `src/vela/`（config / gateway / cli / evidence / evidencepack / util / obs）、`tests/`、`config/`、项目根（`Makefile` / `run_all.sh` / `pyproject.toml` / `requirements*.txt` / `.env.example` / `.gitignore`）、`docs/LLM_PRODUCTION.md`、`.planning/`
**Files read in full:** 14
**Files grepped:** 8
**Pattern extraction date:** 2026-07-31

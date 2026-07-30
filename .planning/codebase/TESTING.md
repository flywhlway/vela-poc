# Testing Patterns

**Analysis Date:** 2026-07-30

## Test Framework

**Runner:**
- pytest `>=8.0` (declared in `pyproject.toml` under `[project.optional-dependencies] dev`/`all`, and in `requirements-optional.txt`).
- Config: `[tool.pytest.ini_options]` in `pyproject.toml` — `testpaths = ["tests"]`, `addopts = "-q --strict-markers"`, two custom markers declared: `slow` ("端到端较慢用例") and `determinism` ("确定性回归用例"). **Note:** neither marker is actually applied to any test in `tests/` today (confirmed by search) — they are reserved for future use. `--strict-markers` means any typo'd `@pytest.mark.foo` will fail collection, so only use `slow`/`determinism` or pytest's builtins.

**Assertion Library:**
- Plain `assert` statements only (pytest's assertion rewriting). No `unittest.TestCase`, no third-party assertion libraries (no `hamcrest`, no custom assert helpers).

**Run Commands:**
```bash
make test                 # PYTHONPATH=src VELA_CONFIG_DIR=config python3 -m pytest tests/ -q
make test-fast             # only test_util.py, test_sim.py, test_gateway.py, test_obs_and_config.py
                            # (the subset that needs no `build()` / columnar-store construction)
PYTHONPATH=src VELA_CONFIG_DIR=config pytest tests/test_gateway.py -q       # single file
PYTHONPATH=src VELA_CONFIG_DIR=config pytest tests/test_util.py -k hash -q  # by keyword
```
There is no `pytest.ini`/`setup.cfg` fallback — `PYTHONPATH=src` and `VELA_CONFIG_DIR=config` **must** be set (or rely on `tests/conftest.py`, which sets both via `sys.path.insert`/`os.environ.setdefault` — see below), otherwise `import vela` and config loading fail.

## Test File Organization

**Location:**
- Flat `tests/` directory, no subdirectories, no test co-location with `src/`.

**Naming:**
- One test file per *subsystem/plane*, not per source module: `test_util.py` ↔ `src/vela/util/*`, `test_gateway.py` ↔ `src/vela/gateway/*`, `test_evidence_pipeline.py` ↔ `src/vela/evidence/*`, `test_evidencepack.py` ↔ `src/vela/evidencepack/*`, `test_query_api.py` ↔ `src/vela/query/*`, `test_agent.py` ↔ `src/vela/agent/*`, `test_sim.py` ↔ `src/vela/sim/*`, `test_obs_and_config.py` ↔ `src/vela/obs/*` + `src/vela/config.py`, `test_cli_and_server.py` ↔ `src/vela/cli.py` + `src/vela/server/*`, `test_eval.py` ↔ `src/vela/eval/*`. When adding a new source file, add tests to the file matching its *plane*, not a new 1:1 file, unless the plane is new.
- Test function names are full sentences describing behavior, not `test_<method_name>`: `test_row_hash_binds_path_and_line`, `test_agent_does_not_fabricate_root_cause_on_healthy_session`, `test_compressor_caps_whitelist_beyond_limit_and_folds_middle`. Aim for a name that reads as the assertion being made.

**Structure:**
```
tests/
├── conftest.py                 # sys.path + env setup, session-scoped fixtures
├── test_util.py                # 20 tests — hashing/ids/jsonl/textutil/timeutil
├── test_sim.py                 # 12 tests — scenario simulation/generation
├── test_gateway.py             # 15 tests — LLM gateway, redaction, budget, providers
├── test_obs_and_config.py      # 12 tests — event bus, metrics, config/budget loading
├── test_evidence_pipeline.py   # 22 tests — unpack, parse, template, build pipeline
├── test_query_api.py           # 27 tests — 12 query tools + guardrails + SQL sandbox
├── test_agent.py               # 23 tests — skills, compression, citations, 7-node graph e2e
├── test_evidencepack.py        # 16 tests — evidence pack build/snapshot/verify
├── test_eval.py                # 9 tests  — golden eval runner + report
└── test_cli_and_server.py      # 14 tests — CLI subcommands + HTTP server routing
```
~170 test functions total (Makefile's `make test` help text references "177 个单元/集成测试" including parametrized expansions).

## Test Structure

**Suite Organization:**
Files use `# ---- section ----`-style comment dividers to group tests by the function/class under test, then flat top-level `test_*` functions underneath — no test classes:

```python
"""模型网关：脱敏、预算硬切断、mock 供应商契约、审计、火山引擎适配器解析。"""
from __future__ import annotations

import json
import pytest

from vela.gateway import LLMRequest, build_gateway
from vela.gateway.budget import BudgetExceeded, TokenLedger


def test_redactor_masks_vin_phone_email_ip_gps():
    r = Redactor({"enabled": True, "rules": [...]})
    text = "VIN=LSVM3HNR4SC988574 phone 13812345678 ..."
    res = r.redact(text)
    assert "LSVM3HNR4SC988574" not in res.text
    assert res.total >= 4
```
(`tests/test_gateway.py`)

**Patterns:**
- Setup: construct real objects directly in the test body (no `setUp`, minimal use of fixtures beyond the shared session ones in `conftest.py`). Imports needed only for one test are done *inside* the test function, mirroring the source code's deferred-import convention: `def test_token_ledger_round_cutoff(): from vela.config import load_budget` (`tests/test_gateway.py`).
- Teardown: explicit `try/finally` with `.close()` for anything holding a DB connection or file handles: `g = AgentGraph(...); try: res = g.run() finally: g.close()` — repeated verbatim across `tests/test_agent.py` and `tests/test_cli_and_server.py`.
- Assertion: single behavioral fact per test where possible, but compound asserts on one call's result are common and acceptable (e.g. `assert rc == 0; assert "全部通过" in out or "未通过" in out`).

## Mocking

**Framework:** No `unittest.mock`, `MagicMock`, or `Mock()` used anywhere in `tests/` (confirmed by search). This is a deliberate project-wide choice.

**Patterns:**
- Instead of mocking internals, the project provides a real, deterministic **`MockProvider`** implementation of the `Provider` interface (`src/vela/gateway/mock.py`) that is exercised through the exact same `LLMGateway.chat()` path production code uses — see `build_gateway("mock", ...)` in `tests/test_gateway.py`. This is the standard way to test anything that depends on an LLM call: use `build_gateway("mock", session_id=..., audit_path=tmp_path/"audit.jsonl")`, never patch `LLMGateway.chat`.
- The only test double for environment/config is pytest's built-in `monkeypatch` fixture, used exclusively for environment variables: `monkeypatch.setenv(...)`, `monkeypatch.delenv(..., raising=False)` (`tests/test_gateway.py::test_openai_compat_models_for_reads_env`, `::test_openai_compat_missing_credentials_raises_clear_error`).
- End-to-end flows (`build()` → `LogQueryAPI` → `AgentGraph`) are tested against a real, small, generated dataset and a real DuckDB file on disk — not stubs. See "Fixtures and Factories" below.

**What to Mock:**
- Nothing at the unit-test-mock level. Only substitute at architectural seams that already have a real test-double implementation (`MockProvider` for LLM calls). Do not introduce `unittest.mock.patch` — it is inconsistent with the rest of the suite.

**What NOT to Mock:**
- DuckDB, the filesystem, the evidence pipeline, and the agent graph are all exercised for real against `tmp_path`-scoped data. Prefer building real fixtures over mocking these layers, following the existing `conftest.py` pattern.

## Fixtures and Factories

**Test Data:**
Session-scoped fixtures in `tests/conftest.py` build one small synthetic dataset and two columnar stores (`built` = the faulty `S3_UDS_NRC72` scenario, `built_healthy` = `S0_HEALTHY`) exactly once per test session, then every test that needs a real DB depends on these fixtures instead of re-running the (slower) build pipeline:

```python
SMALL = dict(density=2, chunks=140, blocks=60)   # small dataset: single-digit-second builds

@pytest.fixture(scope="session")
def tmp_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("vela")

@pytest.fixture(scope="session")
def dataset(tmp_root) -> dict:
    from vela.sim.generate import generate_dataset
    out = tmp_root / "dataset"
    truths = generate_dataset(out, scenarios=["S0_HEALTHY", "S3_UDS_NRC72", "S5_STORAGE_FULL"], **SMALL)
    return {"dir": out, "truths": {t["scenario_id"]: t for t in truths}}

@pytest.fixture(scope="session")
def built(dataset, tmp_root) -> dict:
    from vela.evidence.pipeline import build
    t = dataset["truths"]["S3_UDS_NRC72"]
    archive = dataset["dir"] / t["archive"]
    ws = tmp_root / "ws_s3"
    res = build(archive, ws, progress=False)
    return {"result": res, "ws": ws, "archive": archive, "db": ws / "gold" / "analysis.duckdb", "truth": t}

@pytest.fixture
def api(built):
    from vela.query.api import LogQueryAPI
    a = LogQueryAPI(built["db"])
    yield a
    a.close()
```
(`tests/conftest.py`)

**Location:**
- All shared fixtures live in `tests/conftest.py`. Per-test throwaway data (rows, dicts, small zip archives) is constructed inline in the test body using pytest's built-in `tmp_path` fixture — no separate `fixtures/` directory or factory library (no `factory_boy`).

**Environment bootstrap (also in `conftest.py`, module-level, runs on collection):**
```python
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("VELA_CONFIG_DIR", str(ROOT / "config"))
os.environ.setdefault("VELA_LLM_PROVIDER", "mock")
os.environ.setdefault("VELA_PROFILE", "poc")
os.environ.setdefault("PYTHONHASHSEED", "0")
```
`PYTHONHASHSEED=0` is set to keep any hash-order-dependent behavior reproducible across CI runs — relevant given the project's broader determinism guarantees (row/norm/merkle hashing).

## Coverage

**Requirements:** None enforced. No `coverage.py`/`pytest-cov` config, no `.coveragerc`, no CI coverage gate found anywhere in the repo.

**View Coverage:**
Not set up. If needed ad hoc: `PYTHONPATH=src VELA_CONFIG_DIR=config pytest --cov=vela --cov-report=term-missing tests/` (requires installing `pytest-cov` separately; it is not a project dependency).

## Test Types

**Unit Tests:**
- Pure-function/small-class tests with no filesystem or DB dependency: `tests/test_util.py` (hashing, ids, jsonl, textutil, timeutil), most of `tests/test_gateway.py` (redaction, budget ledger, prompt embed/extract), most of `tests/test_obs_and_config.py` (event bus, config loading). These are what `make test-fast` runs.

**Integration Tests:**
- Tests that build a real DuckDB store from a real (small, simulated) log archive and query/diagnose against it: most of `tests/test_query_api.py`, `tests/test_agent.py`'s graph e2e tests, `tests/test_evidencepack.py`, `tests/test_evidence_pipeline.py`. These depend on the session-scoped `built`/`built_healthy`/`dataset`/`api` fixtures in `conftest.py`.

**E2E Tests:**
- `tests/test_cli_and_server.py` drives the system through its actual entry points — `vela.cli.main([...])` (argv-level) and `vela.server.app._handle(path, body)` (HTTP-handler-level) — rather than calling internal functions directly, catching integration bugs that unit tests of the same functions miss. See the explicit regression-motivation comment in `test_cli_build_command_produces_parseable_qa_json` (`tests/test_cli_and_server.py` lines 30–35) for why this distinction matters in this codebase: a bug existed where `build()`'s Python API was correct but the CLI's JSON-path wiring was broken, and only an argv-level test caught it.
- No browser/UI E2E framework (no Playwright/Selenium) — the project has no browser frontend; `test_server_handle_*` tests exercise the HTTP JSON API's routing function directly rather than over a real socket.

## Common Patterns

**Async Testing:**
Not applicable — no `async`/`await` code in `src/` or `tests/`.

**Determinism Testing (a first-class concern for this project):**
Given the domain (evidence hashing, reproducible diagnosis), several tests specifically assert determinism/order-independence rather than just correctness:
```python
def test_merkle_root_order_independent_but_salt_sensitive():
    d = ["a", "b", "c"]
    assert merkle_root(d, salt="s") == merkle_root(list(reversed(d)), salt="s")
    assert merkle_root(d, salt="s") != merkle_root(d, salt="t")

def test_mock_provider_deterministic_same_input_same_output():
    gw1 = build_gateway("mock", session_id="A")
    gw2 = build_gateway("mock", session_id="B")
    ...
    assert r1b.text == r2b.text
```
(`tests/test_util.py`, `tests/test_gateway.py`) When adding logic touching hashing, ordering, or the mock LLM provider, add a matching determinism assertion.

**Error Testing:**
```python
def test_gateway_unknown_provider_raises():
    with pytest.raises(Exception):
        build_gateway("not-a-real-provider")

def test_openai_compat_missing_credentials_raises_clear_error(monkeypatch):
    ...
    with pytest.raises(LLMError):
        p._post("/chat/completions", {})
```
Prefer asserting the specific custom exception type (`LLMError`, `SqlGuardError`, `UnsafeArchiveError`, `BudgetExceeded`) over bare `Exception` when the production code raises a specific type; bare `Exception` is only used when deliberately testing "raises something" without committing to which subsystem's error type (e.g. `build_gateway` can raise plain `KeyError` or `LLMError` depending on failure mode).

**Parametrized Testing:**
```python
@pytest.mark.parametrize("spec,sec", [("1s", 1), ("10s", 10), ("30s", 30),
                                     ("1m", 60), ("5m", 300), ("1h", 3600)])
def test_bucket_seconds(spec, sec):
    assert bucket_seconds(spec) == sec
```
(`tests/test_util.py`; also used in `tests/test_evidence_pipeline.py` for parser-selection cases) — use `@pytest.mark.parametrize` for table-driven cases with 3+ similar inputs rather than a loop-with-asserts or repeated near-identical test functions.

---

*Testing analysis: 2026-07-30*

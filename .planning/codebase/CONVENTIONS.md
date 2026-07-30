# Coding Conventions

**Analysis Date:** 2026-07-30

## Naming Patterns

**Files:**
- All lowercase snake_case module files: `hashing.py`, `openai_compat.py`, `evidence_pipeline` split as `evidence/pipeline.py`.
- Package = subsystem ("plane"): `src/vela/agent/`, `src/vela/evidence/`, `src/vela/evidencepack/`, `src/vela/gateway/`, `src/vela/query/`, `src/vela/sim/`, `src/vela/obs/`, `src/vela/util/`. Each has an `__init__.py` that re-exports the public surface (see `src/vela/gateway/__init__.py`).
- Test files mirror the subsystem, not the module 1:1: `tests/test_gateway.py` covers all of `src/vela/gateway/*`, `tests/test_evidence_pipeline.py` covers `src/vela/evidence/*`. There is no `test_<module>.py`-per-source-file convention.

**Functions:**
- snake_case throughout, no exceptions found.
- Private/internal helpers prefixed with a single leading underscore: `_infer_level`, `_phase_matchers`, `_normalize_eol`, `_probe_fts`, `_q`, `_check_tenant` (see `src/vela/evidence/pipeline.py`, `src/vela/util/hashing.py`, `src/vela/query/api.py`).
- CLI subcommand handlers are named `cmd_<subcommand>` and take a single argparse namespace argument `a`, returning an `int` exit code: `cmd_sim`, `cmd_build`, `cmd_query`, `cmd_agent`, `cmd_eval`, `cmd_evidence`, `cmd_serve`, `cmd_doctor` (`src/vela/cli.py`).
- Factory/constructor-style functions use `build_*` / `load_*` / `new_*`: `build_gateway`, `load_yaml`, `load_budget`, `load_pipeline`, `new_run_id`, `new_session_id` (`src/vela/gateway/base.py`, `src/vela/config.py`, `src/vela/util/ids.py`).

**Variables:**
- Short, purpose-named locals: `ws` (workspace), `db` (database path), `cfg` (config dict), `st` (state), `res` (result), `rc` (return code), `a` (argparse namespace). These abbreviations are consistent project-wide — follow them rather than spelling out `workspace`/`config`/`result` in new code.
- Module-level constants are SCREAMING_SNAKE_CASE: `LOG_LINES_SCHEMA`, `COLUMN_COUNT`, `SCHEMA_VERSION`, `PARSE_OK`, `ANOMALY_CLOCK_JUMP` (`src/vela/evidence/models.py`).
- Precompiled regexes are module-private constants prefixed `_`: `_FORBIDDEN`, `_FUNC_DENY`, `_LIMIT_RE`, `_LEVEL_HINT` (`src/vela/query/guard.py`, `src/vela/evidence/pipeline.py`).

**Types:**
- Classes are PascalCase: `LLMGateway`, `LLMRequest`, `BudgetProfile`, `SqlGuard`, `AgentGraph`, `SessionState`, `EventBus`.
- Custom exceptions end in `Error` and subclass the most semantically appropriate stdlib exception (not always bare `Exception`): `LLMError(RuntimeError)`, `UnsafeArchiveError(RuntimeError)`, `SqlGuardError(ValueError)`, `BudgetExceeded` (`src/vela/gateway/base.py`, `src/vela/evidence/unpack.py`, `src/vela/query/guard.py`, `src/vela/gateway/budget.py`).

## Code Style

**Formatting:**
- No formatter config found (no `.prettierrc`, no `black`/`ruff` config in `pyproject.toml`). Style is hand-maintained but highly consistent: ~95–100 column soft wrap, multi-arg calls wrapped with hanging indent aligned to the opening paren.
- No blank line between a one-line docstring/summary and the first import; a blank line separates the `from __future__ import annotations` line from the rest of the imports.

**Linting:**
- No `ruff`/`flake8`/`pylint`/`mypy` config exists. `make lint` (`Makefile`) is a minimal `ast.parse()` syntax check over `src/**/*.py` — it does not check style or types. Do not assume CI enforces PEP8 spacing/import-order beyond what is manually consistent in the codebase.
- Every module targeting Python's older-than-3.11 union syntax uses `from __future__ import annotations` as line 1 (after the module docstring) — this is present in essentially every source file. Always add it to new modules so `X | None` / `list[str]` type hints work.

## Import Organization

**Order:**
1. Module docstring (Chinese, describes the module's role in the system — see "Comments" below).
2. `from __future__ import annotations`
3. Standard library imports (alphabetical-ish, one import per concern: `os`, `sys`, `re`, `json`, `time`, `threading`, `hashlib`, `pathlib.Path`, `dataclasses.dataclass`, `functools.lru_cache`, `typing.Any`).
4. Third-party imports (`pyarrow as pa`, `yaml`, `duckdb`) — often deferred to inside functions when the dependency is optional (see "Deferred/optional imports" below).
5. First-party `vela.*` imports last, absolute (never relative `from .foo import`), grouped by target module, parenthesized when multi-name: `from vela.evidence.models import (ANOMALY_CLOCK_JUMP, ANOMALY_DECODE_ERROR, ...)` (`src/vela/evidence/pipeline.py`).

**Path Aliases:**
- None. All internal imports use the fully-qualified `vela.<package>.<module>` path — no `src`-relative imports, no `__init__.py` re-export shortcuts used internally (re-exports in `__init__.py` exist only for external/test consumers, e.g. `from vela.gateway import LLMRequest, build_gateway` in `tests/test_gateway.py`).

**Deferred/optional imports (a strong, deliberate pattern):**
- CLI command handlers import their implementation module *inside* the function body, not at module top, to keep `vela.cli` import-cheap and to support graceful degradation: `def cmd_sim(a): from vela.sim.generate import generate_dataset` (`src/vela/cli.py`, every `cmd_*` function).
- Optional third-party accelerators are imported in a `try/except Exception` at module top and gated behind a `_HAS_<LIB>` boolean, with the stdlib fallback implemented inline: `src/vela/util/hashing.py` lines 22–34 (`blake3`, `xxhash` → falls back to `hashlib.blake2b`). Follow this exact pattern for any new optional dependency: try/except import → `_HAS_X` flag → branch at call site → identical output shape/semantics regardless of branch.
- `config_hash()` in `src/vela/config.py` imports `hashlib`, `vela.util.hashing`, `vela.util.jsonl`, `vela.util.textutil` inside the function to avoid a config→util circular import at module load time — a deliberate exception to "imports at top", used sparingly for genuine cycle avoidance.

## Error Handling

**Patterns:**
- Raise specific, message-rich exceptions in Chinese, always including the offending value and (when applicable) the valid alternatives: `raise KeyError(f"未知 profile: {name}，可选: {sorted(profiles)}")` (`src/vela/config.py`); `raise SqlGuardError(f"表不在白名单内：{t}")` (`src/vela/query/guard.py`).
- Custom exception classes are thin (`class LLMError(RuntimeError): pass`) — no custom `__init__`/attributes unless truly needed. Subclass the closest matching builtin (`RuntimeError` for operational failures, `ValueError` for validation failures, `KeyError` for missing-key lookups) rather than bare `Exception`.
- Fallback-chain pattern for external calls: iterate a list of candidates, catch broad `Exception` per-attempt, record the failure for audit, `continue` to the next candidate, and only raise after all candidates are exhausted — with the last error embedded in the final message: `src/vela/gateway/base.py` `LLMGateway.chat()` (lines 118–148).
- Bare `except Exception: pass` is used only at true fire-and-forget boundaries where a downstream subscriber must never break the caller — e.g. `EventBus.emit()` swallowing subscriber callback errors (`src/vela/obs/events.py` line 71, with an explicit comment explaining why). Do not use bare `except: pass` elsewhere; this is an intentional, narrow exception to normal error propagation.
- Resource cleanup uses `try/finally`, not context managers, for objects with an explicit `.close()`: `try: res = g.run() finally: g.close()` (`src/vela/cli.py` `cmd_agent`; same pattern in `cmd_query`, `cmd_evidence`, and throughout `tests/`).
- CLI-level errors are reported as a printed message to stderr/stdout plus a specific non-zero exit code (not exceptions bubbling to a traceback): unknown tool → `print(..., file=sys.stderr); return 2` (`src/vela/cli.py` `cmd_query`); QA failures → `return 1 if bad else 0` (`cmd_build`).
- Validation of untrusted input (SQL, archive paths) is centralized in dedicated guard modules rather than scattered `if` checks: `src/vela/query/guard.py` (`SqlGuard.check`), `src/vela/evidence/unpack.py` (`UnsafeArchiveError` for zip-slip detection).

## Logging

**Framework:** No `logging` module usage anywhere in `src/` (confirmed by search — zero hits for `logging.`/`getLogger`). This is a deliberate architectural choice, not an oversight.

**Patterns:**
- Structured, replayable events go through the custom `EventBus` (`src/vela/obs/events.py`): `event_bus().emit(kind, severity=Severity.PROGRESS|MILESTONE|ALERT, round_no=..., **payload)`. MILESTONE/ALERT events are fsync'd to JSONL immediately; PROGRESS events are best-effort.
- Metrics/counters go through `src/vela/obs/metrics.py` (dedicated counter/metric module) — check it before adding ad-hoc counting logic.
- Human-facing CLI output uses plain `print()` with emoji status markers (`✅`/`❌`/`⚠️`) directly in `src/vela/cli.py` — this is presentation code, not application logging, and is confined to `cli.py` and `server/app.py`.
- When adding new instrumentation: use `EventBus.emit()` for anything that should be replayable/auditable across a session; use `print()` only in `cli.py` for end-user command output.

## Comments

**When to Comment:**
- Every module has a top-of-file docstring in Chinese explaining the module's *role in the system* (often referencing the design doc section it implements, e.g. "技术方案 §6.1", "交底书机制二(a)") — not what the code does mechanically. New modules should follow this: state the subsystem's responsibility and any cross-reference to a design decision, not a restatement of imports/class names.
- Inline comments explain *why*, especially for non-obvious invariants: byte-vs-string hashing rationale (`src/vela/util/hashing.py` lines 10–14), why a bare `except: pass` is safe (`src/vela/obs/events.py` line 71), why an import is deferred to avoid a cycle (`src/vela/config.py`).
- Regression-motivated comments in tests explain *why a test exists*, referencing the specific bug it guards against, in detail: see `test_cli_build_command_produces_parseable_qa_json` (`tests/test_cli_and_server.py` lines 30–35).
- Section-divider comments (`# ---- 标识域 ----`, `# -------------------------------------------------------------- build`) are used to group related fields/functions within a long file — used in `src/vela/evidence/models.py` (schema field groups) and `src/vela/cli.py` (one divider per subcommand).

**Docstrings:**
- All docstrings and nearly all comments are written in Simplified Chinese; code identifiers (function/variable/class names) are English. Follow this split for new code.
- No JSDoc-equivalent structured docstring format (no `:param:`/`:returns:` Sphinx-style annotations found) — docstrings are prose paragraphs, sometimes with a bullet list, relying on the function signature's type hints for parameter/return documentation instead.

## Function Design

**Size:** Small and single-purpose. Most functions are 3–20 lines. Larger orchestration functions (e.g. `build()` in `src/vela/evidence/pipeline.py`) are decomposed into private `_helper()` functions defined just above their single call site in the same file.

**Parameters:**
- Keyword-only parameters (`*,`) are used liberally for anything beyond the first 1–2 positional args, especially booleans and optional tuning knobs: `def build(archive, workspace, *, run_id=None, keep_raw=None, progress=True)` (`src/vela/evidence/pipeline.py`); `def build_gateway(provider_name=None, *, session_id="-", audit_path=None, ledger=None, cfg=None)` (`src/vela/gateway/base.py`).
- Every parameter and return value has a type hint, using modern PEP 604 union syntax (`str | None`, not `Optional[str]` — a project-wide convention with zero `Optional[` usages found in `src/`). `from __future__ import annotations` is what enables this on Python 3.11 without runtime cost.

**Return Values:**
- Functions that can partially fail return a tuple of `(value, warning_or_none)` rather than raising or logging a side warning: `clamp_limit() -> tuple[int, str | None]`, `clamp_context() -> tuple[int, int, str | None]`, `wide_result_hint() -> str | None` (`src/vela/query/guard.py`). Adopt this pattern for new guardrail-style functions.
- Result objects are dataclasses with an `ok: bool` field plus structured detail, not exceptions, for expected/recoverable outcomes (e.g. query tool results, verification results) — see `LogQueryAPI.call()` result shape used in `src/vela/cli.py` `cmd_query` (`res.ok`, `res.error`, `res.rows`, ...).

## Module Design

**Exports:**
- Packages that are consumed externally (by tests or other subsystems as a unit) declare an explicit `__all__` in `__init__.py`: `src/vela/gateway/__init__.py` re-exports `LLMGateway, LLMRequest, LLMResponse, LLMError, build_gateway, TokenLedger, BudgetExceeded`. Packages consumed only internally via fully-qualified imports (e.g. `vela.evidence.*`) may have a thin or empty `__init__.py`.
- Dataclasses are the default structure for any bag of related fields — plain classes with `__init__` are rare; use `@dataclass` (optionally `frozen=True` for immutable config objects like `BudgetProfile`, `@dataclass` with `field(default_factory=...)` for mutable defaults).

**Barrel Files:**
- Used selectively (`gateway/__init__.py`) for the packages that form a stable public API boundary. Not used as a blanket pattern across every package — check the specific package's `__init__.py` before assuming a re-export exists; prefer importing from the concrete submodule (`vela.evidence.pipeline`, `vela.query.guard`) when unsure.

---

*Convention analysis: 2026-07-30*

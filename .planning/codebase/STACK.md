# Technology Stack

**Analysis Date:** 2026-07-30

## Languages

**Primary:**
- Python ≥3.11 (`pyproject.toml` `requires-python`) — 全部业务代码 `src/vela/`（约 7,100 行，61 个源文件）

**Secondary:**
- YAML — 全部可调参数与规则集，位于 `config/*.yaml`（业务代码不硬编码阈值）
- SQL — DuckDB 查询语句，嵌入 `src/vela/query/api.py`、`src/vela/evidence/pipeline.py`、`src/vela/evidence/gold.py`

## Runtime

**Environment:**
- CPython 3.11+（本地开发环境实测 3.12.13，见 `python3 --version`）
- 无容器依赖：README 明确声明"没有 Docker，没有外部数据库，没有网络依赖（mock 供应商下）"

**Package Manager:**
- pip + `venv`（`.venv`），无 Poetry/PDM/uv 迹象
- Lockfile：缺失（无 `requirements.lock` / `poetry.lock` / `uv.lock`），依赖用 `>=` 下限约束而非锁定版本

## Frameworks

**Core:**
- 无 Web/应用框架作为核心依赖；核心运行时依赖仅 4 个（见下），业务逻辑为纯 Python 标准库 + DuckDB

**Testing:**
- pytest ≥8.0（可选依赖组 `dev`/`all`，见 `pyproject.toml`）
  - 配置：`[tool.pytest.ini_options]`，`testpaths=["tests"]`，`addopts="-q --strict-markers"`
  - 自定义 marker：`slow`（端到端较慢用例）、`determinism`（确定性回归用例）
  - 11 个测试文件，README 声称覆盖 177 个用例

**Build/Dev:**
- setuptools ≥68（`[build-system]`），标准 `setuptools.build_meta` 后端
- 包发现：`[tool.setuptools.packages.find]` `where=["src"]`（src-layout）
- CLI 入口：`[project.scripts]` `vela = "vela.cli:main"`

## Key Dependencies

**必需（`requirements.txt` / `pyproject.toml` `dependencies`）：**
- `duckdb>=1.0` — 唯一的列式数据库/查询引擎，单文件本地库（无服务端进程）
- `pyarrow>=14` — Parquet 列式存储读写，供 DuckDB 与仿真数据集使用
- `PyYAML>=6.0` — 全部 `config/*.yaml` 的解析，见 `src/vela/config.py::load_yaml`
- `pytz>=2024.1` — DuckDB 返回 `TIMESTAMPTZ` 到 Python 时的时区处理（注释见 `requirements.txt`）

**可选加速（`requirements-optional.txt`，缺失时自动降级，不影响功能）：**
- `xxhash>=3.4` — `norm_hash`/`row_hash` 用 xxh3-64；缺失时回退 `hashlib.blake2b`（见 `src/vela/util/hashing.py`）
- `blake3>=0.4` — `raw_hash` 用 BLAKE3-128；缺失时回退 `hashlib.blake2b`
- `fastapi>=0.110` — `vela serve` 优先使用；缺失时 `src/vela/server/app.py` 自动降级到标准库 `http.server`
- `uvicorn>=0.29` — FastAPI 的 ASGI 服务器；同样有标准库降级路径
- `pytest>=8.0` — 测试运行器（重复列在可选依赖，供仅需测试而非全部功能的场景）

**基础设施：**
- 无外部消息队列/缓存/ORM 依赖；持久化全部走本地文件系统（DuckDB 文件 + Parquet + JSON/JSONL）

## Configuration

**Environment（`.env.example` → `cp .env.example .env`）：**
- `VELA_LLM_PROVIDER` — `mock | volcengine | openai_compat`，模型网关唯一切换开关
- `VELA_ARK_API_KEY` / `VELA_ARK_BASE_URL` / `VELA_ARK_MODEL` / `VELA_ARK_EMBED_MODEL` — 火山引擎方舟接入
- `VELA_OPENAI_API_KEY` / `VELA_OPENAI_BASE_URL` / `VELA_OPENAI_MODEL` — 任意 OpenAI 兼容端点
- `VELA_WORKSPACE`（默认 `./workspace`）、`VELA_PROFILE`（`poc|production`）、`VELA_TENANT`（默认 `demo-tenant`）、`VELA_LOG_LEVEL`
- `PYTHONHASHSEED=0` — 确定性要求，固定哈希种子（供仿真器/mock 供应商可复现输出）
- `VELA_CONFIG_DIR` — 覆盖默认 `config/` 目录路径（见 `src/vela/config.py::config_dir`）
- 加载优先级（`src/vela/config.py` 顶部注释）：显式函数参数 > 环境变量 > `config/*.yaml` > 代码内默认值；业务代码不直接读 `os.environ`，全部收敛在 `config.py`/`gateway/*`

**Config files（`config/`，YAML 驱动，改行为不改代码）：**
- `config/pipeline.yaml` — 解包/发现/解析/时间/模板/写出/QA 全部阈值
- `config/parsers.yaml` — 13 个日志格式解析器（正则+优先级），`ParserRegistry` 完全由此驱动
- `config/ota_phases.yaml` — 9 条 OTA 阶段识别规则 + 15 个 UDS NRC 语义字典
- `config/budget.yaml` — `poc`/`production` 双档预算（压缩/计量/护栏），`VELA_PROFILE` 切换
- `config/llm.yaml` — 模型网关：逻辑模型映射、供应商配置、脱敏规则、审计开关
- `config/skills/builtin.yaml` — 12 个内置诊断技能（触发条件+探针+关键词+根因标签）

**Build：**
- `pyproject.toml`（PEP 621 项目元数据 + 依赖 + pytest 配置）
- `Makefile`（`install`/`install-dev`/`doctor`/`sim`/`build`/`agent`/`eval`/`test`/`test-fast`/`bench`/`serve`/`lint`/`clean`/`clean-all`）
- `run_all.sh`（一键全流程：环境自检→仿真→建库→诊断→评测→测试，`set -euo pipefail`）
- `lint` 目标不是 flake8/ruff，而是自制的 `ast.parse` 语法检查（`Makefile` 中 `lint:` 目标）——**无正式 linter/formatter 配置**（未检测到 `.eslintrc`/`ruff.toml`/`.flake8`/`pyproject.toml` 中的 `[tool.ruff]`/`[tool.black]` 等）

## Platform Requirements

**Development:**
- Python 3.11+，`pip install -e ".[all]"` 或 `pip install -r requirements.txt -r requirements-optional.txt`
- 无需 Docker、无需外部数据库、无需网络（mock 供应商下）

**Production:**
- 单机单进程部署（DuckDB 为单文件数据库，未做分布式）；`docs/PRODUCTION_MIGRATION.md` 给出向 ClickHouse/StarRocks、Kafka/Pulsar、Redis 等生产组件迁移的路线图
- 生产接入真实大模型仅需切换环境变量 `VELA_LLM_PROVIDER=volcengine`，不改代码

---

*Stack analysis: 2026-07-30*

# VELA —— 车端 OTA 日志证据化诊断平台
# 本地优先，无 Docker 依赖。所有目标均可独立运行。

SHELL := /bin/bash
PYTHON ?= python3
VENV := .venv
DATASET_DIR ?= ./data/dataset
WORKSPACE ?= ./workspace

.PHONY: help install install-dev doctor sim build query agent eval eval-repeat baseline bench-volc test test-fast \
        demo bench serve clean clean-all lint

help:
	@echo "VELA 常用命令："
	@echo "  make install       安装运行期依赖（duckdb/pyarrow/PyYAML/pytz/python-dotenv/openai）"
	@echo "  make install-dev   安装含可选加速件与测试依赖（xxhash/blake3/fastapi/pytest）"
	@echo "  make doctor        环境自检"
	@echo "  make sim           生成 10 场景仿真数据集到 $(DATASET_DIR)"
	@echo "  make build ARCHIVE=path/to.zip WS=workspace/xxx   建立列式取证库"
	@echo "  make demo          一条命令跑通仿真->建库->诊断->证据验证全链路"
	@echo "  make eval          跑全部黄金评测（10 场景）"
	@echo "  make test          跑全部 177 个单元/集成测试"
	@echo "  make test-fast     只跑不依赖建库的快速用例（util/sim/gateway/obs）"
	@echo "  make bench         建库吞吐 + 诊断延迟基准测量"
	@echo "  make serve DB=workspace/xxx/gold/analysis.duckdb   启动本地 HTTP 服务"
	@echo "  make clean         清理 workspace/ 与仿真数据集（保留 venv）"
	@echo "  make clean-all     清理 workspace/ + 仿真数据集 + venv + 缓存"

$(VENV)/bin/python3:
	$(PYTHON) -m venv $(VENV)

install: $(VENV)/bin/python3
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt

install-dev: $(VENV)/bin/python3
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt -r requirements-optional.txt
	$(VENV)/bin/pip install -e .

doctor:
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli doctor

sim:
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli sim generate --out $(DATASET_DIR)

# 用法: make build ARCHIVE=data/dataset/OTA_xxx.zip WS=workspace/demo
build:
	@test -n "$(ARCHIVE)" || (echo "用法: make build ARCHIVE=path/to.zip WS=workspace/xxx"; exit 1)
	@test -n "$(WS)" || (echo "用法: make build ARCHIVE=path/to.zip WS=workspace/xxx"; exit 1)
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli build $(ARCHIVE) $(WS)

# 用法: make query DB=workspace/demo/gold/analysis.duckdb TOOL=describe_dataset
query:
	@test -n "$(DB)" || (echo "用法: make query DB=path/to.duckdb TOOL=describe_dataset"; exit 1)
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli query --db $(DB) --tool $(or $(TOOL),describe_dataset)

# 用法: make agent DB=workspace/demo/gold/analysis.duckdb
agent:
	@test -n "$(DB)" || (echo "用法: make agent DB=path/to.duckdb"; exit 1)
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli agent diagnose --db $(DB) --workspace $(WORKSPACE)

demo:
	$(PYTHON) scripts/demo_end_to_end.py $(if $(SCENARIO),--scenario $(SCENARIO),)

eval: sim
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli eval run \
		--dataset $(DATASET_DIR) --workspace $(WORKSPACE)/eval --out $(WORKSPACE)/eval/report

# mock 重复评测冒烟（N=2，可复用 workspace；不触发付费）
eval-repeat: sim
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli eval run \
		--dataset $(DATASET_DIR) --workspace $(WORKSPACE)/eval \
		--out $(WORKSPACE)/eval/report-repeat --repeat 2 --reuse-workspace --provider mock

# 付费真实基线（METR-09）：显式目标，不并入 test/eval
baseline: sim
	PYTHONPATH=src VELA_CONFIG_DIR=config VELA_LLM_PROVIDER=volcengine $(PYTHON) -m vela.cli doctor --json > .planning/phases/02-metrics-baseline/baseline/doctor.json || true
	PYTHONPATH=src VELA_CONFIG_DIR=config VELA_LLM_PROVIDER=volcengine $(PYTHON) -m vela.cli eval run \
		--dataset $(DATASET_DIR) --workspace $(WORKSPACE)/baseline-eval \
		--out .planning/phases/02-metrics-baseline/baseline \
		--provider volcengine --no-cache --repeat 3 --reuse-workspace

bench-volc:
	PYTHONPATH=src VELA_CONFIG_DIR=config VELA_LLM_PROVIDER=volcengine $(PYTHON) scripts/bench.py \
		--dataset $(DATASET_DIR) --workspace $(WORKSPACE)/bench-volc \
		--provider volcengine --no-cache --repeat 1 \
		--out .planning/phases/02-metrics-baseline/baseline/bench_result.json

test:
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m pytest tests/ -q

test-fast:
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m pytest tests/test_util.py tests/test_sim.py \
		tests/test_gateway.py tests/test_obs_and_config.py -q

bench:
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) scripts/bench.py --dataset $(DATASET_DIR) --workspace $(WORKSPACE)/bench

# 用法: make serve DB=workspace/demo/gold/analysis.duckdb [PORT=8848]
serve:
	@test -n "$(DB)" || (echo "用法: make serve DB=path/to.duckdb"; exit 1)
	PYTHONPATH=src VELA_CONFIG_DIR=config $(PYTHON) -m vela.cli serve --db $(DB) --port $(or $(PORT),8848)

lint:
	$(PYTHON) -c "import ast,pathlib; \
	[ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('src').rglob('*.py')]; \
	print('OK: 全部源文件语法通过')"

clean:
	rm -rf $(WORKSPACE) $(DATASET_DIR)
	find . -name "__pycache__" -o -name "*.pyc" | xargs rm -rf
	rm -rf .pytest_cache

clean-all: clean
	rm -rf $(VENV)

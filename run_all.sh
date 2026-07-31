#!/usr/bin/env bash
# VELA 一键全流程脚本：环境自检 -> 仿真 -> 建库 -> 诊断 -> 评测 -> 测试
# 用法：./run_all.sh [--skip-tests] [--skip-eval]
#
# 无 Docker、无外部服务依赖；默认使用 mock 大模型（确定性、零 API 调用）。
# 全程本地跑通，供首次拉取项目后快速验证"一切按预期工作"。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src"
export VELA_CONFIG_DIR="$ROOT/config"
export VELA_WORKSPACE="$ROOT/workspace/run_all"
export PYTHONHASHSEED=0
# 演示链路钉死 mock：.env 若为 volcengine，不得在 diagnose/eval 打真实付费 API。
# 进程环境优先于 dotenv（override=False），故须在调用 Python 前 export。
export VELA_LLM_PROVIDER=mock

# 与 Makefile / Plan 01 解释器约定对齐：优先 PYTHON=，其次 .venv，最后系统 python3
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$ROOT/.venv/bin/python3" ]; then
    PYTHON="$ROOT/.venv/bin/python3"
  else
    PYTHON="python3"
  fi
fi

DATASET_DIR="$ROOT/data/dataset"
SKIP_TESTS=0
SKIP_EVAL=0
for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=1 ;;
    --skip-eval)  SKIP_EVAL=1 ;;
    *) echo "未知参数: $arg（支持 --skip-tests / --skip-eval）"; exit 1 ;;
  esac
done

hr() { printf '\n%s\n  %s\n%s\n' "════════════════════════════════════════════════════════════════" "$1" "════════════════════════════════════════════════════════════════"; }

hr "第 1/6 步：环境自检"
"$PYTHON" -m vela.cli doctor

hr "第 2/6 步：生成仿真数据集（10 场景，约 23 万条记录）"
if [ -d "$DATASET_DIR" ] && [ -n "$(ls -A "$DATASET_DIR"/*.zip 2>/dev/null)" ]; then
  echo "数据集已存在于 ${DATASET_DIR}，跳过（如需重新生成请先删除该目录）"
else
  "$PYTHON" -m vela.cli sim generate --out "$DATASET_DIR"
fi

hr "第 3/6 步：建立列式取证库（以 S3_UDS_NRC72 场景为例）"
DEMO_ARCHIVE=$(ls "$DATASET_DIR"/OTA_*TASK-10069*.zip 2>/dev/null | head -1 || true)
if [ -z "$DEMO_ARCHIVE" ]; then
  DEMO_ARCHIVE=$(ls "$DATASET_DIR"/*.zip | head -1)
fi
"$PYTHON" -m vela.cli build "$DEMO_ARCHIVE" "$VELA_WORKSPACE/demo"

hr "第 4/6 步：Agent 七节点诊断（provider=mock，确定性）"
"$PYTHON" -m vela.cli agent diagnose \
  --db "$VELA_WORKSPACE/demo/gold/analysis.duckdb" \
  --workspace "$VELA_WORKSPACE/demo" \
  --session-id "RUN-ALL-DEMO"

if [ "$SKIP_EVAL" -eq 0 ]; then
  hr "第 5/6 步：黄金评测（全部 10 场景）"
  "$PYTHON" -m vela.cli eval run \
    --dataset "$DATASET_DIR" \
    --workspace "$VELA_WORKSPACE/eval" \
    --out "$VELA_WORKSPACE/eval/report"
else
  hr "第 5/6 步：跳过评测（--skip-eval）"
fi

if [ "$SKIP_TESTS" -eq 0 ]; then
  hr "第 6/6 步：全部单元/集成测试（177 个用例）"
  "$PYTHON" -m pytest tests/ -q
else
  hr "第 6/6 步：跳过测试（--skip-tests）"
fi

hr "全部完成 ✅"
echo "产物位置："
echo "  建库+诊断工作区: $VELA_WORKSPACE/demo"
if [ "$SKIP_EVAL" -eq 0 ]; then
  echo "  评测报告        : $VELA_WORKSPACE/eval/report/eval_report.md"
fi
echo ""
echo "下一步可尝试："
echo "  python scripts/demo_end_to_end.py --scenario S6_ECU_SILENT"
echo "  make serve DB=$VELA_WORKSPACE/demo/gold/analysis.duckdb"

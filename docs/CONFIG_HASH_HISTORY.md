# config_hash 断代映射表（NR-6）

证据包 / runs 写入的 `config_hash` 口径变更时在此追加一行。历史证据包仍使用当时的 salt，**不批量重算**。

| date | old_hash | new_hash | added_inputs | reason |
|------|----------|----------|--------------|--------|
| 2026-07-31 | `sha256:32d709b34dfebf66c7545187b5e27eb5d2670e23182d2de314af572689ebef0a` | `sha256:7fe5f44c81d6a6c0f5e2e010505fad8b71d65913a5893e3821c3374d1afe574a` | `skills` via `load_skills()`；`budget.yaml`；`llm.yaml`；`gateway/prompts.py` → `prompts_sha256` | Phase 2 METR-03 / NR-6：首次扩展指纹覆盖（保留 pipeline/parsers/ota_phases/canon_rules/algos；继续排除 `env_checks.yaml`） |
| 2026-07-31 | `sha256:7fe5f44c81d6a6c0f5e2e010505fad8b71d65913a5893e3821c3374d1afe574a` | `sha256:c1377375a18671772f4101bbdf4584dfb84ec9fc14ddd5a7981ecc375eba3c3e` | （口径不变；payload 内容变）`budget.yaml` 新增顶层 `cost:` | Phase 2 PERF-02：成本单价/告警阈值入配置，指纹随之变化 |

采样命令（断代当日）：

```bash
# 扩展前（git show 旧 config_hash 实现后）
PYTHONPATH=src VELA_CONFIG_DIR=config python3 -c "from vela.config import config_hash; print(config_hash())"
# 扩展后同命令 → new_hash
```

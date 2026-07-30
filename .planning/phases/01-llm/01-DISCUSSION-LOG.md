# Phase 1: 真实 LLM 环境就绪 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-31
**Phase:** 1-真实 LLM 环境就绪
**Areas discussed:** 加载器实现口径、优先级与作用域、doctor 连通性口径、输出形态与实测验收

---

## 加载器实现口径

### Q1 — `.env` 加载器的挂载点

| Option | Description | Selected |
|--------|-------------|----------|
| config.py 导入时自动加载 | 符合「配置入口唯一收口」铁律，CLI/pytest/serve/脚本全覆盖，调用方零改动；风险是导入副作用难绕开 | ✓ |
| cli.main() 里显式调用 | 导入无副作用、易测；但 pytest 不走 main()，serve/bench/脚本会漏 | |
| 独立模块 + 两处显式调用 | 职责最清晰、两入口行为可不同；新增入口容易遗漏 | |

**User's choice:** config.py 导入时自动加载

### Q2 — 手写解析器的语法子集

| Option | Description | Selected |
|--------|-------------|----------|
| 严格最小集 | 只支持 KEY=VALUE / 引号 / export 前缀，不处理行尾注释，奇怪值交给 doctor 报 | ✓（后作废） |
| 最小集 + 行尾注释剥离 | 对齐 python-dotenv 行为，但值内合法 `#` 会被静默截断 | |
| 最小集 + 变量插值 | 支持 `${VAR}` 展开；当前 9 个变量无一需要 | |

**User's choice:** 严格最小集
**Notes:** 用户随后推翻整道题的前提——禁止手写解析器，改用 python-dotenv，语法子集由库定义。此答案作废。

### Q3 — 「优先用成熟三方库」的适用范围

| Option | Description | Selected |
|--------|-------------|----------|
| 项目级永久变更 | 写进 PROJECT.md + AGENTS.md，取代「依赖最小化」纪律，Phase 2~6 同样适用 | ✓ |
| 仅 .env 加载这一处特例 | 只改 ENV-01 需求文本，其余纪律保留 | |
| 项目级变更 + 保留两条底线 | 同项目级，但明文保留本地优先与单线程单进程 | |

**User's choice:** 项目级永久变更
**Notes:** 用户原话：「项目必须打破不新增依赖库的约束限制，能使用专业三方开源库组件的功能尽可能避免重复造轮子手写开发，比如加载 .env 文件环境配置，禁止手写实现直接引入新的依赖解决处理。」

### Q4 — 是否顺带替换 gateway 的手写 HTTP 层

| Option | Description | Selected |
|--------|-------------|----------|
| 只引 python-dotenv，gateway 不动 | 改动面最小、回归风险最低；但 doctor 的连通性探测又要自己写一层 HTTP | |
| 同步换成 openai SDK | 重试/超时/错误分类交给 SDK，doctor 直接用异常类型判定四项结论 | ✓ |
| 只换 HTTP 底层为 httpx | 保留自己的 payload 组装，不绑定 openai 协议语义 | |

**User's choice:** 同步换成 openai SDK

### Q5 — 其他架构铁律是否同步松绑

| Option | Description | Selected |
|--------|-------------|----------|
| 只作废「依赖最小化」一条 | 本地优先/单线程单进程/查询唯一收口/图节点即方法/不用 logging/出站脱敏 全部仍有效 | ✓ |
| 底线也按需重评 | 本地优先与单线程单进程也不再是硬约束 | |
| 只作废依赖最小化 + 退化路径也废 | 附带清理 xxhash/fastapi 等 try-import 双路径 | |

**User's choice:** 只作废「依赖最小化」一条
**Notes:** 第三项被记入 CONTEXT.md 的 Deferred Ideas。

### Q6 — 新依赖的分类

| Option | Description | Selected |
|--------|-------------|----------|
| 都进必需依赖 | .env 加载失败即需求失败，不应有静默降级；openai SDK 缺失时 provider 本就无法工作 | ✓ |
| dotenv 必需，openai 可选 | 保持纯 mock 安装轻量；代价是多一条 try-import 分支 | |
| 先合并依赖文件再加 | 顺带把两个 requirements 文件并入 pyproject.toml | |

**User's choice:** 都进必需依赖
**Notes:** 「先合并依赖文件」被记入 Deferred Ideas。

---

## 优先级与作用域

### Q7 — 测试进程里 `.env` 的 provider 是否生效

| Option | Description | Selected |
|--------|-------------|----------|
| conftest 硬锁 mock，凭证照读 | setdefault 改无条件赋值；VELA_ARK_* 仍从 .env 读，ENV-01 仍成立 | ✓ |
| .env 全量生效，不特殊处理 | 语义最简；但本地 .env 切 volcengine 后 make test 会发起上百次付费调用 | |
| 测试完全不加载 .env | 环境完全密封；直接违反 ENV-01，ENV-02 验收用例拿不到凭证 | |

**User's choice:** conftest 硬锁 mock，凭证照读

### Q8 — `.env` 文件查找路径

| Option | Description | Selected |
|--------|-------------|----------|
| 锁定项目根 | 与 config.py 的 _DEFAULT_CONFIG_DIR 同源推导，不受 cwd 影响 | ✓ |
| cwd 向上回溯 | python-dotenv 的 find_dotenv() 原生行为，pip 安装后仍工作 | |
| VELA_ENV_FILE 优先 + 回溯兜底 | CI/多环境有显式导口 | |

**User's choice:** 锁定项目根
**Notes:** pip install 到 site-packages 后 parents[2] 不再是项目根 —— 作为 Open Question 留给 planner。

### Q9 — 是否给 `.env` 覆盖已有环境变量留逃生舱

| Option | Description | Selected |
|--------|-------------|----------|
| 不留，只有一种行为 | 永远 override=False；临时覆盖走 shell 前置赋值 | ✓ |
| 给 VELA_DOTENV_OVERRIDE=1 | 父进程注入陈旧变量时能让 .env 强制赢 | |
| 给 vela --env-file 全局参数 | 与「挂载点在 config.py 导入时」冲突，需额外重加载机制 | |

**User's choice:** 不留，只有一种行为

### Q10 — `.env` 加载行为的可观测性

| Option | Description | Selected |
|--------|-------------|----------|
| 默默加载，只在 doctor 里报 | 导入时零输出，诊断信息集中在 vela doctor | ✓ |
| 加载结果挂到可查询函数 | 额外暴露 config.dotenv_report() 供 doctor/server/评测消费 | |
| 加载时发 MILESTONE 事件 | config.py 反向依赖 obs 模块有循环导入风险 | |

**User's choice:** 默默加载，只在 doctor 里报

---

## doctor 连通性口径

### Q11 — doctor 默认是否发真实网络请求

| Option | Description | Selected |
|--------|-------------|----------|
| 默认离线，--online 才联网 | run_all.sh/make demo 保持完全离线，CI 不会因断网或无凭证而红 | |
| 默认联网，--offline 跳过 | 最贴 ENV-03 字面意图；但 demo 链路必须显式传 --offline | |
| 按 provider 自动判定 | mock 跳过、volcengine/openai_compat 自动联网；意图推断最自然，代价是行为隐式 | ✓ |

**User's choice:** 按 provider 自动判定

### Q12 — 「模型可用」怎么探

| Option | Description | Selected |
|--------|-------------|----------|
| 最小 chat 调用 | 一发同时验证端点/鉴权/接入点可跑，对 ep-xxxx 接入点制是唯一可靠方式 | ✓ |
| 先 /models 列表，不行再 chat | 常规情况不花钱；但两条探测路径 = 两套错误语义与两倍测试 | |
| 只探端点与鉴权，不验模型 | 成本最低；直接失败 ENV-03 的「模型可用」验收标准 | |

**User's choice:** 最小 chat 调用

### Q13 — 连通性失败时的退出码

| Option | Description | Selected |
|--------|-------------|----------|
| 本地错误才非零 | 配置/依赖/形态错误返 1；网络类失败显著报 ❌ 但返 0，保证 run_all.sh 不断链 | ✓ |
| 任何失败都非零 | 语义直白、适合当 CI 门禁；一次 429 限流就让演示跑不起来 | |
| 分级退出码 | 0/1/2 三档，调用方自行决定；退出码语义变多需文档化 | |

**User's choice:** 本地错误才非零

### Q14 — 四个逻辑模型的映射完整性怎么验

| Option | Description | Selected |
|--------|-------------|----------|
| 本地解析 + 去重后探测 | 先用 models_for() 零成本判定链是否为空，再对去重后的物理模型各探一次；典型配置只花 1 次 | ✓ |
| 逐逻辑模型各探一次 | 四者真映射到不同接入点时逐个验真；典型配置下 4 倍重复调用 | |
| 只验默认模型 + 本地列映射 | 成本最低；VELA_ARK_MODEL_PLANNER 填错时报不出来 | |

**User's choice:** 本地解析 + 去重后探测

### Q15 — 是否给显式覆盖开关

| Option | Description | Selected |
|--------|-------------|----------|
| 只给 --offline | 单向逃生舱，保持「意图由 provider 表达」的单一心智模型 | |
| 不加任何开关 | 完全由 VELA_LLM_PROVIDER 决定，零新增参数 | |
| --offline 与 --online 都给 | 两个方向都能强制覆盖默认推断 | ✓ |

**User's choice:** --offline 与 --online 都给
**Notes:** 与 Q9「不留逃生舱」并不矛盾——Q9 是优先级规则（多一条规则多一类疑案），此处是执行开关（不改变任何优先级语义）。

---

## 输出形态与实测验收

### Q16 — ENV-04 形态检查规则写在哪

| Option | Description | Selected |
|--------|-------------|----------|
| config/env_checks.yaml 驱动 | 符合「规则一律放 config/*.yaml」铁律，新增变量零代码改动；需明确它不进 config_hash | ✓ |
| 写在 doctor 代码里 | 改动面最小；与配置驱动铁律相背 | |
| 复用 config/llm.yaml 扩展字段 | 与 provider 定义同处；但会与 Phase 2 METR-04 的 config_hash 扩充耦合 | |

**User's choice:** config/env_checks.yaml 驱动
**Notes:** 此题第一次提出时被用户中断——彼时前提是手写解析器。改用 python-dotenv 后行尾注释已在加载层被正确剥离，ENV-04 重心转移到 base_url 路径异常，题目重述后回答。

### Q17 — doctor 输出的掩码规则

| Option | Description | Selected |
|--------|-------------|----------|
| key 重掩码，其余明文 | API key 只显首尾各 4 位；base_url 与 ep-xxxx 明文——它们不是凭证，看不到就没法对照排查 | ✓ |
| key 与接入点 ID 都掩 | 更贴 AGENTS.md 字面表述；接入点填错时排查要回头 cat .env | |
| 全部明文 + --mask 才掩 | 默认不安全，粘贴输出即泄密 | |

**User's choice:** key 重掩码，其余明文

### Q18 — ENV-02 的可复现验收形态

| Option | Description | Selected |
|--------|-------------|----------|
| pytest 标记 + 默认跳过 | realllm 标记默认被 addopts 排除，验收标准代码化且 make test 不会误触发 | ✓ |
| make 目标 + 人工看报告 | 实现最轻；验收依赖人眼，Phase 2 无现成回归钩子 | |
| 两者都要 | 硬验收 + 便捷入口；多维护一个入口 | |

**User's choice:** pytest 标记 + 默认跳过

### Q19 — 是否提供 `--json` 输出

| Option | Description | Selected |
|--------|-------------|----------|
| 本期不加 | 无下游消费者，避免拍一个会被推翻的 schema | |
| 加 --json | Phase 2 要把环境指纹写进评测报表，届时直接消费；实现上收成 list[dict] 再双通道渲染 | ✓ |

**User's choice:** 加 --json

---

## Claude's Discretion

- `.env.example` 注释重排的具体版式
- `config/env_checks.yaml` 的字段命名与 schema 形状
- doctor 输出排版与 `--json` 的 key 命名
- openai SDK 客户端的构造位置与复用策略

## Deferred Ideas

- 清理现有可选依赖的降级分支（xxhash / blake3 / fastapi 的 try-import 双路径）
- 补一份 lockfile
- 其他手写轮子的替换清单（evidencepack 的 Merkle 实现、自制 ast.parse lint → ruff）
- 合并 requirements.txt / requirements-optional.txt 到 pyproject.toml 单一它源

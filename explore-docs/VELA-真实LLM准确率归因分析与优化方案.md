# 真实 LLM 实测准确率 44.4% 归因分析与优化方案

> 现象：接入真实 LLM + 高 token 预算 + 同一仿真数据集，Top-1 根因准确率从 mock 的 100% 跌至 **44.4%**，多个场景 Agent **过早 stop**
> 分析方法：mock 与真实模型的行为契约分叉点逐条代码核查（已核实，附行号）
> 目标：真实场景 ≥ 80%

---

## 0. 执行摘要

### 0.1 核心判断

**44.4% 不是模型能力问题，是编排层与提示词的结构性缺陷——这些缺陷在 mock 下被系统性掩盖了。**

根本原因在于 mock 的双重身份：它既是**实现**（确定性规则引擎），又被当成了**规范**（"通过 mock 测试 = 契约正确"）。但 mock 从不阅读提示词正文，只解析 `[[VELA_STATE]]` 里的结构化状态并按关键词打分。**凡是"提示词写了什么"与"mock 做了什么"不一致的地方，177 个测试全部测不到**——而真实 LLM 恰恰严格遵循提示词字面。

### 0.2 数值吻合度

44.4% = **4/9**。9 个故障场景中 5 个失败。这与"首轮 stop → `evidence_pool` 为空 → `unanswerable` → `predicted_label = None` → 计为 miss"的失效路径在数量级与离散值上精确吻合。

```python
# graph.py:322-331  —— 首轮 stop 的代价是"全损"，不是"降级"
if plan["stop"] or not plan["actions"]:
    if st.evidence_pool:                    # 首轮时恒为空（见 D2）
        self.node_report(...); st.status = "answered"
    else:
        self.node_unanswerable(...)         # → predicted_label = None → 直接判错
    break
```

**首轮 stop 没有任何补救**：不重试、不降级、不兜底，直接终局。

### 0.3 已定位缺陷排序

| ID | 缺陷 | 影响 | mock 为何测不出 | 修复成本 |
|---|---|---|---|---|
| **D1** | 提示词第 5 条直接诱导首轮 stop | 🔴 极高 | mock 不读提示词正文 | 极低 |
| **D2** | planner 全程看不到已获证据（反馈闭环断裂） | 🔴 极高 | mock 靠关键词打分，首轮即命中，无需反馈 | 中 |
| **D3** | verifier 判据是脆弱字符串精确匹配 | 🔴 高 | mock 恒返回 `"supported"` | 低 |
| **D4** | 技能"用过即剔除"与 D3 复合，把正确假设锁死 | 🟠 高 | mock 首轮收敛，从不进入第二轮 | 低 |
| **D5** | JSON 解析失败静默降级为 stop | 🟠 中高 | mock 输出恒为合法 JSON | 低 |
| **D6** | `max_tokens` 过紧导致输出截断 | 🟠 中 | mock 输出极短 | 极低 |

**高 token 预算排除了预算切断这一嫌疑**——`BudgetExceeded` 会走 `unanswerable` 并在 `unresolved` 里留下"预算耗尽"字样，与"过早 stop"的现象描述不符。

---

## 1. mock 与真实模型的契约分叉

| 提示词字面要求 | mock 实际行为 | 真实 LLM 行为 | 分叉后果 |
|---|---|---|---|
| "证据不足时输出 stop=true" | **完全忽略**；仅当候选全零分才 stop | 首轮无证据 → 遵照执行 → stop=true | **D1 首轮终止** |
| "每一轮只选择一个最相关的诊断技能" | 按加权关键词打分选 Top-1 | 语义理解选择，但看不到已获证据 | **D2 盲目游走** |
| "只输出 JSON" | 恒输出合法 JSON | 可能带前言/围栏/截断 | **D5/D6 解析失败** |
| verifier "判断是否被充分支撑" | 引用 ⊆ 已知集合即 `"supported"` | 严格判断，常返回 `"weak"` | **D3 永不收敛** |

**关键认识**：mock 是按**设计意图**实现的，真实 LLM 是按**文本字面**执行的。两者的差集就是缺陷集合。

---

## 2. 缺陷详析

### D1 提示词第 5 条直接诱导首轮 stop 🔴

**代码证据**（`prompts.py::PLANNER_SYSTEM`）：

```
5. 证据不足时输出 stop=true 并说明还缺什么，不允许编造。
```

**问题本质**：该条把两个完全不同的判断混为一谈——

- "证据不足以**下结论**" → 正确行为是**继续调查**
- "证据不足以**继续调查**" → 才应该 stop

**首轮的状态是什么？** `node_plan` 在 round 1 执行完鸟瞰探针后，`evidence_pool` **必然为空**（鸟瞰结果只进 `signals`/`evidence_digest`，不进证据池，见 D2）。一个严格遵循指令的模型此刻读到第 5 条，唯一合规的动作就是 `stop=true`。

**这不是模型"偷懒"，恰恰是模型"听话"。** 提示词第 4 条还强化了这一倾向："任何结论必须能落到具体日志行，不能凭经验推测"——模型合理推断"我现在没有任何日志行，所以不能下结论，所以按第 5 条 stop"。

**修复**（改提示词即可，零代码）：

```
5. 停止条件（严格区分，不可混淆）：
   - 你的任务是【调查】，不是【立即定论】。只要还有未验证的候选技能，就必须继续下钻。
   - stop=true 仅在以下情形使用：
     (a) 全部候选技能均与当前信号无关，继续下钻只会浪费预算；
     (b) 已连续多轮下钻且未获得任何新证据。
   - 【禁止】因为"当前还没有证据"而 stop —— 没有证据正是你要去取证的理由。
   - 首轮永远不允许 stop：你必须至少执行一个技能的探针。
```

**同时加程序化守卫**（不能只靠提示词，见 §3.2）。

---

### D2 planner 全程看不到已获证据 🔴

**代码证据**（`graph.py:145-149`）：

```python
payload = {"round": st.round_no, "question": st.question, "signals": st.signals,
           "evidence_digest": st.evidence_digest[:40],
           "candidate_skills": cands, "excluded_skills": st.excluded_skills(),
           "used_skills": st.used_skills,
           "budget": self.ledger.snapshot()}
```

**payload 中不存在**：上一轮检索到的证据行、压缩痕迹（`compression_trace`）、护栏提示（`notes`）、verifier 的判定结果（`verdicts`）。

且 `search_logs`/`get_lines`/`get_context` 的结果**只进 `rows` → 压缩 → `evidence_pool`，不进 `evidence_digest`**：

```python
# graph.py:185-189
if res.ok and res.rows and tool in ("search_logs", "get_lines", "get_context"):
    rows.extend(res.rows)                       # → 只给 verifier
elif res.ok and res.rows:
    st.evidence_digest.extend(...)              # 非下钻工具才进 digest
```

**后果**：round 2 的 planner 看到的信息与 round 1 **几乎完全相同**（只多了 `used_skills`）。它无法知道"上一轮我查到了 NRC 0x72，现在应该去确认 Flash 健康度"。它只能在关键词层面重新猜一个技能——这是**随机游走，不是推理**。

这也意味着交底书**机制一的"压缩痕迹回馈闭环"只实现了一半**：`compression_trace` 被送给了 verifier（`graph.py:221`），却没送给真正需要它做决策的 planner。模型不知道哪些证据被折叠了，自然无法发起精确的二次下钻。

**mock 为何无感**：mock 首轮即按关键词命中正确技能并收敛，从未进入需要"基于已有证据决定下一步"的第二轮。

**修复**：payload 增加四类反馈（详见 §4.2）。

---

### D3 verifier 判据是脆弱字符串精确匹配 🔴

**代码证据**（`graph.py:233-235`）：

```python
supported = [v for v in verdicts if v.get("status") == "supported"]
decisive = (bool(supported) and has_error_evidence and skill_id is not None
            and self.skills.label_of(skill_id) is not None)
```

**三重脆弱性**：

1. **大小写/变体敏感**：`"Supported"` / `"SUPPORTED"` / `"supported_with_caveats"` / `"partially_supported"` 全部落空
2. **语义过严**：真实模型被问"这条日志行能否支撑该结论"，对单行证据普遍给 `"weak"`——这是**正确且负责任**的判断，却导致系统永不收敛
3. **claim 构造是循环论证**（`graph.py:216-218`）：

```python
claims = [{"claim_id": f"C{i+1}",
           "claim": str(r.get("raw_line") ...)[:200],      # claim = 日志原文
           "citations": [r.get("row_hash")]}]              # citation = 同一行
```

**claim 和 citation 是同一行日志**。模型被要求判断"这行日志是否被这行日志支撑"——一个逻辑上的同义反复。真实模型面对这种输入的反应难以预测：可能指出循环、可能给 `weak`、可能拒答。mock 只做集合包含检查，永远返回 `supported`。

**这是整个验证环节的设计缺陷**：verifier 本应验证**根因假设**（"NRC 0x72 是本次失败的根因"）是否被证据链支撑，而不是验证"日志行是否等于它自己"。

**修复**：
- 判据改为归一化枚举匹配 + 分级（`supported`/`partial` 均可推进，仅 `unsupported` 阻断）
- claim 重构为**技能的根因假设**，citations 为**支撑该假设的多条证据**

---

### D4 "用过即剔除"与 D3 复合，把正确假设锁死 🟠

**代码证据**（`state.py::excluded_skills`）：

```python
return sorted(set(self.used_skills) | set(self.unproductive_skills))
```

这条策略在 mock 下是**优化**（首轮即收敛，剔除防止无谓重跑）；在真实 LLM 下是**灾难**：

```
round 1: 选中 SK-UDS-NRC（正确）→ 取到证据 → verifier 因 D3 返回 "weak" → 不 decisive
round 2: SK-UDS-NRC 已在 excluded 中 → 候选集里物理不存在 → 被迫选错误技能
round 3+: 继续在错误假设间游走
终局:   budget_exhausted → _last_productive_skill() → 可能返回错误技能的标签
```

**正确的假设被永久锁死，仅仅因为第一次验证没通过。** 而真实诊断恰恰需要对同一假设多轮深挖（先找 NRC，再查 Flash 健康度，再看电压排除干扰）。

**修复**：剔除策略改为**仅剔除"已用且未产出新证据"**（回归交底书原始语义），并允许同一技能在参数不同时复用。

---

### D5 JSON 解析失败静默降级为 stop 🟠

**代码证据**（`graph.py:51-65`）：解析失败返回 `{}`，随后：

```python
sid = out.get("selected_skill")        # None
actions = out.get("actions") or (...)  # [] （因为 sid 是 None）
# → if plan["stop"] or not plan["actions"]: → 终止
```

**解析失败与"模型主动 stop"在下游完全不可区分**，且：
- 无重试
- 无修复提示（re-ask）
- **无任何日志/指标记录**——`events.jsonl` 里看不到"解析失败"这个事实

这意味着如果真实 LLM 有 30% 的输出格式不合规，你在评测报告里只会看到"准确率降低"，永远定位不到原因。

**修复**：解析失败显式重试（附格式修复提示）+ 计入指标 + 发 ALERT 事件。

---

### D6 `max_tokens` 过紧导致截断 🟠

**代码证据**（`config/llm.yaml`）：

```yaml
planner:   {temperature: 0.1, max_tokens: 1024, json_mode: true}
verifier:  {temperature: 0.0, max_tokens: 768,  json_mode: true}
```

- **planner 1024**：`thought` + `selected_skill` + 多个 `actions`（含完整 args）。真实模型的 `thought` 普遍比 mock 长得多，容易超限
- **verifier 768**：最多 8 条 claims，每条需 `claim_id`/`status`/`citations`/`note`。8 × ~90 token ≈ 720，**几乎必然截断**

截断 → JSON 不完整 → D5 静默 stop。**D6 是 D5 的主要触发源。**

注意：`json_mode: true` 只保证格式是 JSON，**不保证不被 max_tokens 截断**。

**修复**：planner 提到 2048，verifier 提到 2048 并限制单批 claims ≤ 5；同时把 `thought` 长度在提示词中约束为一句话。

---

## 3. 用你手上的数据确认归因

系统已经记录了定位所需的全部信息，无需重跑即可判别。

### 3.1 判别命令

```bash
WS=./workspace/eval        # 换成你实测的 workspace

# ① stop 发生在第几轮？（D1 的直接证据）
python3 -c "
import json,glob,collections
c=collections.Counter()
for f in glob.glob('$WS/*/sessions/*.state.json'):
    st=json.load(open(f,encoding='utf-8'))
    c[(st['status'], st['round_no'])]+=1
for k,v in sorted(c.items()): print(f'  status={k[0]:22s} rounds={k[1]}  ×{v}')
"

# ② 模型给出的 stop 理由原文（D1 vs D5 的分水岭）
python3 -c "
import json,glob
for f in glob.glob('$WS/*/sessions/*.state.json'):
    st=json.load(open(f,encoding='utf-8'))
    if st['status']=='unanswerable':
        print(f\"  {st['session_id']}: {st.get('unresolved')}\")
"

# ③ verifier 实际返回了什么 status（D3 的直接证据）
grep -o '\"status\": *\"[a-zA-Z_]*\"' $WS/*/obs/llm_audit.jsonl 2>/dev/null | sort | uniq -c

# ④ 是否发生截断（D6）—— finish_reason 与 completion_tokens 触顶
python3 -c "
import json,glob,collections
c=collections.Counter(); mx=collections.defaultdict(int)
for f in glob.glob('$WS/*/obs/llm_audit.jsonl'):
    for line in open(f,encoding='utf-8'):
        r=json.loads(line); lm=r.get('logical_model')
        c[(lm, r.get('ok'))]+=1
        mx[lm]=max(mx[lm], r.get('completion_tokens') or 0)
print('  调用分布:', dict(c)); print('  各模型最大输出 token:', dict(mx))
"

# ⑤ 每轮技能选择轨迹（D2/D4 的证据：是否在游走）
python3 -c "
import json,glob
for f in sorted(glob.glob('$WS/*/sessions/*.state.json')):
    st=json.load(open(f,encoding='utf-8'))
    tr=[(r['round_no'], r['selected_skill'], len(r['new_row_hashes']), r['productive'])
        for r in st['rounds']]
    print(f\"  {st['session_id']:24s} {st['status']:18s} {tr}\")
"
```

### 3.2 判别矩阵

| 观测结果 | 结论 |
|---|---|
| 多数会话 `status=unanswerable` 且 `rounds=1` | ✅ **D1 确认**（首轮 stop 主因） |
| `unresolved` 含模型原话"证据不足/尚未获得证据" | ✅ **D1 确认**（模型在遵循第 5 条） |
| `unresolved` 是兜底话术"编排器判定无可用假设" | ⚠️ **D5 嫌疑**（解析失败伪装成 stop） |
| verifier `status` 分布中 `supported` 占比低 | ✅ **D3 确认** |
| `completion_tokens` 贴近 768/1024 上限 | ✅ **D6 确认** |
| 技能轨迹显示 `productive=True` 但仍继续换技能 | ✅ **D3+D4 复合确认** |
| 轨迹显示反复换技能且 `new_row_hashes` 递减 | ✅ **D2 确认**（盲目游走） |

---

## 4. 优化方案

### 4.1 Prompt 层（最高性价比，零代码）

#### (1) 角色重定义：调查员，不是裁判

当前提示词把模型定位成"编排器"，隐含"做决定"的语气；应改为**主动调查**的语气：

```
你是车联网 OTA 故障【调查员】。你的职责是通过工具主动搜集证据，直到能用具体日志行支撑结论。
你不能直接看到日志原文，必须通过工具查询。
【重要】没有证据不是停止的理由，而是继续调查的理由。
```

#### (2) 停止条件重写（见 D1 修复方案）

#### (3) 强制最小调查深度

```
每一轮你必须至少执行一个技能的探针（actions 不得为空数组），除非满足 stop 的两个严格条件之一。
首轮必须执行探针——此时你手上只有鸟瞰统计，这正是需要下钻的状态。
```

#### (4) 输出契约强化 + 长度约束（缓解 D6）

```
只输出 JSON，不要任何解释文字、不要 Markdown 围栏。
thought 字段限一句话（不超过 50 字），不要在其中展开推理过程。
```

#### (5) 加入正反 few-shot（针对首轮场景）

在 `planner_user()` 中嵌入两个示例——**首轮该做什么** / **什么时候才真的该 stop**。这是纠正 D1 最有效的手段，因为示例比规则更能约束模型行为。

#### (6) verifier 提示词重构（配合 D3）

```
你在校验【根因假设】是否被证据链支撑，不是校验单行日志是否等于自身。
status 三选一：
  supported —— 证据链可支撑该假设（允许存在未完全排除的替代解释）
  partial   —— 证据方向一致但不充分，需补充特定证据（在 note 中说明缺什么）
  unsupported —— 证据与假设矛盾，或引用不可解析
【标准】不要求"排除一切其他可能"才给 supported —— 诊断是概率推断，不是数学证明。
```

**最后一句至关重要**：真实模型倾向于用"数学证明"标准审查因果结论，这正是 `weak` 泛滥的根源。

### 4.2 编排层（状态与反馈闭环）

#### (1) planner payload 补全反馈（修复 D2）

```python
payload = {
    "round": st.round_no, "question": st.question, "signals": st.signals,
    "evidence_digest": st.evidence_digest[:40],
    "candidate_skills": cands, "excluded_skills": st.excluded_skills(),
    "used_skills": st.used_skills, "budget": self.ledger.snapshot(),

    # ---- 新增：让模型看见自己的调查进展 ----
    "evidence_so_far": _evidence_brief(st.evidence_pool, limit=25),   # 已获关键证据摘要
    "compression_trace": last_trace,          # 哪些被折叠了、如何取回（机制一闭环）
    "guardrail_notes": last_notes[:8],        # 护栏提示（截断/降级告警）
    "prior_verdicts": last_verdicts,          # 上一轮验证结论与缺口
    "open_questions": st.unresolved,          # 尚未回答的问题
}
```

`_evidence_brief` 应输出紧凑形式（ts/component/level/template_id/row_hash + 截断原文），控制在 ~1500 token 内。

#### (2) stop 的程序化守卫（不能只靠提示词）

```python
# node_plan 内，紧接 _parse_json 之后
if out.get("stop"):
    if st.round_no == 1:
        # 首轮 stop 一律驳回：此时必然还没有任何下钻证据
        self.bus.emit("plan.stop_rejected", Severity.ALERT, st.round_no,
                      reason="首轮不允许 stop", model_reason=out.get("reason"))
        self.metrics.inc("plan.stop_rejected")
        out["stop"] = False
        out["actions"] = out.get("actions") or self.skills.probes_of(sid) \
                         or self.skills.probes_of(_fallback_skill(cands))
    elif not st.evidence_pool:
        # 从未取到任何证据就想停 —— 同样驳回，强制走通用兜底技能
        out["stop"] = False
        out["actions"] = self.skills.probes_of("SK-GENERIC-EVIDENCE-FIRST")
```

**这是防御纵深的核心**：提示词负责引导，代码负责保证。二者缺一不可——提示词永远可能被模型以意外方式理解。

#### (3) JSON 解析失败的显式重试（修复 D5）

```python
def _llm_json(self, logical: str, system: str, user: str, retries: int = 2) -> dict:
    for attempt in range(retries + 1):
        text = self._llm(logical, system, user)
        out = _parse_json(text)
        if out:
            return out
        self.metrics.inc(f"llm.{logical}.parse_failure")
        self.bus.emit("llm.parse_failure", Severity.ALERT, self.state.round_no,
                      logical_model=logical, attempt=attempt, sample=text[:200])
        user = (user + "\n\n【格式错误】上次输出无法解析为 JSON。"
                       "请只输出一个 JSON 对象，不要任何其他文字或代码围栏。")
    return {}
```

#### (4) verifier 判据放宽 + claim 重构（修复 D3）

```python
# 判据：归一化 + 分级，partial 也可推进
_OK = {"supported", "partial", "partially_supported", "supported_with_caveats"}
def _norm(s): return str(s or "").strip().lower().replace("-", "_")

supported = [v for v in verdicts if _norm(v.get("status")) == "supported"]
partial   = [v for v in verdicts if _norm(v.get("status")) in _OK
             and _norm(v.get("status")) != "supported"]
decisive = ((bool(supported) or len(partial) >= 2)      # 两条 partial 亦可收敛
            and has_error_evidence and skill_id is not None
            and self.skills.label_of(skill_id) is not None)
```

```python
# claim 重构：验证根因假设，而非日志行自身
hypothesis = self.skills.by_id.get(skill_id, {}).get("root_cause_label")
claims = [{
    "claim_id": "H1",
    "claim": f"本次 OTA 失败的根因是：{hypothesis}"
             f"（技能《{self.skills.by_id[skill_id]['title']}》的假设）",
    "citations": [r["row_hash"] for r in ev if r.get("row_hash")],   # 多条证据支撑一个假设
    "evidence_preview": [str(r.get("raw_line"))[:160] for r in ev[:6]],
}]
```

#### (5) 剔除策略回归原始语义（修复 D4）

```python
def excluded_skills(self) -> list[str]:
    """仅剔除"已用且未产出新证据"的技能。

    此前 used ∪ unproductive 的策略在 mock 下是优化（首轮即收敛），
    但在真实 LLM 下会把"第一次验证未通过的正确假设"永久锁死——
    而真实诊断恰恰需要对同一假设多轮深挖。
    """
    return sorted(set(self.unproductive_skills))
```

配套：保留"同一技能同参数不得重复执行"的探针级去重（避免真正的无效重跑），用 `(skill_id, args_hash)` 做键。

#### (6) `max_tokens` 上调（修复 D6）

```yaml
planner:   {temperature: 0.1, max_tokens: 2048, json_mode: true}
verifier:  {temperature: 0.0, max_tokens: 2048, json_mode: true}
reporter:  {temperature: 0.2, max_tokens: 4096, json_mode: false}
distiller: {temperature: 0.3, max_tokens: 2048, json_mode: true}
```

并在 `LLMGateway.chat` 中检测 `finish_reason == "length"` → 发 ALERT + 计入指标（当前完全没有截断感知）。

### 4.3 技能召回与内容管理

#### (1) 候选集呈现优化

当前 `compact()` 把**完整 probes（含 args）**塞进候选集。12 个技能 × 每个 2~3 条探针，占用大量 token，且诱导模型"照抄探针"而非理解假设。

建议候选集只给**决策所需信息**，探针在选定后由程序注入：

```python
def compact(sk: dict) -> dict:
    return {"id": sk["id"], "title": sk["title"],
            "trigger": sk["trigger"],            # 何时适用（可判定的条件）
            "summary": sk["summary"],            # 一句话机理
            "discriminators": sk.get("differential", []),   # 与谁易混淆、如何区分
            "probe_count": len(sk.get("probes", []))}       # 只给数量，不给全文
```

**收益**：候选集 token 降低 ~60%，且模型被迫基于"假设是否成立"而非"探针长得像不像"来选择。

#### (2) 技能 `trigger` 改写为可判定条件

当前 trigger 多为描述性文字（"FLASH 阶段出现 UDS 否定响应"）。对真实 LLM 应写成**可对照当前 signals 直接判定**的形式：

```yaml
trigger: |
  同时满足：(1) fail_phase ∈ {TRANSFER, FLASH}；
           (2) 错误模板或 abort_reason 中出现 nrc=0x7x 或 UDS_NRC_*；
           (3) 涉事组件包含 uds_stack 或 flash_agent。
  不适用于：仅有静默无 NRC 帧（→ SK-ECU-SILENT）；电压异常在先（→ SK-POWER）。
```

`不适用于` 这一段直接对应 §4.1(6) 的鉴别诊断，是抑制近邻误判最直接的手段。

#### (3) 维度预过滤（程序化，零 token 成本）

用已有的 `signals.fail_phase` / `ecu_id` / 涉事组件，在语义召回**之前**按 `phase_scope`/`ecu_scope`/`module_scope` 硬过滤。既降 token 又提准确率，且不引入语义误差。

#### (4) 召回结果附带匹配理由

```python
{"id": "SK-UDS-NRC", "title": "...", "match_reason": "abort_reason=UDS_NRC_0x72 命中；fail_phase=FLASH 在适用范围内"}
```

让模型看到"为什么这个技能被召回"，比让它自己从关键词猜测更可靠。

### 4.4 收敛控制

| 参数 | 当前 | 建议 | 理由 |
|---|---|---|---|
| 首轮 stop | 允许 | **禁止**（程序守卫） | D1 |
| decisive 判据 | 仅 `supported` | `supported` 或 ≥2 `partial` | D3 |
| 技能剔除 | used ∪ unproductive | 仅 unproductive | D4 |
| 探针去重 | 无 | `(skill, args_hash)` 级 | 配合 D4 |
| 连续无新证据 | 2 轮 → human_gate | 3 轮（真实模型需要更多探索空间） | 经验值 |
| planner max_tokens | 1024 | 2048 | D6 |
| verifier max_tokens | 768 | 2048 + 单批 ≤5 claims | D6 |

### 4.5 评测层（防止再次被 mock 掩盖）

#### (1) mock/real 双轨评测

```bash
vela eval run --provider mock       --out workspace/eval/mock
vela eval run --provider volcengine --out workspace/eval/real
vela eval compare workspace/eval/mock workspace/eval/real     # 新增子命令
```

**任何 mock 与 real 差距 > 15% 的用例，都应视为"编排层缺陷"而非"模型能力不足"**，并强制归因。这是本次问题给出的最重要工程纪律。

#### (2) 新增过程指标（当前完全缺失）

```python
"premature_stop_rate":       (0.05, "<="),   # round<=1 即 stop 的会话占比
"stop_rejected_count":       None,           # 程序守卫驳回 stop 的次数（观测用）
"llm_parse_failure_rate":    (0.02, "<="),   # JSON 解析失败率
"llm_truncation_rate":       (0.02, "<="),   # finish_reason=length 占比
"verdict_supported_ratio":   (0.60, ">="),   # verifier 返回 supported 的占比
"skill_switch_per_session":  (2.5,  "<="),   # 平均技能切换次数（游走程度）
"first_round_hit_rate":      (0.70, ">="),   # 首轮即选中正确技能的比例
```

**这七个指标本应在第一次接真实模型时就存在**——它们能把"准确率低"直接分解到具体环节，而不是留给人猜。

---

## 5. 优先级与预期收益

| 序 | 措施 | 类型 | 预期提升 | 成本 | 风险 |
|---|---|---|---|---|---|
| 1 | 提示词第 5 条重写 + 首轮禁止 stop 守卫 | Prompt+代码 | **+25~35pp** | 极低 | 低 |
| 2 | verifier 判据放宽 + claim 重构 | 代码+Prompt | **+10~15pp** | 低 | 中（需防误判放宽） |
| 3 | 剔除策略回归 unproductive-only | 代码 | **+8~12pp** | 极低 | 低 |
| 4 | planner payload 补全反馈闭环 | 代码 | **+8~15pp** | 中 | 低 |
| 5 | max_tokens 上调 + 截断感知 | 配置+代码 | +3~8pp | 极低 | 低 |
| 6 | JSON 解析重试 | 代码 | +2~5pp | 低 | 低 |
| 7 | 候选集瘦身 + trigger 可判定化 | 配置+代码 | +5~10pp | 中 | 低 |
| 8 | 维度预过滤 | 代码 | +3~6pp | 低 | 低 |
| 9 | few-shot 示例 | Prompt | +3~8pp | 低 | 低 |

**措施 1~3 合计预期即可越过 80% 及格线**，且总成本不足一天工作量。措施 4~9 用于冲击更高目标与稳定性。

> 收益估算基于失效模式的机理推断与占比假设，非实测外推。建议**每完成一项即单独跑一次真实评测**，用实测数据校正后续判断——切勿一次性全改，否则无法归因哪项有效。

---

## 6. 分阶段实施与验收

### 阶段 A：止血（0.5~1 天）

- [ ] 提示词第 5 条重写（D1）
- [ ] 首轮 stop 程序守卫 + `plan.stop_rejected` 指标（D1）
- [ ] verifier 判据归一化 + 允许 partial（D3）
- [ ] 剔除策略回归 unproductive-only（D4）
- [ ] max_tokens 上调（D6）

**验收**：`premature_stop_rate ≤ 0.05`，真实 LLM Top-1 **≥ 75%**

### 阶段 B：闭环（2~3 天）

- [ ] planner payload 补全（证据/压缩痕迹/护栏/verdicts）（D2）
- [ ] verifier claim 重构为根因假设（D3）
- [ ] JSON 解析重试 + 截断感知（D5/D6）
- [ ] 七项过程指标接入评测报告

**验收**：真实 LLM Top-1 **≥ 85%**，`verdict_supported_ratio ≥ 0.6`，`skill_switch_per_session ≤ 2.5`

### 阶段 C：精调（3~5 天）

- [ ] 候选集瘦身 + `trigger` 可判定化改写（12 个技能）
- [ ] 维度预过滤
- [ ] few-shot 示例
- [ ] mock/real 双轨评测 + `vela eval compare`

**验收**：真实 LLM Top-1 **≥ 90%**，且 mock/real 差距 ≤ 10pp

---

## 7. 方法论教训

**mock 不能既是实现又是规范。**

本次问题的根源不在任何单一 bug，而在测试架构：177 个测试全部基于 mock，而 mock 是按设计意图而非提示词字面实现的。这形成了一个**自我确认的闭环**——mock 实现了我们*以为*提示词在说的事，测试验证了 mock 做了它自己做的事，于是所有"提示词字面与设计意图不一致"的缺陷都对测试不可见。

三条可迁移的纪律：

1. **mock 必须遵循与真实模型相同的输入契约**。如果提示词说"证据不足时 stop"，mock 就应该实现这条规则——它会立刻在首轮暴露 D1。当前 mock 直接忽略提示词正文，等于放弃了对提示词的测试覆盖。

2. **任何"模型自主决策点"都必须有程序化守卫**。提示词是引导不是保证；`stop`、工具选择、输出格式这三处都应有代码兜底。防御纵深不能只有一层。

3. **接入真实模型的第一天就要有过程指标**。`premature_stop_rate`、`parse_failure_rate`、`verdict_supported_ratio` 这些指标的价值不在于好看，而在于**把"准确率低"分解成可定位的环节**。没有它们，44.4% 只是一个让人焦虑的数字；有了它们，它是一张指向 D1 的地图。

**最后一点值得强调**：44.4% 的实测结果比 100% 的 mock 成绩有价值得多。它暴露的每一个缺陷都是真实存在的、迟早要在生产环境付出代价的——现在发现，成本是几天的修改；上线后发现，成本是工程师被错误结论误导的排查工时与对系统的信任崩塌。

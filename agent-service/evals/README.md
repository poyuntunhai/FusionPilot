# FusionPilot Agent 评测集

按用例驱动 Agent 跑一遍，逐条断言行为，出一份通过率报告。

```bash
cd agent-service
python -m evals.run_evals                    # 全部用例
python -m evals.run_evals --group gate       # 只跑一组
python -m evals.run_evals --only concept-*   # 按 id 通配
python -m evals.run_evals --verbose          # 打印每一条断言，不只失败的
python -m evals.run_evals --json report.json # 机器可读报告
```

跑一次不到一秒，不需要 provider key、不需要 MySQL、不需要 Java 进程。

## 它测什么，不测什么

**测**：给定一个模型决策，Agent 的行为是否正确 —— 路由分发、确认门是否拦住花钱的调用、工具执行
顺序、回答是否有出处和引用、自检层是否会说话、配置改错时是否会整体拒绝、转录是否可重放。

**不测**：模型自己的判断力。每个用例自带**脚本化的模型**（`model` 字段），所以结果是确定的；这
意味着用例断言的是"模型决定 X 之后 Agent 做了 Y"，而不是"模型是否做出了正确的 X"。要衡量模型的
判断力，需要真实 provider —— 那是另一件事，见文末。

把这条边界写清楚不是谦虚：一份没说清测什么的报告，比没有报告更危险。

## 用例格式

`cases.jsonl`，一行一个 JSON（空行和 `//` 开头的行为注释）。

```json
{
  "id": "gate-approve-executes-and-quotes-only-returned-values",
  "group": "gate",
  "description": "批准后只跑一次，收尾措辞不超出返回的指标",
  "message": "跑一次看看",
  "setup": { "auto_approve": false, "working_config": { "targetCount": 3 }, "memory": "" },
  "java": { "metrics": {"averagePositionError": 3.12}, "validate_error": null, "run_error": null },
  "model": {
    "route": "experiment",
    "clarify_question": null,
    "answer": "概念回答的文本（concept 路由用）",
    "steps": [{"text": "…", "tool_calls": [{"tool": "run_simulation", "arguments": {"reason": "x"}}]}],
    "plan": {"goal": "…", "rationale": "…", "steps": []},
    "reflection": {"supported": false, "problem": "…", "correction": "…"},
    "memory_note": ""
  },
  "decision": "approve",
  "stream": false,
  "expect": {"requires_confirmation": true, "runs_executed": 1}
}
```

| 字段 | 含义 |
|---|---|
| `message` | 用户这句话 |
| `setup.auto_approve` | 关掉确认门（默认 `false`，即走门） |
| `setup.working_config` | 覆盖默认配置 |
| `java.metrics` | 桩 Java 返回的指标（用来触发确定性自检等） |
| `java.validate_error` | 让配置校验失败，测"整份不生效" |
| `java.run_error` | 让运行失败 |
| `model.route` | 脚本化的意图决策（`concept_qa` / `experiment` / `explore` / `clarify`） |
| `model.answer` | concept 路由下模型说的话 |
| `model.steps` | 工具循环中模型逐轮的动作；给完就返回纯文本收尾 |
| `model.plan` | explore 路由下规划器返回的序列 |
| `model.reflection` | 自检模块返回的判定（默认 `supported: true`） |
| `decision` | `approve` / `decline`：是否回答确认卡 |
| `stream` | 走 SSE 端点（UI 用的那条）而不是 JSON 端点 |

模型应答是按**系统提示词特征**分发的，不按调用顺序。按顺序消费单个队列会让用例的含义取决于代码
内部碰巧调用了几次模型 —— 加一个自检调用就会悄悄打乱所有用例。

## 断言词汇表

`expect` 里出现即生效。写错键名会**报错**而不是静默跳过（一个拼错、又什么都不检查的断言，是这类
套件最糟的失败模式）。

| 键 | 断言 |
|---|---|
| `route` | 意图路由选了什么 |
| `no_tools` | 连工具调用都**没被提出**（比"没执行"更强） |
| `tools_used` | 实际执行的工具，精确有序 |
| `tools_exclude` | 这些工具不能出现 |
| `tool_failed` | 这些工具的结果是失败 |
| `tool_result_contains` | 工具结果里含这些文本 |
| `requires_confirmation` | 请求过确认，且**确认之前没执行过任何工具** |
| `runs_executed` | 桩 Java 被调了几次 |
| `plan_steps` | 计划序列的步数 |
| `grounded` | 概念回答是否检索到了材料（事件缺失 = 失败，见下） |
| `citations_min` / `no_citations` | 引用条数量 |
| `citation_chunk_ids` | 引用了哪些小节 |
| `answer_contains` / `answer_excludes` | 收尾那条 assistant 消息的内容 |
| `transcript_contains` | 整段转录里出现过（用来断言"说过的错话仍然可见"） |
| `self_check_issues_contain` / `self_check_clean` | 自检事件的内容 |
| `self_correction` | 是否发生了自我纠正（事件 + `reflect:` 消息） |
| `status` | 最终会话状态 |
| `no_invented_metrics` | 见下 |
| `working_config` | 最终工作配置的字段值 |
| `handoff_to` | 主管把这回合交给了哪位专员（`responder` / `executor` / `planner` / `clarifier`） |
| `routing_reason_contains` | 主管给出的分派理由里含这些文本 |
| `model_roles` | 每个角色的模型调用**次数**（`{"analysis": 1, "reflect": 1}`） |
| `analysis` | 分析专员产物的子断言：见下 |

另有两条**每条用例都跑**的不变式，不需要声明：

- `case-completed`：用例有没有跑起来；没跑起来会带上原因，而不是抛异常打断整份报告。
- `transcript-replayable`：每个工具调用都有结果 —— **但当会话停在等确认时不算**，那个批次本来就
  整批挂着，等批准后一次性回答。把它判成"孤儿"会让这条不变式在最需要放行的那条流程上出错。

## 多智能体协作怎么断言

`multi-agent` 那一组测的是**协作本身**，不是回答文本 —— 这些性质在答案里看不出来：

- `handoff_to` / `routing_reason_contains`：主管把回合交给了谁、为什么。一个没人能看懂的分派
  决定，是多智能体系统里最先腐烂的部分。
- `model_roles`：每个角色的模型调用**次数**。它钉住的是"跑一次仿真 → 分析专员恰好跑一次、
  批评者恰好跑一次"，以及"只改一个设置 → 分析专员跑零次"（不为没有结果的回合付钱）。
  没跑过的角色算 0，不会因为没出现而被跳过。
- `analysis`：分析专员的产物。
  - `present`：产物与 `analysis_ready` 事件是否都存在。
  - `summary_contains` / `limitations_min` / `produced_by_prefix`：内容与生产者。
  - `evidence_metrics_only_returned`：**端到端证明分析专员夹带不了指标** —— 用例故意让它返回一条
    运行从未给出的指标（`hallucinatedMetric`），甚至给出一个指标名对、数值被改写的行；两者都必须
    被丢弃。这条走的是 `analyze_with_model` 里既有的过滤逻辑，现在被真正用上了。

另外一个**结构性**性质由单元测试守，不在这里：概念应答专员与分析专员的"没有工具"不是靠提示词请求
的，而是因为它们走 `complete`，而 `complete` 没有 tools 参数可传。`tests/test_roles.py` 直接断言
`complete` 的签名里没有 tools —— 哪天有人给它加了工具通道，这两个角色会同时悄悄获得行动能力。

## 防幻觉检查

`no_invented_metrics` 检查两件事：

1. **回答里的小数 / 百分数必须来自这次运行。** 允许的比例是"真实值的约 0.5% 以内"，所以"3.12"
   可以写成"3.1"，"0.98"可以写成"98%"，但真值是 3.12 时写 2.5 会被抓住。
2. **不能提到这次运行没返回的指标名。**

**已知局限**：裸整数不查（"目标 1"和"3 个目标"都是正常行文），所以编造一个整数指标值不会被抓住。

## 为什么这里没有 LangGraph 的 `interrupt` + checkpoint

早先的计划里写着"评测集会需要 checkpoint 精确重放"。真正写的时候发现不需要：会话本身就是每轮落库
的持久状态，批确认机制已经能把"半途停住"的会话存下来，而本套件驱动的是真实 HTTP 接口，重放一份
会话就是再发一次请求。为一个不需要的能力引入第二套状态机，只会让出错的地方变多。
（真正需要 checkpoint 的场景是"在一个节点中途崩溃后续跑同一节点"，本套件没有这个需求。）

## 这套件抓到的第一个真问题

`reflect` 自检节点原先只在图里。但**用户批准之后的那个回合不走图** —— `resolve_decision` 执行完
批准的批次后直接在工具循环里继续，`run_experiment` 节点不会再进。于是"读一次用户刚批准的运行结果"
这个最该被审的回合，恰恰是唯一没有被审的回合。`self-check-*` 三条用例直接把这件事暴露了出来。

修法是把 `reflect_turn` 提到模块级，由决策端点显式调用；`tests/test_reflection.py` 里有一条盯着它。
读图看不出来，因为图本身没错 —— 缺的是那条路径根本不经过图。

## 它自己曾经不老实的地方

第一版跑完 14 条用例要 23 秒。原因是 `complete` 在每个模块里各有一份引用（`reflection`、`memory`、
`result_analysis`、`model_planner`），只打桩了 `agent_graph` 的那一份，于是**反思、记忆蒸馏、结果
分析三个模块仍在真的往 provider 发请求** —— 之所以没暴露，是因为三处都把网关异常吞掉了。

现在打桩清单覆盖了全部持有者，并加了一道硬闸：`httpx.AsyncClient.send` 被替换成抛异常（入站请求走
`httpx.Client`，所以 `AsyncClient` 恰好就是出站通道）。用例 0.3 秒跑完，而且"离线确定性"这个说法
是被强制执行的，不是自我宣称的。

## 衡量模型判断力（`--api-key`）

脚本模式测的是"给定模型决策之后 Agent 的行为"，它刻意不理解模型。要衡量模型本身，把同一批用例指向
真实 provider：

```bash
python -m evals.run_evals --group routing \
  --provider zhipu --model glm-4-flash --api-key <你的 token>

# 自定义端点（自建网关、代理、或本机 mock）也行：
python -m evals.run_evals --api-base http://127.0.0.1:8111/v1 --model mock-gpt --api-key k
```

做了两件事，缺一不可：

1. **脚本模型被完全摘掉**，连 `classify_intent` 的桩也不装。provider 与 model 走请求体、token 走
   `X-Model-Api-Key` 请求头——和网页里用户自己贴 key 是同一条路径，所以凭据接错会在这里就暴露，
   而不是等到线上。
2. **只统计与模型措辞无关的断言**（`grade.LIVE_SIGNIFICANT`）：`case-completed`、
   `transcript-replayable`、`status`、`requires-confirmation`、`no-invented-metrics`、`route`、
   `handoff-to`。其余断言（`answer-contains`、`plan-steps`、`analysis-summary-contains`…）是照着
   脚本原文写的，拿真实模型跑必然对不上——那验证的是脚本、不是产品。它们会显示为
   `[skip] not counted`。

所以真实模式的分数回答的是：**这个模型选路选对了吗、有没有守住产品的硬契约**。它不回答"Agent 写得好
不好"——那是脚本模式的事。两者是两个不同的分数，因此报告头部会写明当前处于哪种模式，而不是只丢一句
"17 passed"。

Java 核心在两种模式下都打桩：比较两个 provider 不该需要数据库，而"同一个假运行"也是两次结果可比的
前提。

**验证到哪一步了。** 只在本机 mock provider 上验证过：走真实网关 → mock，routing 4 条用例 2 通过
2 失败，失败的正是"mock 自己做了另一个决定"（它在该用例上要了确认，而用例期望不用），说明打分的确实
是模型的决策。**没有**对着真实厂商验证过——我没有你的 key。另外把 `--api-base` 指成 `not-a-url`
会立刻失败，这条已固化成测试 `test_live_mode_puts_the_scripted_model_aside`，用来防止哪天有人"顺手"
把脚本模型装回去。真实模式走真网络、带重试，比脚本模式慢两个数量级，不适合放进 CI。

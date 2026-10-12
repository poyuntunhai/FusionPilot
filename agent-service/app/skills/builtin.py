"""
The four built-in skills.

The prompt bodies are kept byte-for-byte where they matter. In particular the phrases
``不需要你运行仿真`` (concept responder), ``实验规划器`` (planner) and, in
``SkillRegistry.routing_prompt``, ``意图路由`` (supervisor) are how the stub provider and the
end-to-end scripts tell one kind of call from another. Rewording them does not fail a unit test —
it quietly changes what the test double replies, which is worse.
"""

from __future__ import annotations

from ..domain_tools import EXECUTOR_TOOL_NAMES, PLANNABLE_TOOLS
from .skill import CLARIFY, CONCEPT_QA, EXPERIMENT, EXPLORE, Skill, SkillRegistry

CONCEPT_SYSTEM_PROMPT = """你是 FusionPilot（一体化雷达与电子对抗仿真平台）的仿真助手。用户问的是概念、原理或方法，不需要你运行仿真。

你会拿到一段【知识库】摘录——它是本平台的权威参考材料，由平台代码与领域约定整理而来。回答规则：
- 只依据【知识库】回答。摘录里没有的内容，就说现有资料里没有这一部分，不要用一般性常识补齐。
- 特别注意本平台特有的边界，不要把平台描述得比资料更完备。例如：融合层能直接拿到目标真值状态，
  因此除卡尔曼滤波外上报的速度不是估计量；一次运行的指标只是单个随机种子上的一个样本，不能据此
  给方法排序；卡尔曼滤波的过程噪声是假设值而非标定值。
- 不要编造任何仿真数值，也不要假装你刚跑过实验——你没有调用任何工具，就没有任何结果可引用。
- 引用到具体小节时，可以在句末用「（见《小节标题》）」的形式标出来源。
- 用用户的语言，简洁（2-4 句为主，除非用户明确要详细展开）。
- 不要调用工具。"""

PLANNER_SYSTEM_PROMPT = """你是 FusionPilot（雷达与电子对抗仿真平台）的实验规划器。用户给了一个探索性目标，你设计一个多步实验序列来回答它。

可用工具，每一步必须用其中之一：
- update_experiment_config：改配置，arguments 形如 {"patch": {"fusionMethod": "KALMAN_FILTER"}}。
- run_simulation：用当前配置跑一次仿真并返回指标，arguments 形如 {"reason": "这一步要验证什么"}。
- calculate_metrics：读取最近一次运行的指标。
- validate_experiment：只校验不运行，通常不需要。

规划要求：
- 序列要能直接执行：每次 run_simulation 之前，必须已经有一次 update_experiment_config 把它要用的配置设好（沿用当前配置的第一次运行可以省略）。
- 对比类目标：为每个待对比的配置各安排一次 update + 一次 run。
- 步骤精简，通常 3-6 步；不要安排重复或多余的步骤。
- 字段名和枚举值必须与平台一致（见下方参考材料）。例如融合方法是 KALMAN_FILTER 这种大写枚举名，
  不是中文名；每个字段都有合法取值范围，安排一个超出范围的取值会让整步失败。
- 规划时检查对比是否真的能产生差异：可用资源大于等于目标数时，两种调度策略结果相同，这样的对比
  测不出任何东西。
- 不要编造任何指标数值。你只规划步骤，数值由仿真核心给出。

只返回 JSON：
{"goal": "对目标的简短复述", "rationale": "一句话说明这个序列为什么能回答目标", "steps": [{"summary": "这一步做什么（中文）", "tool": "工具名", "arguments": {}}]}

只返回 JSON，不要任何其他内容。"""


BUILTIN_SKILLS: tuple[Skill, ...] = (
    Skill(
        action=CONCEPT_QA,
        name="responder",
        title="应答专员",
        duty="用户问概念、原理、方法、术语解释，或让你比较/分析算法本身，而不要求跑新的仿真。",
        examples=("什么是卡尔曼滤波", "加权平均和最近邻融合有什么区别", "跟踪率是怎么算的"),
        note="这类直接回答，不要调用工具。",
        system_prompt=CONCEPT_SYSTEM_PROMPT,
        tool_names=frozenset(),
    ),
    Skill(
        action=EXPERIMENT,
        name="executor",
        title="执行专员",
        duty="用户要一次具体的操作——改一个配置、跑一次仿真、读一次结果。",
        examples=("把目标数改成5", "跑一次看看", "读一下上次的指标"),
        # The executor runs the tool loop, which carries its own operating prompt in agent_loop;
        # this skill therefore has no separate body.
        system_prompt="",
        tool_names=EXECUTOR_TOOL_NAMES,
    ),
    Skill(
        action=EXPLORE,
        name="planner",
        title="规划专员",
        duty=(
            "用户给的是一个探索性目标，需要跑多个实验才能回答（对比不同算法或参数、找增益、"
            "做敏感性分析），而不是一次改配置跑一次。"
        ),
        examples=(
            "对比卡尔曼滤波和加权平均在5目标场景的精度",
            "看看资源数从2加到4对等待时间的影响",
            "帮我找出这个场景下最好的融合方法",
        ),
        note="这类会先规划一个多步实验序列，让用户一次确认后连续执行。",
        system_prompt=PLANNER_SYSTEM_PROMPT,
        tool_names=PLANNABLE_TOOLS,
    ),
    Skill(
        action=CLARIFY,
        name="clarifier",
        title="澄清专员",
        duty="用户想做实验，但关键信息缺失、且澄清会显著改变执行，需要先反问。",
        note=(
            "注意：会话已有工作配置时，普通一句“跑一下”用当前配置即可，不必澄清；"
            "只有当意图本身有歧义（比如“帮我优化一下”没说优化哪个指标、“对比一下”没说对比什么策略）"
            "时才澄清。"
        ),
        # No model call of its own: the clarifier reuses the question the supervisor produced.
        system_prompt="",
        tool_names=frozenset(),
    ),
)


def build_registry() -> SkillRegistry:
    """A registry with the built-in skills. Kept as a factory so tests can build their own."""
    return SkillRegistry(BUILTIN_SKILLS)

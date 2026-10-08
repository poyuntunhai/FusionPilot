---
doc: experiment-config
title: 实验配置字段与取值范围
tags: 配置, config, 参数, 字段, 取值范围, 校验, ExperimentConfig
---

## 配置字段总览 experiment config fields

一个实验配置由这些字段组成，字段名区分大小写，改配置时要用 camelCase 原样写：
`scenarioName`、`targetCount`、`simulationSteps`、`timeStepSeconds`、`availableResources`、
`fusionMethod`、`schedulingPolicy`、`randomSeed`、`observationSources`。

Java 仿真核心在每次改动后**全量校验**整个配置：只要有一个字段非法，整次修改就被拒绝、不会写入
会话，因此会话里永远只持有能被运行的配置。改完再跑是安全的，不需要自己先做一遍合法性检查。

## 场景名称与目标数 scenarioName targetCount

`scenarioName`：字符串，1–80 个字符且不能为空。它只作为标签，出现在历史记录和导出文件里，
不影响任何计算结果。

`targetCount`：整数，1–50。决定场景里有几个目标。目标的位置和速度都由编号推导，所以目标数同时
决定了目标之间的间隔尺度——把目标数从 3 改到 12，整个场景在空间上被"撑开"，位置误差的绝对数值
不能直接和改之前对比。

## 步数与时步 simulationSteps timeStepSeconds

`simulationSteps`：整数，1–10000，仿真的时间步数。它和 `randomSeed` 一起决定整条噪声与丢观测
序列，因此改步数等于换了一个噪声实现。

`timeStepSeconds`：浮点，最小 0.01，每一步代表多少秒。它决定每步的运动位移，也决定预测外推多远；
同时它是等待时间从"步"换算到"秒"的唯一系数。步数和时步共同决定仿真的总时长。

## 可用资源 availableResources

整数，1–50，每一步最多可以服务多少个目标。

它是调度环节的关键输入。当它大于等于 `targetCount` 时，每个目标每步都能被服务，两种调度策略结果
完全一致、资源利用率恒为 1，此时调度对比没有意义。要让调度策略产生差异，必须把它设得小于
`targetCount`。它也是资源利用率的分母来源。

## 融合方法与调度策略 fusionMethod schedulingPolicy

`fusionMethod`：枚举，五个可选值 `WEIGHTED_AVERAGE`、`SIMPLE_AVERAGE`、`NEAREST_NEIGHBOR`、
`DISTANCE_GATED`、`KALMAN_FILTER`。写错或写了不在枚举里的值会被核心直接拒绝。

`schedulingPolicy`：枚举，只有两个可选值 `ROUND_ROBIN` 和 `PRIORITY`。用的是大写加下划线的
枚举名，不是中文名。

## 随机种子 randomSeed

`randomSeed`：长整数，取值不限。它固定整段运行里全部随机数的取用顺序，包括每个观测源每一步的
丢观测判定和噪声抽样。

同一个 `randomSeed` 配同一份配置和同一个 `simulationSteps`，两次运行会得到逐位相同的指标。
这**不是**缓存或结果复用，而是确定性复现：每次运行仍然有自己的运行 id 和配置摘要。反过来说，
只改种子就是换一个噪声实现，这是做多次重复实验、把单样本差异和真实差异区分开的正确手段。

## 观测源 observationSources

观测源列表，1–3 个条目，每个条目有五个字段：`type`（枚举 `RADAR`、`EO_IR`、`PRIOR_KNOWLEDGE`
三选一）、`noiseStdDev`（≥ 0，位置噪声标准差）、`missingRate`（0–1，该源每步丢观测的概率）、
`delaySteps`（0–10，观测延迟的步数）、`confidence`（0.1–1.0，该源置信度，参与加权融合）。

列表最多三个条目，且三种类型就这三种。`PRIOR_KNOWLEDGE` 的置信度会在内部再乘 0.8，使先验源的
权重低于同等标称置信度的测量源。`delaySteps` 是真实时延而不是只记录不生效的字段：观测报告的是
该目标 `delaySteps` 步之前的位置。

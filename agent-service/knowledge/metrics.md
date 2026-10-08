---
doc: metrics
title: 指标定义与读法
tags: 指标, metrics, 评价, 误差, 跟踪, 利用率
---

## 指标总览 五个聚合指标

一次仿真运行结束后返回的聚合指标（`AggregateMetrics`）共五个：`averagePositionError`
（平均位置误差）、`trackingRate`（跟踪率）、`resourceUtilization`（资源利用率）、
`averageWaitingTime`（平均等待时间）、`schedulingSwitches`（调度切换次数），外加
`totalSteps`（总步数）。

它们是由每一步的 `StepMetrics` 在整段运行上再取平均（或计数）得到。`totalSteps` 是运行的实际
步数，等于配置里的 `simulationSteps`。

## 平均位置误差 averagePositionError position error

每一步先算所有目标的位置误差：目标真实位置与融合位置之间的欧氏距离，单位是场景坐标单位；
再把各步的值在整段运行上取平均。

注意场景里的目标间距会随口标数增大（目标 i 的初始位置与速度都与 i 成正比），所以绝对位置误差要放到
场景尺度里读，孤立地看"误差是几"没有意义。它变大可能有两个完全不同的原因：观测有噪声，或者根本
没有观测、滤波只能靠运动模型外推。要和 `trackingRate` 一起读才能区分。

## 跟踪率 trackingRate

每一步的跟踪率 = 该步中融合结果**不是**纯预测（`predictedOnly`）的目标占比，也就是至少有
一条观测被真正融合进来的目标比例；整段运行的跟踪率是各步值的平均，取值落在 [0, 1]。

`trackingRate` 高于 1 是不可能的，出现就说明数据有问题。跟踪率偏低说明大量目标在该步没有可用
观测，滤波在靠运动模型滑行，这时 `averagePositionError` 通常同时偏高。它是判断"观测够不够用"
的第一指标。

## 资源利用率 resourceUtilization

每一步的资源利用率 = 该步被分配资源的目标数 ÷ `max(1, min(availableResources, targetCount))`，
即相对"容量与需求中较小者"的饱和程度，因此被截断在 1 以内；整段运行的利用率是各步值的平均，
取值也在 [0, 1]。

它衡量的是资源用得多满。利用率为 1.0 而 `unservedTargetCount` 大于 0，说明这个场景是超订的：
资源已经跑满，但仍有目标拿不到服务，这时候提升指标要靠增加 `availableResources` 或减少
`targetCount`，而不是改调度策略。

## 平均等待时间 averageWaitingTime waiting time

定义是 `Σᵢ(目标 i 未被服务的步数) / (targetCount · simulationSteps)`，即每个目标平均等待了
多少步。单位是**步，不是秒**；要换算成秒需要再乘以 `timeStepSeconds`。

它是调度公平性的直接度量：轮询下各目标等待时间接近，优先级下分布会更不均匀。目标数或资源数变化
都会同时改变它的分子和分母，所以跨配置比较等待时间时要说明双方的 `targetCount` 与
`simulationSteps`。

## 调度切换次数 schedulingSwitches

整段运行中，相邻两步的"被分配目标集合"发生变化的前后步对数量。集合不同就计一次，相同不计。

它是调度稳定性的度量，不是好坏指标：值大说明分配方案在步与步之间反复变动。它的量级上限是
`simulationSteps - 1`。对比两种策略时它天然不同，不要把它当作"哪种策略更优"的证据。

## 每步指标 step metrics

除聚合指标外，每一步还返回 `allocatedTargetCount`（该步被服务的目标数）、
`unservedTargetCount`（该步没被服务的目标数）和该步的 `averagePositionError`、`trackingRate`、
`resourceUtilization`。

这些逐步数据用于画时间序列、定位指标是在哪一段变坏的。比如整体跟踪率被少数几步拖低，往往意味着
那几步出现了大面积观测缺失。逐步数组体量很大，Agent 在对话里只引用聚合指标，完整序列放在运行
详情里查看。

## 指标怎么组合读 how to read them together

高 `trackingRate` 配高 `averagePositionError`：观测是有的，但噪声大，融合位置仍然偏离真值。
低 `trackingRate`：滤波在靠运动模型滑行，位置误差随之升高。
`resourceUtilization` 到 1.0 且 `unservedTargetCount` 大于 0：场景超订，资源不足。
`averageWaitTime`（平均等待时间）偏高而利用率不满：资源没被用满，问题更可能出在调度或可用资源
配置上。

任何一组指标都只来自一个随机种子，也就是一个噪声实现。

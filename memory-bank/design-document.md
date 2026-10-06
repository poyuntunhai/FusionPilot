# 一体化雷达/抗干扰系统数字模型与 AI 智能决策体

## 1. 文档状态

- 版本：v0.1
- 阶段：MVP 设计
- 目标周期：约一周
- 设计原则：先完成可复现的仿真闭环，再逐步增强模型保真度和 Agent 自主性

## 2. 产品定义

本项目是一个面向科研实验和 Agent 工程学习的本地可视化仿真平台，用于研究多目标复杂环境下的多源信息融合与雷达资源调度。系统以 Java 作为领域后端和仿真运行时，以 FastAPI 承载 Agent 服务，以 Vue 构建可视化界面，从而同时训练传统后端、AI 服务和前端工程能力。

系统使用合成数据模拟多个目标、多个观测源和有限雷达资源，经过观测生成、信息对齐、目标关联、状态融合和资源调度后，输出目标状态、跟踪质量、资源分配过程和评价指标。

AI 智能决策体位于仿真平台之上，负责理解用户的实验意图，生成结构化实验计划，调用仿真和分析工具，并以带有假设和证据说明的方式解释结果。第一阶段的 Agent 不直接替代底层调度算法，也不执行未经用户确认的高影响操作。

## 3. 目标与非目标

### 3.1 MVP 目标

在本地浏览器中完成一个端到端闭环：

1. 用户选择或配置多目标场景。
2. 系统生成二维离散时间的目标运动和三类合成观测。
3. 系统对观测进行简化预处理、时间对齐、关联和融合。
4. 系统在有限雷达资源下执行两种可比较的调度策略。
5. 系统展示目标轨迹、观测点、融合状态、资源分配和关键指标。
6. 用户可以保存或导出实验配置与结果。
7. Agent 可以根据自然语言生成实验计划，调用仿真工具，并解释结果。

### 3.2 非目标

- 不实现真实雷达硬件控制、真实电子设备接口或武器系统接口。
- 不追求完整电磁传播、复杂波形、射频链路或高保真信号级建模。
- 不在第一周实现复杂深度学习训练、强化学习训练或全自主在线决策。
- 不把 Agent 生成的文本结论作为未经验证的科研事实。
- 不在 MVP 阶段建设多用户权限、云部署、高并发和生产级数据服务。
- 不把 Python/FastAPI 作为雷达仿真的核心领域后端；FastAPI 仅负责 Agent 和 AI 相关服务。

## 4. 核心用户与用户旅程

### 4.1 研究实验用户

目标：比较不同信息融合和资源调度配置对多目标跟踪效果的影响。

流程：

1. 打开实验界面，选择默认场景或修改目标数量、初始状态和观测噪声。
2. 选择融合方法和调度策略。
3. 运行实验并查看仿真过程。
4. 对比不同策略的跟踪误差、目标覆盖率、资源利用率和调度响应。
5. 导出图表、参数和结果摘要，用于实验报告或论文材料。

### 4.2 Agent 协作用户

目标：用自然语言提出研究问题，让 Agent 协助设计和分析实验。

流程：

1. 用户提出问题，例如“比较两种调度策略在高噪声多目标场景下的表现”。
2. Agent 读取项目设计文档和可用工具说明，识别缺失参数。
3. Agent 生成结构化实验计划，包括场景、变量、基线、指标和预期输出。
4. 用户确认实验计划。
5. Agent 调用仿真、指标和可视化工具。
6. Agent 基于结构化结果生成结论、异常说明和下一步实验建议。
7. 系统保存任务轨迹、实验配置、工具调用和结果摘要。

## 5. MVP 场景与模型假设

### 5.1 场景边界

- 空间：二维平面。
- 时间：离散时间步。
- 目标：有限数量的运动目标，初始支持匀速或分段匀速运动。
- 观测源：三类合成信息源。
  - 雷达观测：位置或距离/方位的简化观测。
  - 红外/光电观测：带有不同噪声和可见性条件的目标观测。
  - 先验/通信观测：目标身份、区域或粗粒度状态先验。
- 资源：有限数量的雷达任务槽位或观测机会。
- 不确定性：通过噪声、缺失观测、延迟和观测置信度模拟。
- 干扰/抗干扰：MVP 以观测质量下降、观测缺失或噪声增大等抽象因素表达，不实现真实电子对抗链路。

### 5.2 多源信息融合基线

第一版使用可解释、易验证的算法基线：

- 统一时间轴和坐标表达。
- 基于距离门限或最近邻的目标关联。
- 位置和速度状态的加权融合，权重由观测置信度或误差估计决定。
- 对缺失观测使用预测状态，对异常观测进行标记。
- 为后续卡尔曼滤波、概率数据关联或学习型融合保留替换接口。

第一版不要求同时实现多种复杂融合算法；系统应通过明确的接口允许后续替换融合模块。

### 5.3 资源调度基线

第一版比较两种策略：

1. 固定轮询：按照目标或任务顺序循环分配资源。
2. 优先级调度：根据目标威胁度、状态不确定性、最近观测时间和跟踪质量计算优先级，优先服务需要更多资源的目标。

优先级公式不在设计阶段绑定为唯一数学形式，但必须：

- 输入和输出明确。
- 每个优先级因素可解释。
- 支持记录每个时间步的调度原因。
- 能够与固定轮询产生可比较的实验结果。

## 6. 功能设计

### 6.1 场景配置

用户可以配置或选择：

- 场景名称和随机种子。
- 仿真时长和时间步长。
- 目标数量、初始位置、速度和运动模式。
- 观测源启用状态。
- 各观测源的噪声、缺失率、延迟和置信度。
- 可用资源数量。
- 融合算法和调度策略。

系统需要在运行前校验参数范围，并明确展示使用的默认值和随机种子。

### 6.2 仿真运行

仿真引擎按时间步执行：

1. 更新目标真实状态。
2. 更新资源和任务状态。
3. 根据调度策略分配当前观测机会。
4. 生成各信息源观测。
5. 执行观测预处理、对齐和关联。
6. 更新融合状态和不确定性。
7. 记录事件、状态、调度结果和指标。

仿真结果必须包含真实状态和观测/融合状态的区分，避免把估计值误当作真实值。

### 6.3 评价指标

第一版至少实现：

- 位置估计误差。
- 速度估计误差或状态误差。
- 有效跟踪率/目标覆盖率。
- 观测资源利用率。
- 目标平均等待时间。
- 调度切换次数或调度稳定性。
- 不同策略之间的指标差异。

每个指标必须说明计算对象、时间范围和是否使用真实状态作为参考。

### 6.4 可视化界面

界面优先服务于实验观察和结果比较，包括：

- 场景配置区域。
- 仿真控制区域：运行、暂停、重置和重新生成。
- 二维场景视图：目标真实轨迹、观测点、融合轨迹和当前资源指向。
- 时间序列或指标图表。
- 调度时间线或资源分配表。
- 实验结果摘要和策略对比。
- Agent 对话区或实验计划区。
- 导出实验配置、结果数据和图表的入口。

界面应明确区分“真实状态”“观测状态”“融合估计”和“Agent 解释”。

### 6.5 Agent 决策体

第一阶段 Agent 采用工具增强的规划与分析模式，具备以下能力：

- 需求澄清：发现目标数量、指标、策略或实验条件缺失时提问。
- 实验规划：输出结构化场景、变量、基线、指标和验证方式。
- 工具调用：调用场景校验、仿真运行、指标计算、对比分析和结果导出工具。
- 结果分析：从结构化结果中生成摘要、趋势、异常和限制说明。
- 实验建议：提出下一组具有明确目的的对比实验。
- 过程记录：保存输入、计划、确认、工具调用、结果和最终解释。

Agent 必须遵守：

- 工具调用参数使用结构化数据，不依赖自由文本解析作为唯一入口。
- 运行高成本或会覆盖结果的操作前请求用户确认。
- 解释必须引用结构化实验结果和模型假设。
- 不确定时明确说明“不足以判断”，不得编造实验数据。
- 模型供应商通过 FastAPI 侧适配接口隔离，支持无 API 的规则演示模式。

## 7. 数据与状态模型

### 7.1 实验配置

实验配置是可序列化对象，至少包含：

- `experiment_id`
- `scenario`
- `targets`
- `observation_sources`
- `fusion_method`
- `scheduling_policy`
- `resource_limits`
- `simulation_settings`
- `random_seed`
- `created_at`

### 7.2 仿真状态

每个时间步记录：

- 当前时间和时间步编号。
- 目标真实状态。
- 可用资源和已分配任务。
- 各观测源原始观测及质量标记。
- 关联结果。
- 融合状态和不确定性。
- 当前指标累计值。
- 调度决策及其解释因素。

### 7.3 实验结果

实验结果至少包含：

- 配置快照。
- 时间序列状态。
- 聚合指标。
- 策略对比摘要。
- 运行日志和异常。
- 可视化所需的数据。
- Agent 任务记录（如果由 Agent 发起）。

MVP 优先使用本地文件或轻量嵌入式存储，数据格式应方便导出和复现实验。

## 8. 模块边界

系统逻辑划分为以下模块：

1. 场景与配置模块：负责参数模型、默认场景和校验。
2. 目标与环境模块：负责真实目标状态和环境条件。
3. 观测源模块：负责生成不同来源的合成观测。
4. 融合模块：负责时间对齐、关联、状态估计和不确定性。
5. 调度模块：负责资源分配和调度解释。
6. 仿真编排模块：负责按时间步协调其他模块并记录结果。
7. 评估模块：负责指标计算和策略对比。
8. Java 后端 API 模块：负责配置校验、仿真任务、结果查询、导出和领域工具接口。
9. FastAPI Agent 服务：负责计划生成、工具调用循环、模型适配、结果分析和 Agent 记忆接口。
10. Vue 可视化前端模块：负责配置、仿真控制、轨迹和指标展示。
11. 服务通信模块：负责 Java 与 FastAPI 之间的结构化请求、响应和错误协议。

Java 后端是 MVP 的领域主服务和主要仿真运行时，FastAPI 是 Agent 独立服务。底层仿真、融合和调度模块不得依赖具体大模型，以确保没有 API 或 FastAPI 不可用时仍可运行科研基线。

推荐的调用边界：

- Vue 前端通过 HTTP/JSON 调用 Java 领域 API 和 FastAPI Agent API。
- Java 后端提供场景校验、仿真运行、结果查询、指标对比和导出接口。
- FastAPI Agent 服务通过 Java 内部工具 API 调用仿真能力，不直接操作数据库。
- Java 和 FastAPI 之间只传递结构化 DTO/JSON，不共享进程内对象。
- 仿真运行结果以结构化 JSON 保存，便于前端展示、Agent 分析和实验复现。
- 若需要实时展示进度，优先使用服务端推送；MVP 可先采用“运行后回放”的方式降低复杂度。

## 9. 异常与边界情况

- 配置参数超出范围：运行前阻止并提示修正。
- 目标数量为零：允许展示空场景，但不能产生虚假指标。
- 观测源全部失效：保留预测状态，明确标记跟踪质量下降。
- 目标靠近或交叉：关联结果标记为低置信度或存在歧义。
- 观测延迟：按时间戳处理，不直接覆盖较新的状态。
- 随机种子相同：应尽量得到可重复结果。
- 仿真中断：保留错误信息和已完成时间步，不伪造完整结果。
- Agent 工具调用参数不完整：返回结构化校验错误，让 Agent 修正或请求用户补充。
- 大模型不可用：切换到规则式实验模板或手动配置模式。
- Agent 结论与指标不一致：优先展示结构化指标，并标记解释冲突。

## 10. 验收标准

### 10.1 仿真闭环

- 用户可以在本地界面选择一个默认多目标场景并运行仿真。
- 系统能够生成至少两类有效观测，并完成融合状态更新。
- 系统能够在固定轮询和优先级调度之间切换。
- 相同配置和随机种子可以复现实验结果或达到明确的可接受误差范围。

### 10.2 结果与可视化

- 界面同时展示真实轨迹、观测点和融合轨迹。
- 用户能够看到至少四项评价指标及其时间变化或策略对比。
- 用户能够查看资源分配过程和调度原因。
- 用户能够导出实验配置和结果。

### 10.3 Agent

- 用户可以用自然语言描述一次实验目标。
- Agent 能生成可审阅的结构化实验计划。
- 经用户确认后，Agent 能调用仿真和分析工具。
- Agent 输出的关键结论能够对应到实验指标、配置或模型假设。
- 没有大模型 API 时，核心仿真和界面仍然可运行。

### 10.4 研究与求职产出

- 形成一份包含问题定义、模型假设、实验设置、指标、结果和限制的实验报告。
- 生成至少两张可用于报告的论文风格图表。
- 形成演示流程：配置场景 -> 运行仿真 -> 对比策略 -> Agent 解释。
- 形成项目简历描述和面试时可讲清楚的技术架构、难点与取舍。

## 11. 后续扩展方向

在 MVP 验证后，按优先级考虑：

1. 将加权融合替换或扩展为卡尔曼滤波、概率数据关联等方法。
2. 增加更丰富的干扰和观测退化模型。
3. 增加更多资源调度策略和离线策略评估。
4. 引入学习型调度或强化学习，并与规则基线严格对比。
5. 引入知识库检索、实验记忆和自动报告生成。
6. 增加多轮 Agent 评估、轨迹回放和决策质量指标。
7. 提升模型保真度和多维场景表达能力。

## Product Direction Update - User Platform First

- The product remains an integrated radar and electronic-countermeasure system digital model.
- Trajectory playback is temporarily deferred as a user-facing acceptance milestone because the current browser rendering path is unstable.
- The trajectory domain must remain extensible: its input boundary should allow future real datasets as well as the current synthetic simulation output. The visualization layer must consume a normalized trajectory contract rather than assume one generator.
- The next delivery priority is a complete user-facing account foundation: registration, login, logout, session state, and protected user workflows.
- MySQL is the intended durable store for users and future user-owned experiments, simulation runs, datasets, and Agent history.
- DataGrip is part of the learning workflow: database schema, migrations, permissions, queries, and operational verification should remain inspectable.
- Every completed feature or material change must update the design, architecture, and progress memory files and include a Git commit walkthrough for the user.
## Account Data Model

The first account milestone uses a durable MySQL `fp_user` table. It stores a unique username, unique email, BCrypt-ready password hash, display name, role, account status, login timestamp, and audit timestamps. Plaintext passwords are never persisted. Future user-owned experiments, datasets, simulation runs, and Agent sessions will reference `user_id`.
## Registration API

- `POST /api/v1/auth/register` accepts username, email, password, and display name.
- The backend trims identity fields, normalizes email to lowercase, rejects invalid input, checks username/email uniqueness, hashes the password with BCrypt, and returns a password-free user profile.
- Duplicate identity returns HTTP 409 with `USER_ALREADY_EXISTS`.
## Login Session API

- `POST /api/v1/auth/login` accepts username or email plus password.
- Active users receive a random opaque access token with a seven-day expiry and a password-free user profile.
- Only the SHA-256 token hash is stored in `fp_user_session`; the raw token is returned to the client and is not persisted.
- `POST /api/v1/auth/logout` accepts an optional `Authorization: Bearer <token>` header and revokes the matching session.
- Invalid credentials return HTTP 401 without revealing whether the username/email exists.
## Public Brand Home

- The first browser view is a prominent FusionPilot brand homepage rather than the simulation workbench.
- The homepage uses a local code-native radar visual, product positioning copy, capability facts, and clear login/register calls to action.
- Login and registration remain in the top-right navigation and open an account modal.
- The simulation workbench and Agent panel are protected by client session state and are rendered only after login succeeds.
- The attached frontend_design_resources.pdf is a visual reference only; it does not override project requirements or architecture.
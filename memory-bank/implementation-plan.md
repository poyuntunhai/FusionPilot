# 一体化雷达/抗干扰系统数字模型与 AI 智能决策体

## 实现计划

## 执行规则

- 按顺序一次只执行一个步骤。
- 每个步骤完成后先运行该步骤的验证，再进入下一步。
- 用户是最终测试门禁；除非用户明确授权，不默认把“代码已运行”视为“功能已验收”。
- Java 是业务和仿真核心；Python/FastAPI 是 Agent 外壳；Vue 是展示层。
- 每完成一个重要里程碑，更新项目架构和进度记录。

## 第 1 步：确定仓库骨架和本地运行约定

### 目标

建立三个应用的目录边界，统一本地端口、环境变量、启动方式和文档位置。

### 工作内容

- 创建 `backend/`、`agent-service/`、`web/` 和 `memory-bank/` 目录。
- 约定使用 VSCode 打开项目根目录，所有代码、文档和配置在同一工作区维护。
- 确定 Java、FastAPI、Vue 的本地端口。
- 创建环境变量示例文件，区分模型 API 配置和 Java/FastAPI 服务地址。
- 编写最小运行说明。

### 验证

- 三个应用目录结构清晰。
- 在 VSCode 中打开项目根目录后，可以从集成终端定位到三个应用目录。
- Java、FastAPI 和 Vue 都能分别启动最小服务或开发服务器。
- 不配置大模型 API 时，系统不会因缺少密钥而无法启动。

## 第 2 步：搭建 Java Spring Boot 领域后端

### 目标

建立 Java 主后端的分层结构和第一个健康检查接口。

### 工作内容

- 创建 Maven 项目和 Spring Boot 应用。
- 建立 `api`、`scenario`、`observation`、`fusion`、`scheduling`、`simulation`、`evaluation`、`persistence` 等包边界。
- 增加统一响应和异常处理约定。
- 增加健康检查和版本信息接口。

### 验证

- Java 服务可以启动。
- 健康检查接口返回服务状态和版本信息。
- Maven 测试可以执行。

## 第 3 步：实现实验配置模型和校验

### 目标

让 Java 后端能够接收、校验和返回一个结构化实验配置。

### 工作内容

- 定义场景、目标、观测源、融合策略、调度策略、资源限制和随机种子 DTO。
- 实现默认多目标场景。
- 实现参数范围校验和结构化错误响应。
- 实现创建或校验实验配置的 REST API。

### 验证

- 合法配置能够通过校验。
- 非法目标数量、时间步长、资源数量或噪声参数会被拒绝。
- API 返回的错误信息能够指出具体字段和原因。

## 第 4 步：实现目标运动和合成观测

### 目标

建立二维离散时间场景的真实状态和多源观测基线。

### 工作内容

- 实现匀速或分段匀速目标运动。
- 实现至少两类合成观测源，预留第三类观测源接口。
- 加入可控噪声、缺失率、延迟和置信度。
- 使用随机种子控制实验复现。

### 验证

- 给定相同配置和随机种子时，目标状态和观测结果可重复。
- 观测结果能区分真实状态、观测值和观测质量。
- 观测缺失和延迟不会导致服务崩溃。

## 第 5 步：实现多源信息融合基线

### 目标

完成时间对齐、简单关联和加权状态融合。

### 工作内容

- 定义 `FusionStrategy` 接口。
- 实现时间对齐和最近邻/距离门限关联。
- 实现基于置信度或误差的加权位置融合。
- 对无有效观测的目标使用预测状态。
- 输出融合状态、不确定性和关联置信度。

### 验证

- 多源观测可以生成融合状态。
- 缺失单个观测源时仍能输出合理状态。
- 观测冲突或目标接近时会标记低置信度。
- 融合模块可以脱离 Controller 单独测试。

## 第 6 步：实现两种资源调度策略

### 目标

完成固定轮询和基于优先级的资源调度，并记录调度原因。

### 工作内容

- 定义 `SchedulingPolicy` 接口。
- 实现固定轮询策略。
- 实现基于威胁度、状态不确定性、最近观测时间和跟踪质量的优先级策略。
- 记录每个时间步的资源分配、未服务目标和优先级因素。

### 验证

- 两种策略都能在有限资源下生成合法分配。
- 两种策略在同一场景下能够产生可比较的结果。
- 每次优先级调度都能返回可解释的排序因素。

## 第 7 步：实现仿真编排、指标和结果 API

### 目标

把目标、观测、融合、调度和评估串成一个可重复运行的 Java 仿真闭环。

### 工作内容

- 实现按时间步运行的仿真编排器。
- 记录真实状态、观测状态、融合状态、调度事件和异常。
- 实现位置误差、跟踪率、资源利用率、等待时间和调度稳定性指标。
- 实现运行实验、查询结果和对比策略 API。
- 优先使用 JSON 文件或 SQLite 保存实验结果。

### 验证

- 默认场景可以通过一个 API 完整运行。
- 结果同时包含配置快照、时间序列、聚合指标和调度记录。
- 固定随机种子下结果可复现。
- Java 后端核心仿真不依赖 FastAPI 或大模型。

## 第 8 步：搭建 Vue 可视化前端

### 目标

完成一个能够配置、运行和观察实验的浏览器界面。

### 工作内容

- 创建 Vue 3、TypeScript、Vite 项目。
- 建立场景配置面板和仿真控制区域。
- 接入 Java 配置和运行 API。
- 使用 ECharts 展示二维轨迹、观测点、融合轨迹和关键指标。
- 展示资源分配时间线和策略对比。
- 支持导出实验配置和结果。

### 验证

- 用户可以在浏览器中修改配置并运行默认实验。
- 界面能明确区分真实轨迹、观测点和融合估计。
- 至少四项指标能展示数值或趋势。
- Java 服务异常时，前端能给出可理解的错误提示。

## 第 9 步：搭建 FastAPI Agent 外壳

### 目标

建立独立的 Python/FastAPI Agent 服务，但不把仿真逻辑复制到 Python。

### 工作内容

- 创建 FastAPI 服务和 Pydantic 请求/响应模型。
- 定义实验规划、工具调用和结果解释接口。
- 使用 HTTPX 调用 Java 工具 API。
- 实现规则式模型提供者，支持没有大模型 API 时的演示。
- 预留远程模型提供者接口。

### 验证

- FastAPI 服务可以启动并通过健康检查。
- 输入自然语言实验目标时，规则式 Agent 能生成结构化实验计划。
- FastAPI 能调用 Java 的配置校验或仿真接口。
- Java 服务不可用时，FastAPI 返回结构化依赖错误。

## 第 10 步：实现 Agent 工具调用闭环

### 目标

让 Agent 完成“实验目标 -> 实验计划 -> 用户确认 -> Java 工具调用 -> 结果解释”闭环。

### 工作内容

- 实现 `validate_experiment`、`run_simulation`、`calculate_metrics` 和 `compare_scheduling_policies` 工具。
- 为工具定义清晰的 JSON Schema。
- 实现用户确认状态。
- 将 Java 结构化结果传给模型适配层或规则式分析器。
- 记录 Agent 输入、计划、工具调用、结果和解释。

### 验证

- Agent 能够生成并展示可审阅的实验计划。
- 用户确认后才会运行实验。
- 工具参数错误会被拒绝，不会执行危险或无效仿真。
- 结果解释中的关键数字可以在结构化实验结果中找到。

## 第 11 步：把 Agent 接入 Vue 界面

### 目标

在同一个可视化界面中完成实验操作和 Agent 协作。

### 工作内容

- 增加 Agent 对话区或实验计划区。
- 展示结构化实验计划和用户确认按钮。
- 展示工具调用状态、实验结果和解释。
- 在模型服务不可用时切换规则式 Agent 提示。
- 保留普通手动运行模式。

### 验证

- 用户可以从 Vue 输入自然语言实验目标。
- 用户能查看、确认或拒绝 Agent 生成的计划。
- Agent 运行结果能回填到场景和指标视图。
- FastAPI 不可用时，手动仿真功能仍然可用。

## 第 12 步：测试、演示和研究材料收口

### 目标

形成可以演示、复现、汇报和写入简历的完整成果。

### 工作内容

- 补齐 Java 单元测试、API 测试和 FastAPI 服务测试。
- 使用固定场景和随机种子生成对比实验。
- 输出至少两张论文风格图表。
- 编写实验报告，明确模型假设、指标、结果和限制。
- 编写项目演示脚本、简历项目描述和面试讲解提纲。
- 更新进度、架构和已知限制。

### 验证

- 从干净环境按说明启动三个服务。
- 完成“配置场景 -> 运行仿真 -> 对比策略 -> Agent 解释”的完整演示。
- 实验结果能够复现或明确记录允许的随机差异。
- 测试命令和演示命令可被其他人理解和执行。

## 一周推荐节奏

- 第 1 天：第 1-3 步，完成骨架、Java 服务和配置 API。
- 第 2 天：第 4-5 步，完成目标、观测和融合基线。
- 第 3 天：第 6-7 步，完成调度、仿真闭环和指标 API。
- 第 4 天：第 8 步，完成 Vue 可视化。
- 第 5 天：第 9-10 步，完成 FastAPI Agent 外壳和工具调用。
- 第 6 天：第 11 步，完成前端 Agent 协作。
- 第 7 天：第 12 步，完成测试、演示和研究材料收口。

如果时间不足，优先保证第 1-8 步完成，再实现规则式 Agent；远程大模型接入属于可替换增强项。

## Revised Execution Priority

1. Verify MySQL service and database credentials; define the user/account schema.
2. Implement Spring Boot user persistence and registration/login/logout APIs.
3. Build Vue login, registration, logout, and authenticated shell screens.
4. Verify browser-to-Java-to-MySQL interaction and document DataGrip checks.
5. Add ownership boundaries for user experiments and simulation history.
6. Return to the normalized trajectory-source contract and browser playback after the account foundation is accepted.
## Account Security Milestone Plan

1. Add local captcha challenge and require it for registration/login; verify one-time consumption and expiry.
2. Add password-reset token persistence, password replacement, and session revocation; verify invalid and reused tokens.
3. Add active Bearer-session lookup and admin role checks; verify 401, 403, and 200 paths.
4. Connect the Vue auth modal to captcha and password-reset flows.
5. Add production adapters for email delivery and external bot protection after local flow acceptance.
## Simulation Route Protection Milestone

1. Require active Bearer authentication in all simulation run and result endpoints.
2. Preserve public account bootstrap and default-configuration routes.
3. Verify missing-token requests return 401 and valid-token requests still execute and query results.
4. Keep the Java backend as the authorization owner; the Vue client only forwards the stored token.
## Agent Token Forwarding Follow-up

1. Forward the browser Authorization header from FastAPI Agent execution endpoints to Java simulation calls.
2. Keep authentication validation in Java and keep FastAPI stateless with respect to user sessions.
3. Add dependency installation and FastAPI integration tests in the next environment-validation pass.
## Multi-Model Agent Milestone

1. Restore the Python virtual-environment dependencies and load local `.env` configuration.
2. Add provider presets and a common HTTP gateway for OpenAI-compatible APIs and Anthropic Messages.
3. Connect model-generated JSON plans to the existing `ExperimentPlan` contract with deterministic fallback.
4. Expose provider capability metadata without exposing API keys.
5. Verify rule mode, provider parsing, Python tests, and source compilation before enabling real keys.
## Agent Research Cockpit Milestone

1. Add an authenticated `/agent` view while preserving the simulation workbench at `/`.
2. Show model status, domain capabilities, plan review, tool trace, and structured evidence.
3. Reuse the existing Agent session and execution APIs so the page does not duplicate simulation logic.
4. Verify route loading, Vue type checking, production build, and domain-oriented Agent workflow tests.## Agent Authorization and Ownership Milestone

1. Add Java `/api/v1/auth/me` as the shared authenticated-profile endpoint.
2. Protect all non-health FastAPI Agent routes with Java bearer validation.
3. Bind Agent traces to the authenticated user and prevent cross-user read, confirm, and execute operations.
4. Preserve bearer forwarding when Agent tools call protected Java simulation APIs.
5. Verify Python tests, Java authentication behavior, and live FastAPI-to-Java route behavior.## UI Separation and Password Policy Milestone

1. Remove the legacy Agent panel from the simulation workbench.
2. Prevent workbench dashboard content from rendering on `/agent`.
3. Add live password rule feedback and enforce the policy in Java registration and reset validation.
4. Verify Vue type checking, production build, backend compilation, and Agent tests.## Persistent Agent Session Milestone

1. Add the Java-owned Agent session table and user foreign-key ownership.
2. Add authenticated Java create, update, and read endpoints for trace snapshots.
3. Synchronize FastAPI Agent lifecycle changes and hydrate traces after restart.
4. Verify create, Java readback, Agent restart recovery, user scoping, Python tests, and Java compilation.## RAG and MCP Future Milestone

1. Define knowledge-source types and ingestion rules for project docs, metric definitions, reports, and user Agent history.
2. Add a local-first vector-store adapter, initially Chroma or Qdrant, with provider-pluggable embeddings.
3. Add a retrieval API that returns cited snippets and source metadata without treating retrieval as simulation truth.
4. Inject retrieved context into the model planner and result explainer while preserving Java as the source of experiment facts.
5. Add a FusionPilot MCP server that exposes Java-backed tools: validate experiment, run simulation, compare policies, get simulation detail, get Agent history, and retrieve evidence.
6. Migrate FastAPI Agent tool execution from the custom registry toward MCP while keeping backward compatibility during transition.
7. Verify auth isolation, retrieval quality, provider fallback, and traceability of every Agent claim to retrieved knowledge or structured simulation data.## User-Selectable Agent Model Milestone

1. Extend the Agent plan request with optional provider and model-name fields.
2. Let the model gateway resolve provider/model per task while keeping secrets server-side.
3. Add Agent cockpit controls for provider selection, model-name override, and provider readiness.
4. Preserve deterministic fallback for unconfigured external providers.
5. Verify FastAPI tests, Vue type checking, production build, and source checks.## Agent Model Dropdown Milestone

1. Add provider-specific model preset lists to FastAPI model metadata.
2. Render model names as a dropdown tied to the selected provider.
3. Reset the model selection to provider defaults when the provider changes.
4. Verify Agent tests, Python compilation, Vue type checking, production build, and source checks.
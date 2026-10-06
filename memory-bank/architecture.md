# 项目架构

## 当前架构状态

项目采用单仓库、多应用结构：

```text
项目根目录
├── backend/       Java/Spring Boot 领域后端和仿真核心
├── agent-service/ Python/FastAPI Agent 外壳和 AI 服务
├── web/           Vue/TypeScript 可视化前端
├── memory-bank/   长期设计、架构、计划和进度记忆
└── AGENTS.md      Codex/Agent 协作规则
```

## 职责边界

- Java：实验配置、仿真、观测、融合、调度、指标、结果存储和领域 API。
- FastAPI：实验计划、模型调用、工具调用循环、结果解释和 Agent 状态。
- Vue：实验配置、仿真控制、轨迹与指标展示、Agent 交互。
- Java 与 FastAPI：通过结构化 HTTP/JSON 工具协议通信。
- Vue：通过 Java API 和 FastAPI API 获取数据，不直接访问实验数据库。

## 当前文件状态

- `PRD.md`：初始需求捕获文件，保留用于追溯。
- `memory-bank/design-document.md`：MVP 设计和验收标准。
- `memory-bank/tech-stack.md`：Java、FastAPI、Vue 技术栈与服务边界。
- `memory-bank/implementation-plan.md`：一周 MVP 的可验证步骤。
- `memory-bank/progress.md`：执行进度和验证记录。
- `AGENTS.md`：项目协作规则。`readme.md`：本地开发入口说明。` .env.example`：服务端口和模型服务环境变量模板。`.vscode/`：推荐扩展和三个服务的任务配置。

## 重要约束

- Java 仿真核心不依赖 FastAPI 或大模型。
- FastAPI 不复制 Java 领域逻辑，也不直接持有实验核心数据。
- 没有大模型 API 时，规则式 Agent 和手动实验流程仍应可运行。
- 当前已创建 `backend/`、`agent-service/`、`web/` 三个业务目录，但尚未写入业务代码。`n- 本机 Java 版本为 17.0.12，Maven 未加入 PATH；Java 项目后续使用 Maven Wrapper。`n- 本地端口约定为 Java `8080`、FastAPI `8000`、Vue `5173`。


## �� 3 �������ṹ

- scenario ����ʵ�����á��۲�Դ���á��ںϷ��������Ȳ��Ժ�Ĭ�ϳ�����
- GET /api/v1/experiments/default������Ĭ��ʵ�����á�
- POST /api/v1/experiments/validate��У�鲢����ʵ�����á�
- Java Դ�ļ����� UTF-8 �� BOM��

## Step 4 Added Structure

- observation package: TargetState, Observation, ObservationSource, DefaultObservationSource, ObservationService, and ObservationController.
- POST /api/v1/observations/sample generates target states and observations for a time step.
- Observation generation remains inside the Java domain backend and does not depend on FastAPI.

## Step 5 Added Structure

- fusion/FusedTargetState.java: fused target position, velocity, uncertainty, confidence, and prediction flag.
- fusion/FusionResult.java: one target fusion result and the observations used.
- fusion/FusionSample.java: time-step level fusion response.
- fusion/FusionStrategy.java: replaceable fusion algorithm interface.
- fusion/WeightedAverageFusionStrategy.java: confidence-weighted baseline with motion prediction fallback.
- fusion/FusionService.java: applies the strategy independently to each target.
- fusion/FusionController.java: exposes POST /api/v1/fusion/sample.
- fusion tests: verify weighted fusion, prediction fallback, and multi-target separation.
## Step 6 Added Structure

- scheduling/ResourceAssignment.java: one target's allocation decision, rank, score, and explanation.
- scheduling/SchedulingResult.java: time-step scheduling output with allocated and unserved target helpers.
- scheduling/SchedulingStrategy.java: replaceable resource scheduling interface.
- scheduling/RoundRobinSchedulingStrategy.java: deterministic rotating baseline.
- scheduling/PrioritySchedulingStrategy.java: explainable priority policy based on fused-state quality.
- scheduling/SchedulingService.java: selects the strategy configured by the experiment.
- scheduling/SchedulingController.java: exposes POST /api/v1/scheduling/sample.
- scheduling/SchedulingStrategyTest.java: verifies rotation, priority ordering, and resource limits.
## Step 7 Added Structure

- simulation/StepMetrics.java: per-time-step tracking and resource metrics.
- simulation/AggregateMetrics.java: run-level aggregate metrics.
- simulation/SimulationStepResult.java: true states, observations, fused states, scheduling, and metrics for one time step.
- simulation/SimulationResult.java: complete run result with configuration and completion time.
- simulation/MetricDelta.java and StrategyComparisonResult.java: strategy comparison output.
- simulation/SimulationResultStore.java: in-memory result lookup by run ID.
- simulation/SimulationService.java: orchestrates observation, fusion, scheduling, metrics, repeatability, and policy comparison.
- simulation/SimulationController.java: exposes run, query, and compare APIs.
- simulation/SimulationServiceTest.java: verifies deterministic execution and policy comparison.
## Step 9 Added Structure

- agent-service/requirements.txt: FastAPI, HTTPX, Pydantic, Uvicorn, and pytest dependencies.
- agent-service/app/config.py: Java backend URL and Agent service port configuration.
- agent-service/app/models.py: plan, tool request, and structured Agent data models.
- agent-service/app/java_client.py: HTTPX client boundary for Java configuration and simulation APIs.
- agent-service/app/rules.py: deterministic experiment-plan generator.
- agent-service/app/main.py: Agent health, planning, default-config, and confirmed simulation endpoints.
- agent-service/tests/test_rules.py: rule planner unit tests.
## Step 10 Added Structure

- agent-service/app/trace.py: in-memory AgentTraceStore and timestamped TraceEvent records.
- agent-service/app/tools.py: tool definitions, Java-backed tool dispatch, and structured metric summarization.
- agent-service/app/agent_service.py: session creation, confirmation state, tool execution, and evidence-based analysis.
- agent-service/app/models.py: tool, trace, confirmation, execution, and analysis models.
- agent-service/app/java_client.py: shared Java request boundary plus validation and policy-comparison calls.
- agent-service/app/main.py: tool registry and Agent session APIs while preserving Step 9 endpoints.
- agent-service/tests/test_agent_loop.py: workflow, trace, analysis, and confirmation tests.
## MySQL Persistence Added Structure

- backend/pom.xml: added spring-boot-starter-jdbc, mysql-connector-j, and H2 runtime dependencies.
- backend/src/main/resources/application.yml: default datasource uses H2 in MySQL compatibility mode so tests can run without MySQL.
- backend/src/main/resources/application-mysql.yml: mysql profile datasource configuration using FUSIONPILOT_DB_* environment variables.
- backend/src/main/resources/schema.sql: creates fp_simulation_run with primary key, metric columns, JSON text columns, and query indexes.
- backend/src/main/java/com/fusionpilot/backend/persistence/SimulationRunRepository.java: persistence boundary for simulation run storage.
- backend/src/main/java/com/fusionpilot/backend/persistence/JdbcSimulationRunRepository.java: JDBC implementation that stores and restores SimulationResult JSON.
- backend/src/main/java/com/fusionpilot/backend/persistence/SimulationRunSummary.java: compact history projection for UI and API responses.
- backend/src/main/java/com/fusionpilot/backend/simulation/SimulationResultStore.java: keeps in-memory cache while delegating durable save/find/history to the repository when available.
- backend/src/main/java/com/fusionpilot/backend/simulation/SimulationService.java: exposes recent simulation history through the service layer.
- backend/src/main/java/com/fusionpilot/backend/simulation/SimulationController.java: adds GET /api/v1/simulations/history.
- docs/mysql/init.sql: creates the fusionpilot database, fusionpilot local user, and grants privileges for development.
## MySQL Relational Schema Design Added Structure

- docs/mysql/schema-design.md: explains the normalized MySQL schema, entity relationships, table responsibilities, indexes, and migration strategy from JSON snapshots to queryable relational data.
- docs/mysql/schema-relational.sql: creates normalized MySQL tables for simulation steps, target truth, observations, fused states, resource assignments, step metrics, Agent sessions, Agent trace events, and Agent tool calls.
- MySQL persistence boundary remains Java-owned for simulation domain data.
- FastAPI Agent trace tables are designed for later Agent persistence, but FastAPI must still call Java APIs for simulation facts instead of writing simulation-domain tables directly.
- Vue remains a client of backend APIs and should not read MySQL directly.
- Next architectural change should add Java repositories/services for writing normalized simulation detail rows in one transaction per simulation run.
## MySQL Normalized Detail Persistence Added Structure

- backend/src/main/resources/schema.sql: now creates the normalized simulation detail tables in addition to fp_simulation_run.
- backend/src/main/java/com/fusionpilot/backend/persistence/JdbcSimulationDetailRepository.java: writes step-level normalized detail data for each SimulationResult, including target truth, observations, fused states, resource assignments, and step metrics.
- backend/src/main/java/com/fusionpilot/backend/persistence/JdbcSimulationRunRepository.java: save() is now transactional and delegates detail-row replacement after the run-level upsert.
- backend/src/test/java/com/fusionpilot/backend/persistence/JdbcSimulationRunRepositoryTest.java: verifies normalized persistence through the real Spring service and H2 MySQL-compatible test datasource.
- Persistence responsibility remains in Java; FastAPI Agent still calls Java APIs for simulation facts rather than writing simulation-domain tables.
- The normalized tables are currently write-side infrastructure; the next backend layer should expose read APIs for normalized playback, charting, and report generation.
## MySQL Normalized Detail Query API Added Structure

- backend/src/main/java/com/fusionpilot/backend/simulation/SimulationRunDetail.java: API DTO for normalized playback data, split into truth, observation, fused state, resource assignment, and metric records.
- backend/src/main/java/com/fusionpilot/backend/persistence/JdbcSimulationDetailQueryRepository.java: read-side JDBC repository that joins normalized detail tables by runId and returns ordered playback/chart data.
- backend/src/main/java/com/fusionpilot/backend/simulation/SimulationService.java: now exposes detail(runId) through the service layer using the optional detail query repository.
- backend/src/main/java/com/fusionpilot/backend/simulation/SimulationController.java: adds GET /api/v1/simulations/{runId}/detail.
- backend/src/test/java/com/fusionpilot/backend/persistence/JdbcSimulationDetailQueryRepositoryTest.java: verifies normalized detail readback through the real Spring service.
- backend/src/test/java/com/fusionpilot/backend/persistence/JdbcSimulationRunRepositoryTest.java: now scopes detail-table assertions by runId for reliable test isolation.
- Vue should use the detail endpoint for trajectory playback and metric charts instead of re-parsing full SimulationResult JSON.
- FastAPI Agent can continue using existing Java APIs, but later can call detail(runId) for evidence-rich explanations and report generation.
## Demo Artifact Generation Added Structure

- docs/demo/generate-demo.ps1: local demo generator that calls the Java backend default scenario and simulation APIs, then writes reproducible demo artifacts.
- docs/demo/latest-simulation.json: generated simulation snapshot containing the Java API response, backend base URL, timestamp, and optional detail response.
- docs/demo/simulation-report.md: generated Markdown summary for report/demo use, including configuration, aggregate metrics, and data provenance.
- docs/demo/simulation-viewer.html: generated standalone Canvas viewer for truth trajectories, fused estimates, aggregate metrics, time-step playback, and resource assignments.
- The demo viewer uses Java simulation results as its only data source. It does not read MySQL directly and does not duplicate simulation-domain logic.
- This path is a reliable demo/export fallback while the Vue manual run-state bug is still being repaired.
- Vue should later reuse the same data mapping from SimulationResult or the normalized detail API, but remain the primary interactive UI.
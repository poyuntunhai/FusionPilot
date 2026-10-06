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
## Step 16 Completed Structure

- web/src/App.vue: renders the immediate Java simulation snapshot, then refreshes normalized playback detail in the background; request tokens and AbortController ownership prevent stale responses from changing the active run state.
- web/package.json and web/tsconfig.app.json: use no-emit Vue type checking and the Vite config loader that works in the local Windows environment.
- backend/target/fusionpilot-backend-0.1.0-SNAPSHOT.jar: must be rebuilt after backend route changes before runtime verification; an older packaged jar can omit the normalized detail route even when source tests pass.
- The frontend remains dependent on Java APIs for simulation facts and does not access MySQL directly.
- The normalized detail endpoint is now usable for trajectory playback and metric chart data, while the original simulation snapshot remains the fast initial response and fallback.
## Step 16.1 Runtime Proxy Boundary

- Vite API proxies use 127.0.0.1 for the Java and FastAPI local services to make the browser-to-local-service boundary deterministic on Windows.
- Vue simulation requests allow 30 seconds and use a 32-second watchdog; timeout and cancellation still release loading state and progress controls.
- Runtime verification through a temporary Vite port confirmed the frontend proxy returns the Java default configuration and simulation snapshot successfully.
## Product Direction Update - October 6, 2026

- Current priority moved from browser trajectory playback to the account and persistence foundation: MySQL user schema, registration, login, logout, session handling, and Vue account screens.
- Java/Spring Boot remains the owner of authentication, authorization, user persistence, and simulation-domain facts. Vue remains a client and FastAPI remains the Agent boundary.
- Trajectory playback is deferred, but its future contract must accept both generated simulation trajectories and imported real datasets. A normalized trajectory source boundary should prevent the visualization from depending on one data generator.
- MySQL and DataGrip are first-class development tools for learning front-end/backend/database interaction and operations.
- Each completed feature or material change must be recorded in design-document.md, architecture.md, and progress.md, followed by a user-facing Git commit walkthrough.
## Account Persistence Foundation

- `backend/src/main/resources/schema.sql` now creates `fp_user` for durable account records in the default and test database initialization path.
- `backend/src/main/resources/application-mysql.yml` uses `127.0.0.1` for the local MySQL profile, matching the Windows local-service convention.
- `docs/mysql/schema-relational.sql` mirrors the account table for DataGrip/MySQL relational setup.
- Authentication endpoints and password hashing are intentionally not included in this milestone; they are the next Java feature built on this schema.
## Registration Feature

- `backend/src/main/java/com/fusionpilot/backend/account/` owns account request/response models, JDBC persistence, registration service logic, and the REST controller.
- `spring-security-crypto` supplies BCrypt without enabling Spring Security auto-configuration yet; authentication/session behavior is the next milestone.
- `GlobalExceptionHandler` maps duplicate account identity to a stable 409 API error.
## Login Session Feature

- `fp_user_session` stores hashed bearer tokens, expiry, revocation time, and the owning user ID with a foreign key to `fp_user`.
- `UserRepository` reads login credentials and updates `last_login_at`; `SessionRepository` creates and revokes sessions.
- `UserService` owns BCrypt verification, secure token generation, SHA-256 token hashing, and seven-day expiry policy.
- The current milestone provides the auth API contract; a request filter for protecting simulation/user routes will be added after the Vue client can retain and send the token.
## Public Homepage and Client Gate

- web/src/App.vue renders a public FusionPilot landing state before authentication and preserves the existing workbench as the authenticated state.
- web/src/styles.css provides the local radar/sensor visual, responsive hero layout, and top-right account actions without an external paid asset dependency.
- Login and registration use the existing Java auth endpoints; successful login stores the opaque access token and user profile in browser local storage.
- Simulation and Agent requests attach the bearer token when available. The current UI gate is a presentation boundary; backend route authorization remains a follow-up hardening step.
## Authentication Security Foundation

- `CaptchaService` issues short-lived, single-use arithmetic challenges for the local auth flow; the answer is stored only as a BCrypt hash in memory.
- `PasswordResetRepository` persists short-lived SHA-256 reset-token hashes in `fp_password_reset_token`; raw tokens are never stored.
- `UserService.authenticateBearer()` resolves an active session from `fp_user_session`; `requireAdmin()` enforces the active `ADMIN` role.
- `AdminController` owns user listing, status changes, and forced session revocation under the admin boundary.
- `UserController` owns captcha issuance and password-reset request/confirmation endpoints.
- The current captcha and reset-token delivery are local development implementations. SMTP/Resend/Turnstile integration remains an adapter-level follow-up.
## Password Visibility Control

- `web/src/App.vue` owns `showPassword` and `showNewPassword` UI state for password and reset-password fields.
- `web/src/styles.css` renders the eye control locally without adding an icon dependency.
- This is presentation-only; password values are still submitted through the existing HTTPS/API boundary and are never persisted in the browser as plain account data.
## Simulation API Route Protection

- `SimulationController` now requires an active Bearer session before running a simulation or reading simulation history, detail, result, or policy comparison data.
- Authentication remains in the Java account boundary through `UserService.authenticateBearer()`; Vue only supplies the token and does not implement authorization.
- Public account bootstrap routes remain separate from protected simulation routes. `GET /api/v1/experiments/default` remains available for loading the initial form, while simulation execution and stored results require login.
- `JdbcSimulationDetailRepository` accepts both named and generic generated-key responses so normalized detail persistence works with MySQL and H2.
## Agent Authorization Forwarding

- FastAPI remains an orchestration boundary and does not validate or persist Java sessions.
- Agent simulation and comparison calls accept the incoming Authorization header and forward it to Java unchanged.
- Java remains the single owner of bearer-session validation and simulation authorization.
## Multi-Model Agent Gateway

- `agent-service/app/model_gateway.py` is the provider boundary for external model calls. It supports OpenAI, Claude, DeepSeek, Qwen, and Zhipu through provider presets.
- OpenAI, DeepSeek, Qwen, and Zhipu use the OpenAI-compatible chat-completions protocol; Claude uses the Anthropic Messages protocol.
- `agent-service/app/model_planner.py` converts model JSON into the existing `ExperimentPlan` DTO and falls back to `rules.py` when configured.
- `agent-service/app/config.py` loads local `.env` values without persisting API keys in source control.
- Java remains the source of truth for simulation facts. External models only propose plans and never execute domain logic directly.
## Domain Agent Research Cockpit

- The Vue application now has two authenticated views: `/` for the simulation workbench and `/agent` for the Agent research cockpit.
- The Agent cockpit presents model status, mission brief, plan review, tool trace, and structured evidence as first-class research workflow areas.
- Domain copy and capability labels explicitly connect Agent work to radar, EO/IR, prior-knowledge observations, information fusion, resource scheduling, and noise/missing/delay countermeasure evaluation.
- Existing Agent session and tool functions are reused; the subpage is a presentation and workflow boundary, not a second simulation implementation.## Agent Authorization and Trace Ownership

- FastAPI Agent routes use the `require_agent_user` dependency. It forwards the bearer token to Java `GET /api/v1/auth/me` and does not maintain a second session authority.
- Agent health remains public for service probes; planning, model metadata, tool metadata, configuration, execution, and trace routes require an active Java session.
- `AgentTrace.owner_user_id` binds each in-memory trace to the authenticated Java user. Confirm, execute, and read operations return `TRACE_NOT_FOUND` for another user's trace.
- The Agent forwards the validated bearer token to Java simulation calls so the Java domain boundary remains authoritative for simulation access.
- `UserController.me` exposes the minimal authenticated profile needed by the Agent boundary. `UserRepository.insert` requests only `user_id` as the generated key for H2/MySQL compatibility.## UI Separation and Password Policy

- The authenticated simulation workbench is rendered only when `activeView === 'workbench'`; the Agent route no longer renders the workbench dashboard or the legacy embedded Agent panel.
- The `/agent` view is a dedicated Agent research cockpit containing mission brief, plan review, tool trace, and structured evidence.
- Registration and password reset use one shared policy: 10-100 characters and at least two of letters, digits, and symbols. The Vue form gives live feedback, while Java Bean Validation enforces the rule at the API boundary.## Persistent Agent Session Storage

- Java now owns `fp_agent_session` persistence for Agent trace snapshots, keyed by `user_id` and protected by the existing bearer-session boundary.
- `backend/src/main/java/com/fusionpilot/backend/agent/AgentSessionRepository.java` stores plan, events, status, confirmation state, last result, and structured analysis as JSON while keeping ownership relational.
- `AgentSessionController` exposes authenticated create, update, and user-scoped read endpoints for FastAPI; FastAPI never connects to MySQL directly.
- FastAPI keeps a memory cache for active workflows, synchronizes snapshots to Java after creation, confirmation, and tool execution, and hydrates a trace from Java after service restart.
- The schema uses `events_json` in the session snapshot for atomic workflow recovery; the existing normalized event/tool tables remain available for a later event-level query/reporting milestone.## Planned RAG and MCP Architecture

- Planned RAG components: document ingestion, chunking, embedding generation, vector storage, retrieval, optional reranking, and prompt-context assembly in FastAPI.
- Planned knowledge sources: `memory-bank/`, project docs, schema/design notes, simulation reports, metric definitions, and user-owned Agent/session history.
- Vector storage can start local-first with Chroma or Qdrant. Hosted vector storage remains optional and should be isolated behind a repository/interface.
- Embedding generation should be provider-pluggable, matching the existing multi-model gateway style. API keys must remain in local `.env` files and never be exposed to Vue or committed.
- Planned MCP boundary: a FusionPilot MCP server exposing Java-backed domain tools and Agent-history resources. The current `agent-service/app/tools.py` is a custom interim tool registry, not MCP.
- Java remains the authority for authenticated data access and simulation facts. RAG retrieval and MCP tool calls must not bypass Java ownership checks.## User-Selectable Agent Model

- `PlanRequest` now accepts optional `model_provider` and `model_name` fields from the Agent cockpit.
- `model_gateway.py` can resolve a requested provider/model for one Agent task while still reading API credentials only from local environment variables.
- The Vue Agent cockpit exposes a provider selector, model-name input, and readiness indicator. API keys are never entered or displayed in the browser.
- Unconfigured external providers fall back to the deterministic rule planner when fallback is enabled, and the generated plan records the requested provider/model as fallback metadata.## Agent Model Preset Lists

- `ProviderPreset` now includes `model_options` for each external provider. `/api/v1/agent/models` returns these options as `modelOptions` with provider metadata.
- The Agent cockpit renders model names as a provider-specific dropdown instead of a free-text input.
- Switching the provider resets the selected model to that provider's default model. Rule mode keeps the model selector disabled and uses the local deterministic planner.## Frontend Session and Scene Readiness

- Vue no longer trusts local storage alone for authenticated startup. A stored bearer token must be accepted by Java `GET /api/v1/auth/me` before the app restores the user profile.
- Invalid stored sessions are cleared client-side and routed back to the login modal, preventing the workbench and Agent cockpit from showing unusable authenticated controls.
- Login and valid session recovery preload Java's default experiment config and refresh FastAPI Agent model metadata.
- Workbench run/compare actions and Agent plan creation call the shared scene-readiness guard, so the Java default scenario is loaded before domain actions are submitted.
- Java remains the authority for session validity and simulation facts; Vue only coordinates user-facing readiness and never grants access by itself.
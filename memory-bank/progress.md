# 项目进度

## 当前状态

- 阶段：第 1 步完成，项目骨架和 VSCode 本地开发约定已建立。
- 当前步骤：第 1 步待用户确认；确认后进入第 2 步，搭建 Java Spring Boot 领域后端。
- 开发环境：VSCode + 集成终端。
- 架构：Java/Spring Boot 后端 + Python/FastAPI Agent 外壳 + Vue 可视化前端。

## 已完成

- 完成初始 PRD。
- 完成 MVP 设计文档。
- 完成技术栈方案。
- 完成一周实现计划。
- 初始化 `memory-bank/` 和 `AGENTS.md`。
- 创建 `backend/`、`agent-service/`、`web/` 三个应用目录。
- 创建 `.env.example`、`.gitignore` 和 VSCode 任务/扩展配置。

## 第 1 步验证结果

- 状态：通过。
- 端口约定：Java `8080`、FastAPI `8000`、Vue `5173`。
- 工具链：Java `17.0.12`、Python `3.11.9`、Node `v24.16.0`、npm `11.13.0` 可用。
- 已知限制：Maven 未加入 PATH，Java 项目后续使用 Maven Wrapper。
- 说明：三个应用的实际启动验证分别放在第 2、8、9 步，避免提前复制业务逻辑。
- 下一步：等待用户确认第 1 步，然后进入第 2 步，搭建 Java Spring Boot 领域后端。

## 记录规则

每个计划步骤验证并经用户确认后，在此追加：

- 步骤编号和名称
- 实际完成内容
- 验证方式和结果
- 已知限制
- 下一步


## �� 3 ����֤���

- ״̬��ͨ����
- �����ʵ������ DTO��Ĭ�ϳ���������У������� REST API��
- �ӿڣ�GET /api/v1/experiments/default��POST /api/v1/experiments/validate��
- �Ƿ����û᷵�� 400 �ͽṹ�� VALIDATION_ERROR��
- ��һ������ 4 ����ʵ�ֶ�άĿ���˶��ͺϳɹ۲⡣

## Step 4 Verification

- Status: PASSED
- Implemented 2D discrete-time target motion and synthetic observations.
- Added radar, EO/IR, and prior-knowledge observation sources.
- Added noise, missing rate, delay, confidence, and seeded reproducibility.
- API: POST /api/v1/observations/sample.
- Next: Step 5, implement multi-source information fusion baseline.

## Step 5 Verification

- Status: PASSED
- Implemented a replaceable FusionStrategy interface.
- Added confidence-weighted position fusion for multiple observation sources.
- Added per-target fusion service and POST /api/v1/fusion/sample.
- When no valid observation is available, the service returns a motion-predicted state with higher uncertainty.
- Added unit tests for confidence weighting, missing observations, and independent multi-target fusion.
- MVP limitation: current association groups observations by target ID; time alignment and distance-gate association remain future enhancements.
- Next: Step 6, implement fixed-round-robin and priority-based radar resource scheduling.
## Step 6 Verification

- Status: PASSED
- Implemented the replaceable SchedulingStrategy interface.
- Added round-robin scheduling with time-step rotation.
- Added priority scheduling based on uncertainty, predicted-only state, tracking quality, and motion.
- Scheduling results include allocated targets, unserved targets, rank, score, and human-readable reasons.
- Added POST /api/v1/scheduling/sample to connect observation, fusion, and scheduling for one time step.
- Added unit tests for rotation, priority selection, and resource limits.
- MVP limitation: scheduling currently consumes one-step fused states; multi-step waiting-time statistics will be completed in the simulation and evaluation phase.
- Next: Step 7, implement simulation orchestration, evaluation metrics, and result API.
## Step 7 Verification

- Status: PASSED
- Implemented multi-step simulation orchestration across observation, fusion, and scheduling.
- Added step-level metrics for position error, tracking rate, resource utilization, allocated targets, and unserved targets.
- Added aggregate metrics for average position error, tracking rate, resource utilization, average waiting time, and scheduling switches.
- Added in-memory simulation result storage and result lookup by run ID.
- Added POST /api/v1/simulations/run, GET /api/v1/simulations/{runId}, and POST /api/v1/simulations/compare.
- Added deterministic repeatability and scheduling strategy comparison tests.
- MVP limitation: result storage is in memory; persistence and richer multi-run comparison remain future enhancements.
- Next: Step 8, build the Vue visualization frontend.
## Step 9 Verification

- Status: PASSED
- Implemented an independent FastAPI Agent service with rule-based planning mode.
- Added GET /api/v1/agent/health.
- Added POST /api/v1/agent/plan for natural-language experiment goals.
- Added Java HTTP client calls for default configuration and simulation execution.
- Added structured dependency errors when the Java backend is unavailable.
- Added confirmation protection for the simulation tool endpoint.
- Added Python tests for plan generation, configuration overrides, and policy comparison intent.
- MVP limitation: the Agent currently uses deterministic rules instead of a remote large language model.
- Next: Step 10, implement the Agent tool-calling loop, confirmation state, result analysis, and trace records.
## Step 10 Verification

- Status: PASSED
- Added a FastAPI Agent workflow loop with tool registration, confirmation, execution, analysis, and trace persistence.
- Added GET /api/v1/agent/tools for the structured tool registry.
- Added POST /api/v1/agent/sessions to create a planned Agent session.
- Added POST /api/v1/agent/sessions/{traceId}/confirm for explicit user confirmation.
- Added POST /api/v1/agent/sessions/{traceId}/execute for confirmed tool execution.
- Added GET /api/v1/agent/sessions/{traceId} for trace inspection.
- Added validation, simulation, metric summary, and scheduling-policy comparison tools.
- Result analysis only uses structured metrics returned by the Java backend.
- Added tests for tool registration, trace persistence, metric evidence, and confirmation protection.
- MVP limitation: the workflow is still deterministic and in-memory; remote LLM planning and durable persistence remain future enhancements.
- Next: Step 11, connect the Agent workflow to the Vue interface and improve end-to-end observability.
## MySQL Persistence Step Verification

- Status: PASSED
- Added JDBC-based persistence for simulation run records.
- Added MySQL profile configuration and local H2 fallback for ordinary tests.
- Added fp_simulation_run table for run metadata, aggregate metrics, config JSON, and result JSON.
- Added GET /api/v1/simulations/history for recent run lookup.
- Verified Java backend can start with the mysql profile.
- Verified a simulation run writes a row into MySQL.
- Verified recent simulation history can be queried through the Java API.
- Verified MySQL can query fp_simulation_run directly.
- MVP limitation: step-level trajectory, observation, fusion, scheduling, and Agent trace data are still stored as JSON blobs or in memory; full relational normalization remains a later step.
- Next: decide whether to normalize simulation details into MySQL tables or repair the Vue Agent result playback using the now-persistent history API.
## MySQL Relational Schema Design Verification

- Status: PASSED
- Added docs/mysql/schema-design.md as the relational design note for simulation details and Agent trace persistence.
- Added docs/mysql/schema-relational.sql as the MySQL DDL draft for normalized detail tables.
- Verified schema-relational.sql can be executed against the local fusionpilot MySQL database.
- Verified the expected fp_* tables are visible after running the DDL.
- Key backend learning point: the project now has a concrete ER-style data model covering run, step, truth, observation, fused state, resource assignment, step metric, Agent session, Agent trace event, and Agent tool call records.
- Current limitation: Java still writes only the run-level persistence table and JSON snapshots; normalized detail-table writes remain the next implementation step.
- Next: implement Java-side transactional persistence for normalized simulation detail tables.
## MySQL Normalized Detail Persistence Verification

- Status: PASSED
- Added Java transactional persistence for normalized simulation detail tables.
- Added schema.sql DDL for fp_simulation_step, fp_target_truth, fp_observation, fp_fused_state, fp_resource_assignment, and fp_step_metric.
- Added JdbcSimulationDetailRepository to replace detail rows for a simulation run and batch-write truth, observation, fusion, assignment, and step metric rows.
- Updated JdbcSimulationRunRepository so save() writes the run snapshot and normalized detail rows in one Spring transaction.
- Added JdbcSimulationRunRepositoryTest to verify that one simulation run writes both run-level and detail-level records.
- Fixed generated-key handling by explicitly reading the step_id key, avoiding H2 returning both step_id and created_at.
- Verified Maven backend test suite passes: 17 tests, 0 failures, 0 errors.
- Backend learning points covered: transaction boundary, foreign-key cascade delete, generated keys, JDBC batch inserts, H2/MySQL compatibility, and normalized read/write model design.
- Current limitation: Java still does not expose detail-query APIs for normalized tables; Vue and FastAPI still consume the full SimulationResult JSON or run history API.
- Next: add Java detail-query APIs for trajectory playback and metric charts from normalized MySQL data.
## MySQL Normalized Detail Query API Verification

- Status: PASSED
- Added GET /api/v1/simulations/{runId}/detail for normalized simulation-detail playback data.
- Added SimulationRunDetail DTO with truth, observations, fusedStates, assignments, and metrics sections.
- Added JdbcSimulationDetailQueryRepository to read normalized MySQL/H2 detail tables with runId-scoped joins.
- Updated SimulationService to expose detail(runId) while keeping Java as the simulation-domain owner.
- Updated SimulationController to expose the detail API before the generic /{runId} lookup route.
- Added JdbcSimulationDetailQueryRepositoryTest to verify a short simulation can be read back from normalized tables.
- Updated the existing persistence test to scope detail-table counts by runId so tests remain isolated when multiple simulations run in the same H2 context.
- Verified Maven backend test suite passes: 18 tests, 0 failures, 0 errors.
- Backend learning points covered: read DTO design, repository query boundary, SQL joins, runId-scoped filtering, route ordering, and test isolation.
- Current limitation: Vue still needs to call the new detail endpoint for chart playback; FastAPI Agent still uses existing Java result APIs.
- Next: wire Vue playback and metric views to GET /api/v1/simulations/{runId}/detail.
## Demo Viewer Verification

- Status: PASSED
- Added a stable demo-generation path under docs/demo that calls the Java simulation API and writes local demo artifacts.
- Generated latest-simulation.json from the Java backend response, preserving the full simulation snapshot and data provenance.
- Generated simulation-report.md with run ID, scenario, configuration, aggregate metrics, and source API notes.
- Generated simulation-viewer.html as a standalone Canvas-based playback page for truth trajectories, fused estimates, metrics, time-step slider, and resource assignments.
- Fixed the viewer-generation script so PowerShell does not corrupt JavaScript template expressions during HTML generation.
- Verified the generated HTML script with node --check and a small runtime mock confirming draw(0), step label, and assignment rows execute.
- User verified the standalone simulation-viewer.html displays successfully.
- Current limitation: the Vue manual simulation button can still get stuck in the running state; the stable viewer proves the Java simulation data path is valid and gives a reliable demo/export fallback.
- Next: repair the Vue simulation UI by reusing the working data mapping and simplifying the run-state lifecycle.
## Step 16 Verification

- Status: PASSED
- Wired Vue playback to GET /api/v1/simulations/{runId}/detail through a background refresh, so the run result is rendered before normalized detail loading completes.
- Added request ownership tokens, explicit AbortController handling, cancellation handling, and a watchdog for manual simulation and policy comparison requests.
- Preserved the snapshot result as the immediate fallback when the detail endpoint is unavailable.
- Verified npm.cmd run build: Vue type checking and Vite production build passed.
- Verified the Java backend test suite: 18 tests, 0 failures, 0 errors.
- Rebuilt the Spring Boot jar before runtime verification; the stale jar from before Step 15 did not contain the detail route.
- Verified runtime API flow with the rebuilt jar: health UP, simulation run succeeded, and normalized detail returned truth, observations, fused states, assignments, and metrics.
- Current limitation: browser-level visual verification is still manual because no browser connector is available in this environment.
- Next: user review of the Vue run/cancel/detail playback behavior, then continue with broader demo and research-material acceptance work.
## Step 16.1 Proxy and wait-state repair

- Fixed both Vite configs to proxy Java and Agent requests through 127.0.0.1 instead of localhost, avoiding Windows localhost/IPv6 ambiguity.
- Replaced the 5-second frontend request timeout with a 30-second timeout and a 32-second run watchdog so normal browser startup or proxy delays do not leave the run button in a short-window race.
- Verified Vue type checking and production build; verified a temporary Vite server on port 5176 returned the app, default config, and a 60-step simulation through the proxy.
- The stable standalone viewer remains available under docs/demo/simulation-viewer.html for trajectory and time-step slider verification.
## Process Rule Update - October 6, 2026

- Product direction now prioritizes the user account and MySQL foundation before browser trajectory playback.
- Trajectory playback remains a deferred feature with a future normalized source contract for synthetic results and imported real datasets.
- Design, architecture, and implementation-plan memory files were updated with this priority change and the requirement to teach Git submission after each accepted feature.
- The previous user-schema code patch was not applied because the relational schema context did not match; no database code change is claimed in this checkpoint.
## Account Persistence Foundation Verification

- Status: PASSED
- Added the MySQL `fp_user` table with unique username/email constraints, password-hash storage, role/status fields, login timestamp, and audit timestamps.
- Updated the MySQL profile to use `127.0.0.1` and mirrored the table in the relational schema documentation.
- Verified the local MySQL80 service and `fusionpilot` credentials through MySQL CLI.
- Applied `backend/src/main/resources/schema.sql` successfully and confirmed `fp_user` with `DESCRIBE`.
- Re-applied `docs/mysql/schema-relational.sql` successfully; schema creation is idempotent.
- Verified Maven backend tests: 18 tests, 0 failures, 0 errors.
- Next: implement Java user repository and registration API; after verification, pause for the user's Git commit.
## Registration API Verification

- Status: PASSED
- Added `POST /api/v1/auth/register` with validation, duplicate detection, BCrypt password hashing, and password-free response DTO.
- Verified Maven backend tests: 18 tests, 0 failures, 0 errors.
- Rebuilt and started the backend with the MySQL profile on temporary port 8090; MySQL connection succeeded.
- Registered `codex_demo` successfully, confirmed the row in MySQL, and confirmed the stored password begins with the BCrypt `$2a$` prefix.
- Repeated registration returned HTTP 409 for the duplicate username/email.
- DataGrip automation was unavailable because the Windows computer-use helper failed to start twice; MySQL CLI verification was used instead.
- Next: implement login using the same account boundary, then pause for user verification and Git commit.
## Login Session API Verification

- Status: PASSED
- Added `fp_user_session` with user foreign key, token hash uniqueness, expiry, and revocation indexes.
- Added `POST /api/v1/auth/login` and `POST /api/v1/auth/logout`.
- Login accepts username or email, verifies BCrypt, creates a random seven-day bearer token, and stores only its SHA-256 hash.
- Logout revokes the matching session using the Bearer token header.
- Verified Maven backend tests: 18 tests, 0 failures, 0 errors.
- Verified on MySQL profile port 8091: successful login, logout, revoked session row, updated `last_login_at`, and HTTP 401 for an incorrect password.
- Next: build Vue registration/login/logout screens and token state handling, then pause for user verification and Git commit.
## FusionPilot Public Homepage Verification

- Status: PASSED
- Added a high-visibility public FusionPilot landing state with brand title, product positioning, capability facts, radar-style local visual, and login/register calls to action.
- Kept login and registration in the top-right navigation with a modal account flow.
- Kept the existing simulation workbench and Agent panel hidden until a valid client login session exists.
- Verified npm.cmd exec vue-tsc -- --noEmit.
- Verified npm.cmd run build; Vite production build completed successfully. Vite reported only the existing large ECharts bundle warning.
- The attached PDF was treated as a visual reference, not as a project instruction document. No paid or external asset dependency was added.
- Next: user opens the site and verifies the visual direction, then commit the account and homepage milestone together.
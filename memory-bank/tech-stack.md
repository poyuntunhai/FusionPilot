# 技术栈方案

## 1. 选型结论

本项目采用 **Java/Spring Boot 传统后端 + Python/FastAPI Agent 外壳 + Vue 可视化前端** 的架构。

核心原则：

- Java 负责传统后端工程、仿真领域模型、任务编排、数据管理和稳定 API，是系统的业务核心。
- Python/FastAPI 负责 Agent 外壳、提示词、模型调用、结构化输出和 AI 相关扩展。
- Vue 负责实验配置、仿真回放、轨迹展示、指标对比和 Agent 对话界面。
- Java 仿真基线不依赖大模型，确保没有 API 或 FastAPI 不可用时仍能完成科研实验。
- Agent 能力通过 FastAPI 内部适配接口隔离，避免绑定单一模型供应商。
- MVP 优先使用本地单机部署和轻量存储，不引入不必要的分布式组件。

## 2. 服务职责

### 2.1 Java 领域后端

- Java 21 LTS 或当前本地可用的稳定 LTS 版本
- Spring Boot 3.x
- Spring Web：提供 REST API
- Spring Validation：校验实验配置
- Jackson：配置、状态和结果的 JSON 序列化
- Maven：依赖管理、构建和测试

选择理由：

- 符合传统 Java 后端实习路线，能够展示分层架构、接口设计、参数校验和测试能力。
- Spring Boot 适合快速构建本地可运行的 API 服务。
- Java 的类型系统适合表达实验配置、仿真状态、观测、融合结果和调度决策等领域对象。

Java 服务负责：

- 场景配置和参数校验
- 目标、观测、融合、调度和仿真运行
- 指标计算、策略对比和结果存储
- 实验导出和历史实验查询
- 对前端提供稳定的领域 REST API
- 对 FastAPI 提供受控的 Agent 工具 API

### 2.2 FastAPI Agent 服务

- Python 3.11+
- FastAPI
- Pydantic 2
- Uvicorn
- HTTPX：调用 Java 工具 API 或远程模型 API
- pytest：服务测试

FastAPI 服务负责：

- 接收用户自然语言实验目标
- 生成结构化实验计划
- 管理 Agent 的工具调用循环
- 适配云端或本地大模型
- 解析和校验模型结构化输出
- 将 Java 仿真结果转换为 Agent 可分析的上下文
- 生成结果解释、异常说明和下一步实验建议

选择理由：

- FastAPI 适合快速搭建 AI 服务和结构化接口。
- Python 生态更适合后续接入模型 SDK、评估工具、检索和科研分析库。
- 将 AI 逻辑从 Java 领域后端隔离，可以避免仿真核心被模型调用细节污染。

FastAPI 不是本项目的领域主后端，也不直接持有实验核心数据；它是围绕 Java 领域后端构建的 Agent 外壳服务。

### 2.3 前端

- Vue 3
- TypeScript
- Vite
- Pinia：前端状态管理
- Vue Router：页面路由
- ECharts：轨迹、指标和调度图表
- 浏览器 Fetch API 或 Axios：调用 Java API 和 Agent API

Vue 替换 React，原因是：

- 更符合你希望补充的前端技术栈。
- Vue 3 + TypeScript + Vite 能快速完成一周 MVP。
- 组件边界适合拆分场景配置、仿真视图、指标面板和 Agent 面板。

### 2.4 前后端通信

- Java REST/JSON：场景配置、运行实验、查询结果、策略对比和导出。
- FastAPI REST/JSON：Agent 对话、实验规划、结果解释和模型健康检查。
- Java 与 FastAPI 之间使用内部 REST/JSON 工具调用。
- 可选 SSE：仿真进度或逐时间步回放。
- MVP 默认先支持“提交实验 -> 返回结果 -> 前端回放”，只有在时间充足时再加入实时推送。

推荐调用关系：

```text
Vue 前端
  ├── Java API：场景、仿真、指标、结果
  └── FastAPI API：Agent 规划、解释、对话

FastAPI Agent 服务
  ├── 调用模型提供商或本地模型
  └── 调用 Java 工具 API

Java 领域后端
  └── 运行仿真、融合、调度和指标计算
```

为减少前端复杂度，MVP 可以让 Vue 通过 Java 统一代理 Agent 请求；如果实现成本过高，再允许 Vue 直接调用 FastAPI，并通过开发服务器代理解决跨域。

## 3. 仿真与领域模块

后端内部采用面向领域的模块划分，不把所有逻辑堆在 Controller 中：

- `scenario`：场景、目标、环境和实验配置
- `observation`：观测源和观测质量
- `fusion`：时间对齐、关联、加权融合和状态不确定性
- `scheduling`：固定轮询和优先级调度
- `simulation`：时间步编排和结果记录
- `evaluation`：误差、覆盖率、资源利用率和策略对比
- `agent`：Java 侧 Agent 请求编排、会话记录和 FastAPI 客户端
- `model`：Java 侧模型服务状态和 Agent 服务适配
- `api`：REST 请求、响应和异常映射

推荐使用接口隔离策略：

- `FusionStrategy`
- `SchedulingPolicy`
- `ObservationSource`
- `SimulationRunner`
- `ExperimentAnalyzer`

第一周只实现必要的默认实现，不提前建设复杂插件系统。

FastAPI 内部单独维护：

- `agent/planner`：实验计划生成
- `agent/tools`：工具描述、参数校验和工具调用
- `agent/analyzer`：结果解释和建议
- `providers`：云端模型、本地模型和规则式模型适配
- `schemas`：Pydantic 请求、响应和工具协议

## 4. Agent 技术路线

### 4.1 第一阶段

Agent 采用“结构化规划 + 工具调用 + 结果解释”模式：

1. 接收用户的自然语言实验目标。
2. 通过模型适配器生成结构化实验计划。
3. 校验计划中的场景、策略、指标和参数。
4. 在用户确认后调用 Java 工具服务。
5. 将结构化实验结果交给模型生成解释和下一步建议。

### 4.2 模型适配

FastAPI 内部定义统一的 Python 接口，例如：

- 输入：系统提示、用户任务、实验上下文和工具描述。
- 输出：结构化实验计划、工具调用请求或结果解释。

至少提供两个实现方向：

- `RuleBasedModelProvider`：无 API 时的规则式演示和固定模板。
- `RemoteModelProvider`：通过 HTTP 调用任意兼容的云端或本地模型服务。

后续可以评估 LangChain/LangGraph 或其他 Agent 编排工具，但 MVP 不应让 Agent 框架遮蔽工具协议、状态管理和错误处理这些基本能力。

### 4.3 工具协议

Agent 可调用的工具至少包括：

- `validate_experiment`
- `run_simulation`
- `compare_scheduling_policies`
- `calculate_metrics`
- `export_experiment`

工具输入和输出使用明确的 JSON Schema；Java 侧用 DTO 表达，FastAPI 侧用 Pydantic 表达。工具错误返回结构化错误，不依赖解析日志文本。

## 5. 数据存储

MVP 采用轻量本地存储：

- 实验配置和结果：JSON 文件
- 实验索引和查询：SQLite
- Java 访问：Spring JDBC 或 Spring Data JDBC

选择理由：

- 不需要额外启动数据库服务。
- 便于保存实验快照、提交 Git、复制和复现。
- 后续可以平滑迁移到 PostgreSQL，而不改变领域对象和 API 契约。

第一周不引入 Redis、Kafka、ElasticSearch 或云对象存储。

## 6. 测试方案

- JUnit 5：单元测试
- Spring Boot Test：API 和应用层测试
- MockMvc：REST 接口测试
- 前端组件测试：在时间允许时加入
- 端到端验收：使用固定随机种子运行默认场景，检查关键指标、结果结构和前端展示

最低测试范围：

- 场景配置校验
- 目标状态更新
- 观测生成
- 融合结果的基本正确性
- 两种调度策略能够产生不同且可解释的分配结果
- 固定随机种子下结果可复现
- Agent 工具参数错误能够被拒绝并返回结构化错误

## 7. 工程结构建议

建议采用一个仓库、三个应用目录：

```text
backend/
  pom.xml
  src/main/java/...
  src/test/java/...
agent-service/
  pyproject.toml
  app/...
  tests/...
web/
  package.json
  src/...
docs/
memory-bank/
```

Java 后端、FastAPI 服务和 Vue 前端在开发阶段分别运行，通过项目脚本统一启动。

## 8. 部署与运行

MVP 运行方式：

- 使用 VSCode 打开项目根目录，并使用 VSCode 集成终端执行启动和测试命令。
- 本地启动 Spring Boot 后端。
- 本地启动 FastAPI Agent 服务。
- 本地启动 Vue/Vite 前端开发服务器。
- 通过环境变量配置模型服务地址和 API Key。
- 未配置模型服务时，FastAPI 自动使用规则式 Agent。
- FastAPI 不可用时，Java 仿真和 Vue 的非 Agent 功能仍可运行。

开发环境约定：

- 项目代码、文档、配置和测试统一放在同一个 VSCode 工作区。
- Java、Python 和 Node.js 的依赖通过各自的项目配置文件管理。
- 优先使用 VSCode 集成终端执行 Maven、Python 和 npm/pnpm 命令。
- 可以通过 VSCode 的多终端或任务配置同时运行三个服务。
- 不要求使用独立 IDE；IntelliJ IDEA、PyCharm 等工具不是项目运行前提。

不在第一周处理：

- 云端部署
- 容器编排
- 用户认证
- 多租户
- 生产监控

## 9. 选型风险与应对

### Java 仿真代码量较大

应对：第一版保持模型简单，优先实现稳定的领域接口、二维状态更新和可解释基线；不要一开始追求信号级高保真。

### 前后端同时开发导致范围膨胀

应对：先完成后端默认实验 API 和固定结果 JSON，再开发前端；前端优先展示一个完整默认场景。

### 大模型调用不稳定或不可用

应对：规则式 Agent 和手动实验模式必须独立可用，所有核心仿真不依赖远程模型。

### Java 和 FastAPI 服务边界增加了本地运行复杂度

应对：使用统一启动脚本和 `.env.example`，先让 Java 仿真 API 独立可用，再接入 FastAPI Agent；Agent 服务异常不影响仿真主流程。

### Agent 框架学习成本过高

应对：先自己实现最小工具协议和模型适配接口，再按需要引入 LangChain/LangGraph，不把框架配置当成 Agent 能力本身。

## 10. 后续可升级方向

- 使用 PostgreSQL 替代 SQLite。
- 使用 WebSocket 或 SSE 展示实时仿真进度。
- 引入 LangChain/LangGraph 或其他 Python Agent 编排框架。
- 增加 OpenAPI 文档和契约测试。
- 将实验结果接入向量检索和项目知识库。
- 将融合和调度算法拆分为独立可评估模块。
- 在严格基线和指标体系上加入学习型策略。

## Agent Model Integration

- Python HTTP client: HTTPX, reused for provider calls to avoid unnecessary SDK coupling.
- Configuration: python-dotenv plus environment variables; secrets remain outside Git.
- Supported protocols: OpenAI-compatible Chat Completions and Anthropic Messages.
- Provider adapters: OpenAI, Claude, DeepSeek, Qwen, and Zhipu presets with configurable model and endpoint overrides.
- Deterministic fallback: existing rule planner remains available when no provider key is configured or an external call fails.
# 项目协作规则

> 说明：本文件是作者与 AI 编码助手协作时使用的规则。规则里引用的 `memory-bank/` 是**私有的过程记录
> （架构决策日志、进度日志、设计文档），不随本仓库发布**，因此那些路径在本仓库中不存在。保留本文件是
> 为了展示这套协作方式本身；去掉 memory-bank 相关条目后仍然可用。

## 开发环境

- 使用 VSCode 打开项目根目录。
- Java/Spring Boot 是业务后端和仿真核心。
- Python/FastAPI 是 Agent 外壳和 AI 服务层。
- Vue/TypeScript 是可视化前端。
- 优先使用 VSCode 集成终端执行构建、测试和启动命令。

## 工作流

- 按 `memory-bank/implementation-plan.md` 的顺序一次执行一个步骤。
- 当前步骤验证通过并得到用户确认后，才开始下一步骤。
- 不把 Agent 生成的解释直接当作仿真事实，结论必须能追溯到结构化实验结果。
- 保持 Java、FastAPI 和 Vue 的职责边界，避免复制领域逻辑。
- 每完成一个重大功能或里程碑，更新 `memory-bank/progress.md` 和 `memory-bank/architecture.md`。
- 改完 Agent（提示词、路由、工具、评测用例）后跑 `python -m evals.run_evals`：这是行为回归网，0.4 秒。

## 重要提示

- 写任何代码前必须完整阅读 memory-bank/@architecture.md
- 写任何代码前必须完整阅读 memory-bank/@design-document.md
- 每完成一个重大功能或里程碑后，必须更新 memory-bank/@architecture.md

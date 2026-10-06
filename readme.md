# FusionPilot

一体化雷达/抗干扰系统数字模型与 AI 智能决策体。

## 本地开发

使用 VSCode 打开项目根目录：

```text
FusionPilot
```

项目由三个应用组成：

- `backend/`：Java 17 + Spring Boot，负责领域后端和仿真核心。
- `agent-service/`：Python 3.11 + FastAPI，负责 Agent 外壳和 AI 服务。
- `web/`：Vue 3 + TypeScript + Vite，负责可视化界面。

本地端口约定：

- Java 后端：`8080`
- FastAPI Agent：`8000`
- Vue 前端：`5173`

详细设计、技术栈和实施步骤见 `memory-bank/`。

## 当前状态

当前正在执行实现计划第 1 步：建立项目骨架和本地运行约定。

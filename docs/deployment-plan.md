# FusionPilot 上线部署计划

> 目标：把本地跑通的项目部署到云服务器，让别人能通过公网访问，用于实习简历/作品集展示。
> 当前状态：三个服务在本地 8080（Java 后端）/ 8000（Python Agent）/ 5173（Vue 前端）运行，MySQL 本地 3306。
>
> **可直接执行的东西在 [`deploy/`](../deploy/README.md)**：systemd 单元、Nginx 站点配置、环境变量模板、初始化脚本。
> 本文讲思路与取舍，`deploy/` 是照着抄就能跑的命令。

---

## 一、现状盘点（部署前先看清楚有什么）

| 组件 | 技术栈 | 构建产物 | 启动方式 |
|---|---|---|---|
| 前端 | Vue 3 + Vite + TypeScript | `web/dist/`（静态文件） | `npm run build` 后由 Nginx 托管 |
| 后端 | Java 17 + Spring Boot | `backend/target/fusionpilot-backend-0.1.0-SNAPSHOT.jar` | `java -jar ... --spring.profiles.active=mysql` |
| Agent 服务 | Python 3.11+（本地 3.11） + FastAPI | 源码 + `requirements.txt` | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| 数据库 | MySQL 8.x | — | 本地 `fp_simulation_run` 等表 |

关键注意点（部署时容易踩）：
1. 后端默认读环境变量 `SERVER__PORT`，会覆盖 `--server.port`；上线时要么清掉这个变量，要么显式 `--server.port=8080`。
2. 数据库口令已从环境变量 `FUSIONPILOT_DB_PASSWORD` 读取（`application-mysql.yml` 不再写死默认值），`init.sql` 里是 `CHANGE_ME` 占位；上线务必设置强口令。
3. 前端 API 通过 Vite 代理转发，生产环境要由 Nginx 承担同样的代理职责。
4. 用户上传的 API key 走 `X-Model-Api-Key` 请求头，**不落库**；生产环境必须上 HTTPS，否则明文过网。

---

## 二、部署架构（生产环境）

```
                 ┌─────────────────────────────────────────────┐
  浏览器 ──────► │  Nginx (80/443)                             │
                 │   ├─ /            → web/dist 静态文件         │
                 │   ├─ /api/*       → Java 后端 127.0.0.1:8080 │
                 │   └─ /api/v1/agent/* → Agent 127.0.0.1:8000  │
                 └─────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Java 后端       Agent 服务         MySQL
              (systemd)      (systemd)       (127.0.0.1:3306)
```

- **只暴露 Nginx 的 80/443 端口**，Java / Agent / MySQL 全部只监听 127.0.0.1，不直接对公网开放。
- 前端静态文件交给 Nginx 托管，`/api` 和 `/api/v1/agent` 反向代理到各自服务。

---

## 三、部署方式怎么选：宝塔 / Docker Compose / systemd

先给结论，再说理由。

**结论：这台机器第一次上线，我建议先不装宝塔，按本文第四、五节（选主机 → 分阶段上线步骤）用 systemd + Nginx 走。** 如果中途在
Nginx 配置或 HTTPS 证书上卡住，再装宝塔**只用来管 Nginx 和 MySQL**，三个应用仍然交给 systemd。
宝塔的强项恰好是这套项目最不需要的部分，而它的弱项恰好是这套项目的主体。

### 三种方式对比（针对本项目：Java 常驻 + Python 常驻 + MySQL + 静态前端）

| | 宝塔面板 | Docker Compose | systemd + Nginx（本文后面用的） |
|---|---|---|---|
| 上手成本 | 最低，点界面 | 中，要写一次 compose.yml | 中高，要在服务器上敲命令 |
| 对 Java/Python 常驻服务 | **弱**。有"Java 项目管理器"插件，但不如 systemd 灵活；Python 服务通常仍要自己配 supervisor | 强，一个容器一个服务，天然隔离 | 强，原生支持开机自启、崩溃自动重启 |
| Nginx / HTTPS | **最强**。站点配置图形化、一键申请 Let's Encrypt 证书并自动续期 | 要么容器里跑 Nginx + certbot，要么复用宿主 Nginx | 手写配置 + certbot，一次配好不用再动 |
| MySQL 管理 | 强，带 phpMyAdmin、备份计划 | 容器化，但国内拉镜像慢，要配加速 | 用手上的 mysql 客户端（你现在本机就有） |
| 额外内存占用 | 面板 + 自带的 Nginx/MySQL 版本，约 100～300MB | Docker daemon + 每容器开销，约 150～300MB | 几乎为零 |
| 攻击面 | **面板本身是长期暴露在公网的额外服务**，历史上出过多次未授权访问类漏洞；必须改默认端口、限 IP、强口令 | 只有 Nginx 暴露，但要注意镜像来源 | 只有 Nginx 暴露，最小 |
| 可迁移 / 可版本化 | 差。配置在面板数据库里，不随仓库走，换机器靠手点 | 最好。compose.yml 入库，换机器 `docker compose up -d` | 好。service 文件与 Nginx 配置都可以入库 |
| 简历上怎么说 | "我用面板点的" | "我写了编排文件" | "我配了 systemd 单元和 Nginx 反代" |

### 为什么 2G 内存这件事值得单独说

本项目四个进程的粗略内存占用（启动后稳态，实测数量级，非精确值）：

| 进程 | 占用 |
|---|---|
| Java 后端（默认 JVM 参数） | 400～600 MB |
| MySQL 8 | 300～400 MB |
| Agent 服务（uvicorn 单进程） | 100～200 MB |
| Nginx | 几十 MB |
| **合计** | **约 1.0～1.3 GB** |

2G 机器上再叠一个面板（100～300MB）就接近吃满了，容易在跑仿真的同时被 OOM Killer 杀掉 MySQL 或 Java。
如果确实要用面板，建议 4G 内存，或者把 Java 的堆显式限制一下（`-Xmx512m -Xms128m`）。

### Docker Compose 的现实障碍

对国内机器，Docker 最大的坑不是技术而是**网络**：`docker pull` 从 Docker Hub 拉镜像经常超时，需要配国内
镜像加速器，而加速器本身也时好时坏。其次是 2G 内存下 Docker daemon 的额外开销。**如果你买的是国内机，
我不建议把这套项目做成 Docker。** 香港/海外机器可以考虑。

### 另外一个必须提前知道的事：Agent 能不能出网

Agent 服务要调用用户填的模型 provider。**国内服务器访问 `api.openai.com` / `api.anthropic.com` 通常不通**，
这意味着上线后你或面试官贴 OpenAI 的 key 会直接失败，但贴 **DeepSeek / Qwen / 智谱** 的 key 可以直连。
这不是代码问题，是网络问题——部署到国内机时请在演示说明里写明"通义/DeepSeek/智谱可直接使用"，
或者自己也准备一个可直连的 key 备用。

### 什么时候确实该用宝塔

- 你不熟悉 Linux 命令行，或不想手写 Nginx 配置；
- 需要频繁改站点配置、传文件、看日志，图形界面确实更快；
- 这台机器还要顺便跑别的站（比如 WordPress），面板能省很多事；
- 你要同时管多台机器。

这几种情况下，用宝塔 + 三个服务仍交给 systemd 的**混合方案**，是性价比最高的做法。

---

## 四、云服务器选择

**目的只是实习展示，成本越低越好，不必上高配。**

| 方案 | 优点 | 缺点 | 月成本 |
|---|---|---|---|
| 阿里云/腾讯云 学生机（2核2G） | 国内访问快、有学生认证价、文档全 | 需实名认证，**绑域名要备案** | 约 10～30 元 |
| 轻量应用服务器（2核2G） | 便宜、自带防火墙、开箱即用 | 同上 | 约 24～60 元 |
| 香港/海外 VPS | **免备案**、可立即绑域名 | 国内访问慢、售后弱 | 约 5～10 美元 |

**建议**：如果只是想快速给面试官看 demo，**先买一台香港或海外 VPS 免备案**，用 IP 或临时域名直接访问；等确定要长期维护再回国内走学生机 + 备案。

2核2G 内存对这套项目**够用**：Java 后端约 400～600M、Agent 服务约 100～200M、MySQL 约 300M、Nginx 几十 M，加起来 1.2G 左右，2G 内存刚好。

---

## 五、分阶段上线步骤

### 阶段 0：本地预演（已完成 ✅）

三个服务本地跑通。当前测试规模：Java 45 个、Agent 210 个、Agent 评测集 17 个用例（0.4 秒离线跑完）。

### 阶段 1：服务器环境初始化

```bash
# 1. 更新系统并装基础工具
sudo apt update && sudo apt install -y git openjdk-17-jdk mysql-server nginx python3 python3-venv curl

# 2. 装 Node（用于前端构建，构建完可卸载）
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# 3. 建部署目录和专属用户（不要用 root 跑服务）
sudo mkdir -p /opt/fusionpilot && sudo chown $USER /opt/fusionpilot
```

### 阶段 2：数据库

```bash
# 只需建库建用户（口令与 /opt/fusionpilot/.env 里填的保持一致）
sudo mysql -e "CREATE DATABASE IF NOT EXISTS fusionpilot CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'fusionpilot'@'127.0.0.1' IDENTIFIED BY '<同一个强口令>';
GRANT ALL ON fusionpilot.* TO 'fusionpilot'@'127.0.0.1'; FLUSH PRIVILEGES;"
```

**表由应用自己建。** `spring.sql.init.mode=always` 会让后端在每次启动时执行
`backend/src/main/resources/schema.sql`，里面全是 `create table if not exists`，可重复执行。
新库**不需要**手工导入表结构。

`docs/mysql/migrations/*.sql` 是**升级脚本**——给已经存在的老库补列/补表，全新部署不用跑；
只有把一个旧库接到新版代码上时才按序（001→006）执行。

### 阶段 3：构建并部署三个服务

```bash
cd /opt/fusionpilot

# --- 前端：构建静态文件 ---
cd web && npm install && npm run build   # 产出 dist/

# --- 后端：打包 jar ---
cd ../backend && ./mvnw -DskipTests package   # 或本地打包后 scp 上传 jar

# --- Agent：装依赖 ---
cd ../agent-service && python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 阶段 4：用 systemd 让三个服务开机自启、崩溃自拉起

**现成的单元文件在 `deploy/systemd/`，直接装，不用手写：**

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fusionpilot-backend fusionpilot-agent
```

两个单元都从 `EnvironmentFile=/opt/fusionpilot/.env` 读密钥，所以**单元文件里不含口令**，可以进仓库。
几个容易写错、这份文档自己就写错过一次的点：

- **口令变量名是 `FUSIONPILOT_DB_PASSWORD`**，不是 `SPRING_DATASOURCE_PASSWORD`（本项目不读后者）。
- 必须清掉 `SERVER__PORT`（`Environment="SERVER__PORT="`）——它会覆盖 `--server.port`，残留值会让端口悄悄漂移。
- 2G 内存要给 JVM 限堆：`Environment="JAVA_TOOL_OPTIONS=-Xmx512m -Xms128m"`。
- Agent 用 `JAVA_BASE_URL=http://127.0.0.1:8080`，走回环，不走公网域名。

### 阶段 5：Nginx 反向代理 + 静态托管

```nginx
server {
    listen 80;
    server_name _;

    root /opt/fusionpilot/web/dist;
    index index.html;

    # 前端单页应用：路由回退到 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Java 后端
    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Agent 服务（要放在 /api 之前，避免被长前缀吃掉）
    location /api/v1/agent/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        # SSE 流式必须关缓冲，否则 agent 回复不流式
        proxy_buffering off;
        proxy_read_timeout 120s;
    }
}
```

> 注意：nginx 对**前缀 location 取最长匹配**，与书写顺序无关，所以 `/api/v1/agent/...` 必然命中更长的那条，
> 不会落到 `/api/`。（"要写在前面"是把正则 location 的规则套过来了，纯前缀 location 不成立。）
> 另外 `proxy_pass` **不能带结尾斜杠**：写成 `http://127.0.0.1:8080/` 会把 `/api/` 前缀吃掉，后端全部 404。
> 完整配置见 `deploy/nginx/fusionpilot.conf`，其中还带了 SSE 必须的 `proxy_buffering off`。

### 阶段 6：HTTPS（必须，因为要传 API key）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

如果没有域名，先用 IP 访问（此时 API key 走明文 HTTP，只建议自己测试用）；对外给别人用务必 HTTPS。

---

## 六、上线前安全加固清单（逐项打勾）

- [ ] 设置 `FUSIONPILOT_DB_PASSWORD` 为强口令（`init.sql` 里是 `CHANGE_ME` 占位，本地沿用旧口令需显式设置）
- [x] `application-mysql.yml` 已改为从环境变量 `FUSIONPILOT_DB_PASSWORD` 读取
- [ ] `FUSIONPILOT_RETURN_RESET_TOKEN=false`（mysql profile 默认已是 false，确认没被环境变量覆盖）
- [ ] Java / Agent / MySQL 只监听 127.0.0.1，不对公网开放端口
- [ ] Nginx 配好 HTTPS（API key 走加密通道）
- [ ] 生产环境关掉 `--reload`（Agent 的 uvicorn 热重载只用于开发）
- [ ] 定期备份 MySQL（`mysqldump` + cron）
- [ ] 限制注册接口的滥用（验证码已有，可再加频率限制）
- [ ] 服务器开防火墙（`ufw allow 80,443`，其余拒绝）

---

## 七、给实习展示的建议（比技术本身更重要的部分）

1. **README 写好**：把项目要解决的问题（多目标雷达跟踪的资源调度 + 多源融合 + Agent 协同实验设计）用 3 句话讲清楚，放一张架构图。
2. **录一段 2 分钟演示视频**：注册 → 跑一次仿真 → 看到轨迹图和指标 → 用 Agent 说一句"把目标数改成 5 用卡尔曼跑一次" → 流式看到结果。面试官没时间点开操作，视频最直接。
3. **突出 Agent 工程部分**：这是你找 Agent 开发方向实习的加分项，重点讲——BYOK（自带模型 key）、多轮工具调用循环、确认门、token 级流式、多协议（OpenAI/Anthropic）适配。这些正是企业里 agent 框架在做的事。
4. **把「上线地址 + 演示账号 + 视频」放进简历**，而不是只写"做过一个网站"。

---

## 八、成本小结

| 项 | 一次性 | 月常 |
|---|---|---|
| 服务器（2核2G 轻量/学生机） | 0 | 10～30 元 |
| 域名（可选，.com 首年） | 约 50～70 元 | 约 60～70 元/年 |
| HTTPS 证书（Let's Encrypt） | 0 | 0 |
| **合计** | 约 50～70 元 | 约 15～35 元 |

整体上线成本很低，主要是**时间成本**（首次部署 + 备案/域名）。

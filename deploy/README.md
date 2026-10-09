# 部署到香港 / 海外 VPS

这里是可以直接照着敲的命令。`docs/deployment-plan.md` 讲的是**为什么这么选**（宝塔/Docker/systemd 对比、
内存预算、成本），这里讲**怎么点一下就跑起来**。

免备案是这个方案的全部理由：香港/海外机器绑定域名不需要 ICP 备案，买完就能上。代价是国内访问延迟略高。

---

## 0. 机器要求：**2 核 2G 起，不要买 1 核 1G**

内存是硬门槛，不是建议：

| 进程 | 稳态占用 |
|---|---|
| Java 后端（已限堆 `-Xmx512m`） | 约 500 MB |
| MySQL 8 | 约 300～400 MB |
| Agent 服务（uvicorn 单进程） | 约 100～200 MB |
| Nginx | 几十 MB |
| **合计** | **约 1.0～1.2 GB** |

1 核 1G 装完就剩不下什么了，跑一次仿真就会被 OOM Killer 杀掉 MySQL 或 Java。
磁盘 40G 起步（Maven 产物 + MySQL 数据 + 系统）。月流量 500G～1T 对展示用途绰绰有余
（页面本身很轻，最重的是 README 里那几张截图）。

**香港/海外常见选择**（价格随活动和汇率变动很大，下表只是量级参考，**下单前以官网实时价为准**）：

| 方案 | 配置 | 线路特点 |
|---|---|---|
| 阿里云 香港轻量 | 2核2G / 30Mbps 峰值 / 约 1TB | 国内延迟 30～60ms，BGP；峰值带宽非独享，超流量限速 |
| 腾讯云 香港轻量 | 2核2G / 30Mbps 峰值 / 约 1TB | 与阿里相当，部分时段回程更稳；CPU 主频略低 |
| 轻量类小厂（DMIT / Lightnode / GigsGigsCloud 等） | 常见 1核1G～1核2G | 便宜，但**多为 1G 内存，不建议**；CN2 GIA 线路好但贵 |
| AWS Lightsail 香港 / Vultr 香港 | 2核1G ~ 2核2G | 面向海外用户，国内访问一般，部分 IP 会绕路 |
| 搬瓦工 香港 CN2 GIA | 2核2G | 三网直连、晚高峰最稳，但月付接近 $90，展示用途不划算 |

**建议**：先买**阿里云或腾讯云的香港轻量 2核2G**。大厂控制台干净、能随时重置系统、
可以随时快照回滚，对第一次部署最省心。

**但香港经常买不到**——它是国内用户最抢手的海外节点，售罄、补货慢是常态。如果购买页的地域下拉里
没有香港，按这个顺序退而求其次（都免备案）：

| 备选地域 | 国内访问延迟 | 说明 |
|---|---|---|
| **韩国（首尔）** | 约 50～80ms | **首选替代**。东亚里离国内最近的海外节点，国际出口充足，晚高峰比香港稳 |
| 美国（硅谷） | 约 150～200ms | 到 OpenAI / Anthropic 原生最快最稳，代价是国内访问会感到一点慢 |
| 泰国 / 菲律宾 / 印尼 | 约 70～120ms | 比首尔远，回国线路质量也一般，除非面向当地市场否则不必 |
| 英国 / 德国 / 美国（弗吉尼亚） | 200ms 以上 | 服务欧洲/美东业务的，展示用途不划算 |

> **不要选国内地域（华东/华北等）**：需要 ICP 备案（1～2 周，且得先有域名），而且
> OpenAI / Anthropic 的官方 API **在中国大陆不可用**，你的 Agent 演示会直接受限。

> **一个容易搞错的事实**：OpenAI 官方支持地区列表里**没有中国大陆、香港、澳门**，但有韩国、日本、
> 新加坡、泰国、印尼、菲律宾、美国、英国、德国。所以"香港机器能直连 OpenAI"不成立——香港节点一样
> 打不了 OpenAI 官方 API。想稳用 OpenAI / Anthropic 就选**美国（硅谷）**；想国内访问快又免备案就选
> **韩国（首尔）**。国产模型（DeepSeek / Qwen / 智谱）在任何海外节点都能直连，从亚洲节点访问还更快。

> 一条经验：轻量的"30Mbps"是**峰值**不是独享，晚高峰国内访问可能降到几 Mbps，展示够用，别指望推流。
> 买完先用国内三网 ping/mtr 测一下你的 IP，如果晚高峰延迟从 40ms 跳到 150ms，说明回程绕路了。

---

## 1. 目录与端口规划（后面所有命令都基于它）

| 路径 | 内容 |
|---|---|
| `/opt/fusionpilot/backend/app.jar` | Java 后端（systemd 启动它） |
| `/opt/fusionpilot/agent-service/` | Agent 源码 + `.venv` |
| `/opt/fusionpilot/web/dist/` | 前端静态文件（Nginx 托管） |
| `/opt/fusionpilot/.env` | **密钥只在这里**，`chmod 600`，不进仓库 |
| `/opt/fusionpilot/deploy/` | 本目录，systemd / nginx 配置从这儿装 |

| 端口 | 谁 | 是否对外 |
|---|---|---|
| 80 / 443 | Nginx | ✅ 只暴露这两个 |
| 8080 | Java 后端 | ❌ 只听 127.0.0.1 |
| 8000 | Agent 服务 | ❌ 只听 127.0.0.1 |
| 3306 | MySQL | ❌ 只听 127.0.0.1 |

---

## 2. 服务器初始化

```bash
# 本地：把 deploy/ 传上去
scp -r deploy root@YOUR_HOST:/root/

# 服务器：一条命令装好运行时、建用户、开防火墙
ssh root@YOUR_HOST 'bash /root/deploy/bootstrap.sh'
```

`bootstrap.sh` 装的是**运行时**（JRE 17、MySQL、Nginx、Python、venv），**不装 Node 和 Maven**——
构建在你自己机器上做，2G 的小机器不背这个负担。脚本可重复执行。

> 防火墙那一步是**先放行 SSH 再 enable** 的。顺序反过来会当场把你自己的连接掐掉。

初始化完成后按脚本提示建库（见下一步）。

---

## 3. 本地构建，然后上传产物

在**你自己机器**上（Windows Git Bash 也可以）：

```bash
cd D:/Project/WorkBuddy/2026.10.07/FusionPilot

# 前端
cd web && npm ci && npm run build && cd ..

# 后端（Windows 必须用 mvnw.cmd；在 Git Bash 里跑 ./mvnw 会失败）
cd backend && ./mvnw.cmd -DskipTests package && cd ..

# 自检：两个产物都在
ls -lh backend/target/fusionpilot-backend-0.1.0-SNAPSHOT.jar
ls web/dist/index.html
```

上传（`HOST` 换成你的地址）：

```bash
HOST=root@YOUR_HOST

# Agent 源码 + deploy 配置（排除本地虚拟环境）
tar -czf /tmp/fp-src.tgz --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' agent-service deploy
scp /tmp/fp-src.tgz $HOST:/tmp/
ssh $HOST 'tar -xzf /tmp/fp-src.tgz -C /opt/fusionpilot/'

# Java 产物
scp backend/target/fusionpilot-backend-0.1.0-SNAPSHOT.jar $HOST:/opt/fusionpilot/backend/app.jar

# 前端产物
tar -czf /tmp/fp-web.tgz -C web dist
scp /tmp/fp-web.tgz $HOST:/tmp/
ssh $HOST 'mkdir -p /opt/fusionpilot/web && tar -xzf /tmp/fp-web.tgz -C /opt/fusionpilot/web'

# 统一属主
ssh $HOST 'chown -R fusionpilot:fusionpilot /opt/fusionpilot'
```

---

## 4. 数据库

```bash
ssh root@YOUR_HOST
```

```bash
# 口令自己定一个强口令，记下来，下一步要填进 .env，必须一致
sudo mysql -e "CREATE DATABASE IF NOT EXISTS fusionpilot CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'fusionpilot'@'127.0.0.1' IDENTIFIED BY '你的强口令';
GRANT ALL ON fusionpilot.* TO 'fusionpilot'@'127.0.0.1'; FLUSH PRIVILEGES;"
```

**表不用手建。** 后端启动时会执行 `schema.sql`（`spring.sql.init.mode=always`，全是
`create table if not exists`），新库会自动补齐。

> `docs/mysql/migrations/*.sql` 是**升级脚本**，给已存在的老库补列/补表用的，全新部署不要跑
> ——跑了会报 "Duplicate column name"。

---

## 5. Agent 依赖

```bash
sudo -u fusionpilot python3 -m venv /opt/fusionpilot/agent-service/.venv
sudo -u fusionpilot /opt/fusionpilot/agent-service/.venv/bin/pip install -q --upgrade pip
sudo -u fusionpilot /opt/fusionpilot/agent-service/.venv/bin/pip install -q -r /opt/fusionpilot/agent-service/requirements.txt
```

---

## 6. 环境变量

```bash
cp /opt/fusionpilot/deploy/env.example /opt/fusionpilot/.env
nano /opt/fusionpilot/.env      # 至少改 FUSIONPILOT_DB_PASSWORD，与上一步一致
chown fusionpilot:fusionpilot /opt/fusionpilot/.env
chmod 600 /opt/fusionpilot/.env
```

`env.example` 里每一项都有注释。两个关键点：

- `FUSIONPILOT_DB_PASSWORD` —— **必填**。`application-mysql.yml` 已经没有默认值了，
  不填后端会直接启动失败并报 `could not resolve placeholder 'FUSIONPILOT_DB_PASSWORD'`。
- `FUSIONPILOT_RETURN_RESET_TOKEN=false` —— 保持 false。这个开关为 true 时，
  **任何人对任何邮箱请求重置密码，接口会把重置令牌直接返回在响应里**，等于任意账号可被接管。
  它默认就是 false，确认别被覆盖。

---

## 7. 两个服务交给 systemd

```bash
cp /opt/fusionpilot/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now fusionpilot-backend fusionpilot-agent

# 看状态（Active: active (running) 才算起来）
systemctl status fusionpilot-backend --no-pager
systemctl status fusionpilot-agent --no-pager

# 本机直连自测，此时 Nginx 还没配
curl -s localhost:8080/api/v1/system/health; echo
curl -s localhost:8000/api/v1/agent/health; echo
```

两个端口都应该返回 JSON。**如果 8080 起不来**，直接看日志，报错信息通常一眼就懂：

```bash
journalctl -u fusionpilot-backend -n 40 --no-pager
```

---

## 8. Nginx + 域名 + HTTPS

```bash
cp /opt/fusionpilot/deploy/nginx/fusionpilot.conf /etc/nginx/sites-available/fusionpilot
sed -i 's/your-domain.com/你的域名/' /etc/nginx/sites-available/fusionpilot
ln -sf /etc/nginx/sites-available/fusionpilot /etc/nginx/sites-enabled/fusionpilot
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

此时用 IP 或域名走 HTTP 应该已经能打开首页了。加上证书：

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d 你的域名
```

certbot 会自动改这个配置文件、加 443 段、并配好自动续期。**必须上 HTTPS**——
用户在页面上填的模型 API key 走 `X-Model-Api-Key` 请求头，明文 HTTP 等于把 key 广播出去。

> 还没有域名？先去注册商买个 .com 或 .xyz，把 A 记录指向这台机器的 IP，等解析生效（几分钟）再跑 certbot。
> 只想先看看效果，用 IP + HTTP 也能跑，但别把带 key 的演示发出去。

---

## 9. 验收清单

从**你自己的电脑**（不是服务器）逐条过：

```bash
# 1. 首页静态资源
curl -sI http://你的域名/ | head -1                     # 200

# 2. 后端经 Nginx
curl -s http://你的域名/api/v1/system/health; echo       # JSON

# 3. Agent 经 Nginx（这条走的是 8000，验证 /api/v1/agent/ 路由对了）
curl -s http://你的域名/api/v1/agent/health; echo        # JSON

# 4. 内部端口没有对公网开放（都应该超时或被拒绝）
curl -s --max-time 3 http://你的域名:8080/ || echo "8080 已封闭 ✓"
curl -s --max-time 3 http://你的域名:8000/ || echo "8000 已封闭 ✓"
```

然后在浏览器里手工过一遍：

1. 注册一个账号（要答算术验证码）→ 能进实验室。
2. 工作台改参数 → 跑一次 → 看到轨迹图和指标。
3. Agent 页贴一个模型 key（**智谱 `glm-4-flash` 免费**）→ 问一句「什么是卡尔曼滤波」。
4. **重点看第 3 步的回复是逐字出现还是整段蹦出来**——逐字才对。
   整段蹦出来说明 Nginx 把 SSE 缓冲了，检查 `proxy_buffering off;` 是否在
   `/api/v1/agent/` 那一段里。

---

## 10. 以后怎么更新

改了代码要重新上线时，只重复第 3 步的构建上传，再加一次重启：

```bash
# 本地：重新构建并上传（同第 3 步）
# 服务器：
systemctl restart fusionpilot-backend fusionpilot-agent
```

只改了前端就不必重启服务：

```bash
# 上传新的 web/dist 后
systemctl reload nginx      # 其实是可选的，静态文件是实时读的
```

---

## 11. 排障对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| `502 Bad Gateway` | 服务没起来，或端口不是 8080/8000 | `systemctl status` + `journalctl -u` |
| 首页 404 / 空白，但 `/api` 正常 | Nginx `root` 指向不对 | 确认 `/opt/fusionpilot/web/dist/index.html` 存在 |
| 刷新子路由 404 | 少了 SPA 回退 | `try_files $uri $uri/ /index.html;`（用 `deploy/` 里这份就不会漏） |
| Agent 回复整段蹦出 | Nginx 缓冲了 SSE | `/api/v1/agent/` 段里要有 `proxy_buffering off;` |
| 后端启动报 `could not resolve placeholder 'FUSIONPILOT_DB_PASSWORD'` | `.env` 没配、没被读到、或权限不对 | `chmod 600` + `chown fusionpilot`，`systemctl show -p EnvironmentFiles fusionpilot-backend` |
| 后端报 `Access denied for user 'fusionpilot'` | 建库口令与 `.env` 不一致 | 改成一致，或 `ALTER USER` |
| 上传数据集返回 413 | 请求体超限 | 配置里已设 `client_max_body_size 110m` |
| 跑仿真时 MySQL/Java 被杀 | 没限 JVM 堆，2G 被吃满 | 确认单元里有 `JAVA_TOOL_OPTIONS=-Xmx512m` |
| Agent 回答标着 `produced_by: rule` | 没贴模型 key | 在 Agent 页模型栏贴自己的 key（服务端不配 key） |
| 国内访问特别慢 / 晚高峰丢包 | 线路问题，非配置问题 | 换 CN2 GIA 线路的机器，或接受它 |
| 贴 OpenAI / Anthropic 的 key 报连接失败 | **香港机器打不了**（香港不在 OpenAI 支持地区列表内）；韩国/东南亚/美国/欧洲节点可以。仍失败再查 DNS/出网 | 换 DeepSeek / Qwen / 智谱 的 key 试 |

---

## 12. 安全清单（对着打勾）

- [ ] `/opt/fusionpilot/.env` 是 `600`，且**没有进仓库**（`.gitignore` 已忽略 `.env`）
- [ ] `FUSIONPILOT_RETURN_RESET_TOKEN=false`
- [ ] 只有 80/443 对外；8080 / 8000 / 3306 只听 127.0.0.1（`ufw status` + `ss -lntp`）
- [ ] 已配 HTTPS，并且用 https 打开过一次
- [ ] MySQL root 没有弱口令（Ubuntu 默认走 socket 认证，别去改成密码登录）
- [ ] 定期备份：`mysqldump -u fusionpilot -p fusionpilot > /root/fp-$(date +%F).sql`
- [ ] 知道自己随时可以在云控制台**重置系统盘**从零再来（第一次部署一定会弄脏一次）

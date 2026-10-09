# 运维手册（单人维护）

面向"一个人维护一台服务器"的场景：日常怎么看数据、怎么备份、哪些红线不能碰，以及从域名到 HTTPS 的完整清单。

命令里的 `<服务器IP>` / `<你的私钥>` 请替换成实际值；本文不写死具体 IP。

---

## 一、数据库：不要开放 3306，用 SSH 隧道

**先说结论：不要为了方便用图形化客户端，把 3306 开到公网。** MySQL 现在只监听 `127.0.0.1`，
这是保护而不是限制——公网上的 3306 平均几小时内就会被扫描到并开始被暴力破解。下面两条路都不需要动它。

### 先解释一个必然踩到的坑：root 从客户端连不上

Ubuntu 的 MySQL 安装把 `root@localhost` 设成了 **`auth_socket`** 插件，意思是：
**只有从服务器本机的 shell、以 root 身份，才能免密进入**。任何 TCP 连接（包括你在 DataGrip 里
用 root + 口令）都会直接失败，而且报错不会告诉你原因。这是默认加固，**不要改它**。
需要管理权限时，ssh 登录服务器后用 `mysql` 命令即可。

### 路径 A：DataGrip 内置 SSH 隧道（推荐）

**1. 取数据库口令**（在你自己电脑的终端里执行，口令只出现在你屏幕上）：

```bash
ssh -i ~/.ssh/<你的私钥> root@<服务器IP> 'grep ^FUSIONPILOT_DB_PASSWORD= /opt/fusionpilot/.env'
```

**2. 新建数据源**：DataGrip → `+` → Data Source → **MySQL**，在 `General` 页填：

| 字段 | 值 |
|---|---|
| Host | `127.0.0.1` |
| Port | `3306` |
| Database | `fusionpilot` |
| User | `fusionpilot` |
| Password | 上一步取到的值 |

**3. 切到 `SSH/SSL` 页**，勾选 **Use SSH tunnel**：

| 字段 | 值 |
|---|---|
| Host | `<服务器IP>` |
| Port | `22` |
| User | `root` |
| Auth type | `Key pair` |
| Private key file | `C:\Users\<你>\.ssh\id_ed25519` |

**4. 点 Test Connection**。

两个已知报错及处理：

- **SSH 隧道报密钥格式错误**：DataGrip 内置的隧道实现偶尔不支持 OpenSSH 格式的 ed25519 私钥。
  把 SSH 配置里的 `Client` 从 `Built-in` 改成 `Native`（改用系统 ssh），或直接走下面的路径 B。
- **报 `Public Key Retrieval is not allowed`**：到 `Advanced` 页把 `allowPublicKeyRetrieval` 设为 `true`。
  MySQL 8 的 `caching_sha2_password` 在非 TLS 连接下需要它完成 RSA 密钥交换。

**怎么确认自己连的到底是哪个库** —— 这是最常见的"连不上"原因，一条命令就能判：

```sql
SELECT CURRENT_USER();
```

| 结果 | 意味着 |
|---|---|
| `fusionpilot@`**`localhost`** | **你连的是本机开发库**，SSH 隧道没生效 |
| `fusionpilot@`**`127.0.0.1`** | 连的是线上库，正确 |

两个库的账号定义本来就不同（本机是 `@localhost`，线上是 `@127.0.0.1`），所以**报错里的 host 会直接告诉你连到了哪**：
看到 `Access denied for user 'fusionpilot'@'localhost'` 就是隧道没生效、流量没出你的电脑，
不是密码错。同理，别把线上的口令填进本机库的连接 —— 两边口令不一样。

**怎么确认自己连的到底是哪个库** —— 这是最常见的"连不上"原因，一条命令就能判：

```sql
SELECT CURRENT_USER();
```

| 结果 | 意味着 |
|---|---|
| `fusionpilot@`**`localhost`** | **你连的是本机开发库**，SSH 隧道没生效 |
| `fusionpilot@`**`127.0.0.1`** | 连的是线上库，正确 |

两个库的账号定义本来就不同（本机是 `@localhost`，线上是 `@127.0.0.1`），所以**报错里的 host 会直接告诉你连到了哪**：
看到 `Access denied for user 'fusionpilot'@'localhost'` 就是隧道没生效、流量没出你的电脑，
不是密码错。同理，别把线上的口令填进本机库的连接 —— 两边口令不一样。

### 路径 B：手工端口转发（最稳，不依赖客户端的 SSH 功能）

开一个终端挂着不动：

```bash
ssh -N -L 3307:127.0.0.1:3306 -i ~/.ssh/<你的私钥> root@<服务器IP>
```

然后 DataGrip 里当成**普通本地连接**填：Host `127.0.0.1`、Port **`3307`**，其余同上，`SSH/SSL` 页不用配。
隧道关掉就连不上（这正是想要的效果），用完在那个终端按 Ctrl-C。

### 可选：单独的运维账号

`fusionpilot` 这个账号已经拥有整个 `fusionpilot` 库的全部权限，日常看数据、改数据完全够用。
如果希望有一个独立可回收的运维账号，**在服务器上**以 root 身份执行：

```sql
CREATE USER 'ops'@'127.0.0.1' IDENTIFIED BY '<强口令>';
GRANT ALL PRIVILEGES ON fusionpilot.* TO 'ops'@'127.0.0.1';
```

> host 写 `127.0.0.1` 是对的：只有经隧道进来时，来源地址才是 `127.0.0.1`。

---

## 二、你会用到的几条 SQL

```sql
-- 有哪些用户（谁注册过）
SELECT user_id, username, email, display_name, role, status, created_at
FROM fp_user ORDER BY user_id DESC;

-- 某个用户的会话与运行记录
SELECT session_id, status, updated_at FROM fp_agent_session
WHERE user_id = ? ORDER BY updated_at DESC;
SELECT run_id, scenario_name, saved_at FROM fp_simulation_run
WHERE user_id = ? ORDER BY created_at DESC;

-- 长期记忆（每个用户一行，内容由模型生成）
SELECT user_id, LEFT(memory_text, 200) AS preview, updated_at FROM fp_agent_memory;

-- 最近的登录会话
SELECT * FROM fp_user_session ORDER BY created_at DESC LIMIT 20;
```

**删除一个用户**（外键会级联清理他的会话、运行记录、记忆）：

```sql
DELETE FROM fp_user WHERE username = '<name>';
```

删之前先 `SELECT` 确认是哪一行。**没有撤销**，在生产库上删之前先做一次备份（见下一节）。

两个容易困惑的点：

- `GET /api/v1/simulations/history` 只列**用户显式保存过**的运行，每用户上限 10 条（`savedLimit`）。
  运行数比"跑过的次数"少是正常的。
- `fp_agent_session` 存的是整段会话的 JSON 快照，字段很长。在 DataGrip 里可读，但别指望排版好看。

---

### 用户与登录数据在哪，以及两件你做不到的事

| 表 | 存什么 |
|---|---|
| `fp_user` | 账号本身：`username` / `email` / `password_hash` / `role` / `status` / `last_login_at` |
| `fp_user_session` | 登录会话：`token_hash` / `expires_at` / `revoked_at` |
| `fp_password_reset_token` | 重置令牌：`token_hash` / `expires_at` / `used_at` |

**先说清楚两件做不到的事，免得白找：**

- **看不到任何人的密码。** `password_hash` 是 **BCrypt 单向哈希**（`$2a$` 开头、60 字符），
  设计上不可逆。能做的只有"重置"，没有"查看"。任何号称能从库里读出密码的做法都是错的。
- **抓不到可用的登录令牌。** `token_hash` 是令牌的 **SHA-256**，不是令牌本身。
  所以你无法从库里复制一条会话去冒充别人 —— 这是刻意设计的。

这两点是这个项目的好属性，不是缺陷。

**常见操作分两类，用对地方：**

- **查数据** → DataGrip / SQL（见上一节）。
- **"禁用某人 / 把他踢下线" → 用管理接口**，因为它会**连带吊销该用户全部会话**，
  手写 SQL 很容易只改了状态忘了踢会话：

```bash
TOKEN="<你自己的 access token>"
BASE="http://<你的域名或IP>"

# 列出所有用户
curl -H "Authorization: Bearer $TOKEN" $BASE/api/v1/admin/users

# 禁用（INACTIVE 会同时吊销其全部会话）
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"status":"INACTIVE"}' $BASE/api/v1/admin/users/<userId>/status

# 只踢下线，不禁用
curl -X POST -H "Authorization: Bearer $TOKEN" $BASE/api/v1/admin/users/<userId>/revoke-sessions
```

状态只有 `ACTIVE` / `INACTIVE` 两种。这些接口要求调用者是 **ADMIN**，而新注册的账号一律是 `USER`，
所以需要**先给自己提一次权**（一次性操作，在服务器上或 DataGrip 里执行）：

```sql
UPDATE fp_user SET role = 'ADMIN' WHERE username = '<你自己的用户名>';
```

改完**退出重新登录一次**，再用新的 token 调管理接口。

> DataGrip 自带 HTTP Client，这些请求可以直接在它里面发，不必开终端。

> 小坑：在 Windows 的 Git Bash 里跑 `mysql` 命令行客户端时，**中文列名会显示成乱码**——
> 那是终端编码问题，不是数据库问题。DataGrip 里不会出现。

## 三、备份

**一次性导出**（在你自己的电脑上执行，结果直接落到本地，天然"离开服务器"）：

```bash
ssh -i ~/.ssh/<你的私钥> root@<服务器IP> \
  'mysqldump --single-transaction --default-character-set=utf8mb4 fusionpilot' \
  > fusionpilot-$(date +%F).sql
```

`--single-transaction` 让导出不锁表（InnoDB），线上跑着也能安全备份。

**定时备份**（在服务器上，每天 3 点，保留最近 14 天）：

```bash
mkdir -p /var/backups/fusionpilot
cat > /etc/cron.d/fusionpilot-backup <<'EOF'
0 3 * * * root mysqldump --single-transaction --default-character-set=utf8mb4 fusionpilot > /var/backups/fusionpilot/$(date +\%F).sql 2>/dev/null; find /var/backups/fusionpilot -name '*.sql' -mtime +14 -delete
EOF
```

**恢复**：

```bash
mysql fusionpilot < fusionpilot-2026-10-09.sql
```

> 注意：定时备份落在**同一台机器的系统盘**上。磁盘坏了、机器被重置，备份跟着一起没。
> 真正的备份必须离开这台机器——至少每周手动下载一次。

---

## 四、安全红线

- **不要**把 3306 加进云防火墙/安全组对外放行。确实需要临时直连时，只放行**你自己的公网 IP**，用完立刻删。
- **不要**把 `.env` 里的口令贴到聊天、issue、截图或提交里。要取就 ssh 上去 `grep`。
- **不要**为了让客户端连得上，就把 `root` 改成密码登录。
- 改数据库结构（加表/加列）时，**必须同时改 `backend/src/main/resources/schema.sql`**。
  后端启动只执行这个文件；漏改的话，当前库看似正常，但下次全新部署会缺对象——
  历史上就漏过一张表，症状是功能静默失效而不是报错。

---

## 五、域名 → HTTPS 清单

1. **买域名**。推荐 `.com`。**看续费价，不是首年价**：`.com` 首年常促销到 35 元左右，
   续费约 79～95 元/年；`.cn` 续费约 40 元/年；`.xyz` / `.top` 首年很便宜但续费会涨。
2. **完成实名认证**。国内注册商强制要求；未实名的域名会被 serverHold，**解析不生效**。
   实名一般几分钟到 1～2 天，所以别等到要用才做。
3. **加解析记录**（域名服务商的 DNS 控制台）：

   | 类型 | 主机记录 | 记录值 |
   |---|---|---|
   | A | `@` | 服务器公网 IP |
   | A | `www` | 服务器公网 IP |

4. **等解析生效**（几分钟到几十分钟）。验证：`nslookup 你的域名` 应返回服务器 IP。
   **解析没生效前不要去申请证书**，会失败。
5. **改 nginx 的 server_name**：把 `deploy/nginx/fusionpilot.conf` 里的 `server_name _;`
   改成 `server_name 你的域名 www.你的域名;`，然后：

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

6. **申请证书**（会自动改 nginx、加 443 段、并配置自动续期）：

   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d 你的域名 -d www.你的域名
   ```

7. **验证**：浏览器打开 `https://你的域名` 证书有效；`curl -I http://你的域名` 应 301 跳到 https。

> **域名一定要开自动续费。** 域名过期后被抢注，基本要不回来。

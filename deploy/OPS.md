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
- **同一页的「使用 SSL」要取消勾选。** SSH 隧道已经把整条链路加密了；再叠一层 MySQL SSL，
  会因为服务端用的是自签证书、而客户端默认拿系统/IDE 的 CA 去校验，直接连不上。
  **两个勾只留「使用 SSH 隧道」那一个。**

**关于「内省级别」（Introspection level）——不用管**

DataGrip 连上后弹出「为 xxx 选择的内省级别」，是它问你要把数据库元数据抓多少层，**与连接是否成功无关**：

| 级别 | 内容 |
|---|---|
| 1 | 只抓库和 schema，不抓表 |
| 2 | 抓库 / schema / 对象，**跳过系统 schema**（`information_schema`、`performance_schema`、`mysql`、`sys`） |
| 3（默认） | 全部抓，包括系统 schema |

默认的 **3** 就够用。唯一差别是树里会多出 `information_schema` / `performance_schema` 这些噪音目录，
**不影响任何查询**。想清静可以在数据源属性 → `Options` → `Introspection` 里改成 2。
**注意级别 2 会连 `mysql` 库一起隐藏**，将来要翻系统表时还得改回来。

**连不上时，先看 `using password`，别看用户名里的 host**

认证**失败**时，MySQL 报的是**客户端主机名**（`127.0.0.1` 会被反解成 `localhost`），**不是**匹配到的账号。
所以 `Access denied for user 'x'@'localhost'` 这句**本地连接和经隧道连线上都会原样出现**，
**不能**拿它判断连到了哪个库 —— 这条最容易反着推错（本人就推错过一次）。

真正的信号是括号里那半句：

| 报错里的 `using password:` | 含义 | 处理 |
|---|---|---|
| **`NO`** | **客户端一个密码都没发** | 客户端没拿到口令：字段没保存、凭据存储失效、或弹框被跳过。重新填并保存；把「保存」改成 `永不` 让它每次弹框，是最可靠的定性实验 |
| `YES` | 密码发出去了但不对 | 口令本身错（长度/字符/带了首尾空格），或这个口令不属于你所连的库 |

**要判断连到了哪个库，只能等连上之后**：

```sql
SELECT CURRENT_USER();   -- 显示的是"匹配到的账号"，这句才可信
```

| 结果 | 意味着 |
|---|---|
| `fusionpilot@`**`127.0.0.1`** | 连的是**线上**库，正确 |
| `fusionpilot@`**`localhost`** | 连的是**本机**开发库，隧道没生效 |

两个库的账号定义本来就不同（本机 `@localhost`、线上 `@127.0.0.1`），所以**连接成功后**这一句能一眼分辨。
同理，别把线上的口令填进本机库的连接 —— 两边口令不一样。

**连不上时，先看 `using password`，别看用户名里的 host**

认证**失败**时，MySQL 报的是**客户端主机名**（`127.0.0.1` 会被反解成 `localhost`），**不是**匹配到的账号。
所以 `Access denied for user 'x'@'localhost'` 这句**本地连接和经隧道连线上都会原样出现**，
**不能**拿它判断连到了哪个库 —— 这条最容易反着推错（本人就推错过一次）。

真正的信号是括号里那半句：

| 报错里的 `using password:` | 含义 | 处理 |
|---|---|---|
| **`NO`** | **客户端一个密码都没发** | 客户端没拿到口令：字段没保存、凭据存储失效、或弹框被跳过。重新填并保存；把「保存」改成 `永不` 让它每次弹框，是最可靠的定性实验 |
| `YES` | 密码发出去了但不对 | 口令本身错（长度/字符/带了首尾空格），或这个口令不属于你所连的库 |

**要判断连到了哪个库，只能等连上之后**：

```sql
SELECT CURRENT_USER();   -- 显示的是"匹配到的账号"，这句才可信
```

| 结果 | 意味着 |
|---|---|
| `fusionpilot@`**`127.0.0.1`** | 连的是**线上**库，正确 |
| `fusionpilot@`**`localhost`** | 连的是**本机**开发库，隧道没生效 |

两个库的账号定义本来就不同（本机 `@localhost`、线上 `@127.0.0.1`），所以**连接成功后**这一句能一眼分辨。
同理，别把线上的口令填进本机库的连接 —— 两边口令不一样。

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

---

### 发布一条系统消息（网站顶栏的铃铛）

网页顶栏那个铃铛里的内容就是这张表，**发版公告、维护通知都从这里发**。

| 表 | 存什么 |
|---|---|
| `fp_system_message` | 消息本体：`title` / `body` / `version` / `level` / `published_at` |
| `fp_system_message_read` | 已读回执：每个 (消息, 用户) 一行，知道谁读过 |

**最省事的发法——直接在 DataGrip 里 INSERT 一行，前端不用重新部署：**

```sql
INSERT INTO fp_system_message (title, body, version, level)
VALUES ('融合算法对比新增卡尔曼滤波',
        '对比页现在支持三种融合方法同屏比较。',
        '0.3.0',
        'UPDATE');
```

`version` 和 `level` 可以不写（`NULL` / 默认 `INFO`）。`level` 三选一，决定标签样式：

| `level` | 前端显示 |
|---|---|
| `INFO`（默认） | 「通知」 |
| `UPDATE` | 「版本更新」 |
| `WARNING` | 「重要」（琥珀色，用于维护/故障） |

**想定时发布**：把 `published_at` 写成将来的时间，**到点之前任何人都看不到**，到点自动出现。
写入时**不用带时区**，按服务器本地时间（CST）理解：

```sql
INSERT INTO fp_system_message (title, body, version, level, published_at)
VALUES ('计划维护', '本周日 02:00–03:00 停机维护。', NULL, 'WARNING', '2026-10-18 09:00:00');
```

**发错了就改或删**（`fp_system_message_read` 会跟着级联删掉，已读状态一起没）：

```sql
UPDATE fp_system_message SET body = '……' WHERE message_id = ?;
DELETE FROM fp_system_message WHERE message_id = ?;
```

**不写 SQL 的替代方案**是调接口（需要 ADMIN，提权方式同上）：

```bash
BASE="https://<你的域名>"
# 1. 取 token（登录接口要过一道算术验证码，见 /api/v1/auth/captcha）
TOKEN='<登录拿到的 accessToken>'

# 2. 发布，返回新消息的 messageId
curl -s -X POST "$BASE/api/v1/system/messages" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"版本更新","body":"……","version":"0.3.0","level":"UPDATE"}'

# 3. 看看发布后的列表（不带 token 也看得到，只是 read 恒为 false）
curl -s "$BASE/api/v1/system/messages"
```

**红点的机制**，看数据就能明白：

- `GET /api/v1/system/messages` **不需要登录**——铃铛在首页（未登录）也要能用。
- 登录用户的 `read` 由 `fp_system_message_read` 决定，**换设备、换浏览器都保持一致**。
- 未登录访客没有回执可记，已读状态存在浏览器本地，所以**新访客/换了浏览器会再看到红点**——
  这是设计如此，不是 bug。
- 消息是**广播**：一行对所有人生效，没有"给某个用户单独发消息"的能力。

## 三、备份

### 已经在跑的那套（systemd 定时器）

```bash
systemctl list-timers fusionpilot-backup.timer    # 下次什么时候跑
systemctl start fusionpilot-backup.service        # 现在立刻备份一次（升级前手动跑很合适）
journalctl -u fusionpilot-backup.service -n 30    # 上次跑的完整日志
cat /var/backups/fusionpilot/last-success.txt     # 上次成功的时间、大小、表数
ls -lh /var/backups/fusionpilot/                  # 现有备份文件
```

- 每天 **03:30**（±15 分钟随机抖动）跑一次，保留最近 **14 份**
- 连不上数据库、磁盘写满、dump 被截断，**都会让这次备份判为失败**并返回非 0
- 文件权限 600、目录归 root；脚本是 700，不接受任何参数

**脚本不是"跑完就完事"**，它会验三件事，任何一条不过就整体失败：

1. `gzip -t` 能解压（挡住磁盘写满导致的半截文件）
2. 内容结尾有 `Dump completed`（挡住被中断的 dump）
3. 解压后 `CREATE TABLE` 的数量 ≥ 库里的表数（挡住"成功但内容是空的"）

**为什么重要**：`mysqldump` 对空 schema 也会返回 0，所以只看退出码的备份脚本可以在
"什么都没备份到"的情况下一直报成功。

### 失败怎么让你知道（以及它的局限）

| 渠道 | 什么时候能看到 |
|---|---|
| 失败标记 `/var/backups/fusionpilot/LAST_BACKUP_FAILED`（含时间与原因） | 主动去看 |
| `journalctl -u fusionpilot-backup.service` | 主动去看 |
| **`./deploy/deploy.sh` 每次部署时会检查并高亮提醒** | 你部署时 |
| 备份超过 2 天没成功 → 同样会在部署时提醒 | 你部署时 |

**要说清楚**：这些都需要"你去看了"才会看到。**这不是及时推送**。要做到"半夜失败、早上手机响"，
需要一个外部通道（邮件 SMTP、企业微信/钉钉机器人、或者云厂商的短信告警）——那要额外配置，
现在没做。如果你想要，告诉我用哪种，我接上。

### 恢复

```bash
# 在服务器上（会覆盖当前数据，先确认这是你要的那一份）
zcat /var/backups/fusionpilot/fusionpilot-2026-10-11.sql.gz | mysql fusionpilot
```

**验证备份能不能用，最靠谱的办法是真恢复一次**（到一个临时库，不碰生产）：

```bash
mysql -e 'CREATE DATABASE fusionpilot_restore_test CHARACTER SET utf8mb4;'
zcat /var/backups/fusionpilot/fusionpilot-2026-10-11.sql.gz | mysql fusionpilot_restore_test
mysql -N -B -e "select count(*) from information_schema.tables where table_schema='fusionpilot_restore_test'"
mysql -e 'DROP DATABASE fusionpilot_restore_test;'
```

### 最重要的一条：备份必须离开这台机器

**同机备份等于没有备份**——机器丢了、磁盘坏了、误删了，两者一起没。
定时任务只负责"在服务器上生成"，**把它拉走需要你在自己电脑上做**：

```bash
# 在本地执行，把服务器上的备份同步到本机目录
mkdir -p ~/fusionpilot-backups
scp -i ~/.ssh/<你的私钥> root@<服务器IP>:'/var/backups/fusionpilot/*.sql.gz' ~/fusionpilot-backups/
```

（更好的做法是传到对象存储或另一台机器；`scp` 到本地至少保证"服务器没了数据还在你手上"。
另外注意：**拉到本地只是备份，本机磁盘挂了同样会没** —— 重要的东西建议再往网盘/对象存储放一份。）

### 临时手动导出一份（不想用脚本时）

```bash
ssh -i ~/.ssh/<你的私钥> root@<服务器IP> \
  'mysqldump --single-transaction --default-character-set=utf8mb4 fusionpilot' \
  > fusionpilot-$(date +%F).sql
```

`--single-transaction` 让导出不锁表（InnoDB），线上跑着也能安全备份。

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
   **解析没生效前不要去申请证书**，会失败。见下面「解析迟迟不生效」那一节。
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

   想收到证书到期提醒邮件就带上 `-m 你的邮箱`（或用 `--register-unsafely-without-email`
   跳过）。**不带邮箱不影响续期**，只是收不到警告信。事后补邮箱：

   ```bash
   sudo certbot update_account --email 你的邮箱
   ```

7. **验证**：浏览器打开 `https://你的域名` 证书有效；`curl -I http://你的域名` 应 301 跳到 https。

> **域名一定要开自动续费。** 域名过期后被抢注，基本要不回来。

### 解析迟迟不生效：先分清「配置错」和「没委派」

国内注册商改了 NS / 刚买的新域名，常见这样一个陷阱：

- 在注册商 DNS 控制台记录加好了，**直连它自家的权威 DNS 也能查到**：
  `nslookup 你的域名 <权威NS，如 dns13.hichina.com>`
- 但公共 DNS 一律返回 `NXDOMAIN`（不存在）：
  `nslookup 你的域名 223.5.5.5` / `nslookup 你的域名 8.8.8.8`

**这不是你配错了，是注册局的 NS 委派还没生效**——`.cn` / `.com` 这类需要把「这个域名的权威 NS 是谁」
从注册商同步到注册局，`.cn` 通常几小时、最慢次日。
**判据：权威能查到 = 配置对，只剩等。** 这时候什么都别改，改了反而乱。

中间怎么盯进度（不必一直手动查）：跑个定时任务每小时 `nslookup`，生效了通知自己。

### 走完这一遍之后，你会拥有（对照检查用）

- 域名 `<你的域名>`，A 记录 `@` / `www` → `<服务器公网 IP>`
- 证书由 **Let's Encrypt** 签发，落在 `/etc/letsencrypt/live/<你的域名>/`，**有效期 90 天**
- 续期是全自动的：装 certbot 时会创建 **`certbot.timer`**，systemd 每 12 小时跑一次，
  只在剩余不足 30 天时真正续。查状态：

  ```bash
  systemctl list-timers certbot.timer --no-pager
  sudo certbot renew --dry-run        # 演练一次续期，验证配置没坏
  ```

- 改 nginx 前的配置备份自己留一份（`cp /etc/nginx/sites-available/<站点> /root/<站点>.nginx.bak`），
  回滚就是 cp 回去再 reload
- certbot 在 80 端口那个 server 块里加了「按 host 301 到 https」，并在末尾 `return 404`，
  这样别的域名扫到这台机器不会被当成正常站点——**这是 certbot 的正常产物，别删**
- 证书签发后自测（本地执行）：

  ```bash
  curl -sI  http://<你的域名>/  | head -1    # 301，Location: https://<你的域名>/
  curl -sI  https://<你的域名>/ | head -1    # 200
  curl -sI  https://<你的域名>/api/v1/system/health | head -1   # 200，证明反代通
  ```

  > 用 `-I`（HEAD）而不是 `-o /dev/null`：Windows 的 Git Bash 里 `curl -o /dev/null` 会把
  > `/dev/null` 当成路径交给原生 curl.exe，**退出码恒为 23**（虽然 `-w` 输出的码是对的）。
  > 放进 `&&` 串里会莫名其妙地中断。

---

## 六、容量与内存边界（实测数据）

这台 2 核 2G 的机器**注册人数不是瓶颈**：一行账号约 1KB，磁盘还剩 30G 以上，几十万账号都放得下。
真正的边界是**仿真结果占用的 JVM 堆**。

### 实测（线上实况 + 本机同参数测堆）

| 项 | 值 |
|---|---|
| 内存 | 总 1613MB，可用约 739MB |
| 应用栈常驻 | java 198MB + mysqld 180MB + uvicorn 94MB |
| 系统与云厂商组件 | 约 200MB（AliYunDun / fwupd / tuned / multipathd …） |
| 磁盘 | 40G，用 16% |
| JVM 堆 | `-Xmx512m`，空载约 20MB |

单条仿真结果在堆里的**实测**占用（用 `jcmd GC.run` 强制 GC 后测保留量）：

| 规模 | 单次耗时 | 单条结果 |
|---|---|---|
| 3 目标 × 100 步（默认） | 0.53s | **2.4 MB** |
| 20 目标 × 500 步 | 3.55s | **30.5 MB** |
| 50 目标 × 1000 步 | 6.39s | **147.6 MB** |

### 两个已经加上的保护

1. **结果缓存在 `SimulationResultStore` 里是有限的**：按估算字节最多 192MB 的 LRU。
   超出的部分会被淘汰——**淘汰不会丢数据**，因为每条结果同时也写在数据库里，
   `find()` 读不到内存会回退去查库。单条结果如果自己就超过整个预算，直接不进缓存。
2. **单次运行有规模上限**：`targetCount × simulationSteps ≤ 50000`，超了在接口校验层就被拒（返回 400）。
   在这之前两个字段各自的上限允许 50 × 10000 = 500000，实测约需 1.5GB 堆 —— 会直接把进程打死。

### 想跑得更大怎么办

- 上限 50000 对应约 150MB 单条结果，在 512MB 堆上已经是"能跑但吃紧"。
- 想放宽就得同时加大 `-Xmx`（改 systemd 单元里的 `JAVA_TOOL_OPTIONS`）并确认机器内存，
  **但 1.6G 的机器没有多少空间**：可用只有 739MB。
- 真要跑大规模场景，正确做法是**换更大的机器**，而不是在这台上调参数。

### 这条上限对 MySQL 有一个隐含要求

整个结果**还会以一条 JSON 写进 `fp_simulation_run.result_json`**。50000 规模对应约 **27MB** 的
JSON，所以数据库必须有 `max_allowed_packet ≥ 32M`：

```bash
mysql -N -B -e 'select @@max_allowed_packet'      # 线上是 67108864（64M，MySQL 8 默认值）✓
```

**线上没问题**（用的就是默认值 64M）。但**本机 Windows 上的 MySQL 实测是 4M**，所以在本地跑大场景
会在"保存结果"这一步失败：

```
PacketTooBigException: Packet for query is too large (27,239,074 > 4,194,304)
```

**这个报错的表现很迷惑**：仿真本身其实跑完了，只在落库时炸，前端只看到一个 500。
要在本地跑大场景，改 `my.ini` 加上 `max_allowed_packet=64M` 再重启 MySQL 即可；
不改也不影响日常开发，默认场景（3×100）远低于这个限制。

## 七、改完代码怎么让线上更新

**先说结论：不会自动同步。** 线上跑的是服务器上的那份构建产物，你在本地改代码，
**除非重新构建并上传，线上永远是旧的**。所以"像很多网站那样持续更新"这件事，
全靠下面这条命令。

### 一条命令的事

```bash
cd <仓库目录>
./deploy/deploy.sh --host root@<服务器IP> --domain <你的域名>
```

它按顺序做完：构建后端 jar → 构建前端 → 上传 jar（**旧版自动备份成 `app.jar.prev`**）→
上传前端（先清空 `assets/`，避免旧的哈希文件堆积）→ 从 `git archive HEAD` 同步 `agent-service`
（**服务器上的 `.venv` 不会被碰**）→ 改属主 → 重启两个 systemd 单元 → **健康检查**
（后端 / agent / 首页各探一次，任何一步不过就返回非零退出码并打印排查命令）。

**健康检查失败会报错退出**——不会出现"脚本说成功、网站其实打不开"这种情况。

不想每次敲 IP 和域名，就建一个本地配置文件（**已在 `.gitignore` 里，不会进仓库**）：

```bash
cp deploy/.deploy.env.example deploy/.deploy.env
# 填 DEPLOY_HOST / DEPLOY_DOMAIN / DEPLOY_SSH_KEY，之后直接 ./deploy/deploy.sh
```

常用开关：

| 开关 | 用途 |
|---|---|
| `--only backend` / `--only web` / `--only agent` | 只更一部分（改一行前端文案就不必重建后端） |
| `--with-tests` | 先跑 `mvn test` 再打包 |
| `--no-restart` | 只上传不重启（想自己控制重启时机时用） |

### 出问题怎么退回去

后端留了上一版：

```bash
ssh -i ~/.ssh/id_ed25519 root@<IP> \
  'cd /opt/fusionpilot/backend && mv app.jar.prev app.jar && systemctl restart fusionpilot-backend'
```

前端没有自动备份（`dist` 是纯构建产物），**回退就是回到旧提交重新跑一次 `deploy.sh`**。
所以**上线前先 `git commit`**，否则没有可回退的点。

### 三个会咬人的地方

- **`agent-service` 是按 `HEAD` 同步的**，没提交的改动不会被发上去。脚本会检测到并打印警告，
  但不会替你提交。
- **`web/dist` 与 `backend/target` 都是构建产物，不进 git**，服务器上也没有源码，
  所以**只能在本地构建**——这也是脚本刻意不在服务器上装 Maven/Node 的原因（1.6G 机器跑构建会很难受）。
- **只改了 `schema.sql`（加表/加列）时**，部署会自动生效：后端每次启动都执行 `schema.sql`，
  里面全是 `create table if not exists`，重复执行安全。但**老库上的列变更不会自动加**——
  那种情况要么手写 `ALTER TABLE`，要么参考 `docs/mysql/migrations/`（那套脚本只用于升级老库，
  **全新部署不要跑**，会报 Duplicate column）。

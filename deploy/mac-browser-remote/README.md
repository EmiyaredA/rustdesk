# 浏览器远控 Mac

首版目标：M5 / macOS Tahoe 26.6 的日常办公。采用 Apache Guacamole + guacd + PostgreSQL；网站账号密码与 TOTP 双重验证。Linux 部署增加 Caddy HTTPS 与 WireGuard。

这是一套独立部署工程，不使用或修改 RustDesk 的客户端、服务端、协议或子模块。Docker 在本地模拟服务器侧环境；正式部署后 Mac 只需要系统屏幕共享和 WireGuard，Docker 运行在 Linux 服务器上。

## 1. 本地开始

需要 Python 3.9+、Docker Desktop 和 Compose。先启动 Docker Desktop。所有命令均在本目录执行：

```sh
cd /Users/tonghao/Projects/rustdesk/deploy/mac-browser-remote
python3 remote.py init
python3 remote.py up
python3 remote.py check
```

首次初始化会：

1. 创建权限为 `0600` 的 `.env`，生成随机数据库密码。
2. 启动 PostgreSQL，提取同版本官方 Guacamole 数据库结构。
3. 隐藏输入两遍新的 `guacadmin` 密码（至少 12 字符），以及两遍你已在 Mac 设置的 VNC 密码。
4. 在同一数据库事务内创建结构、替换默认管理员密码并创建 `My Mac` 连接。此时网站尚未启动，默认 `guacadmin / guacadmin` 不会有公开可登录的窗口。

`init` 重复执行会保留已有账号、TOTP 和连接。不要重命名或禁用引导管理员 `guacadmin`；脚本用它确认数据库已经安全初始化。若 `.env` 丢失但数据卷还在，脚本拒绝重新生成数据库密码，需找回原 `.env`。

本地入口：<http://127.0.0.1:8080/guacamole/>。第一次启动需要下载编译工具和源码、构建 VNC 兼容插件，之后利用 Docker 构建缓存；Tomcat 启动也需要一点时间。网页只绑定回环地址，不供其他电脑直接访问。数据库和 guacd 无宿主机端口；基础镜像固定多架构摘要，不使用 `latest` 或 x86 模拟运行。

### Apple 认证协商兼容

Mac 同时提供 Apple 系统账号认证与传统 VNC 密码认证；官方 guacd 1.6.0 可能优先选择前者，出现额外的“用户名”提示。独立 VNC 密码不能用于 Apple 系统账号认证。

本工程的 guacd 以固定摘要的官方 1.6.0 镜像为基底，下载并校验同版本 Apache 官方源码的 SHA-256，仅对 VNC 插件增加认证选择条件：**未配置 username 时，只允许 VNC 密码认证；配置了 username 时保留原有协商行为**。不允许无认证连接，也不改用户凭据。

`guacd/vnc-password-auth.patch` 是完整补丁；最终镜像仅替换该插件的动态库，保留官方守护进程及依赖。编译器只存在于构建阶段。`remote.py up` 会先完成构建，成功后再替换运行容器；构建失败不启动半成品镜像，也不改数据库。Docker 构建上下文只包含 `guacd/`，不会发送 `.env` 或备份。

传统 VNC 不提供会话加密，因此公网部署必须继续使用 WireGuard；网站侧的密码和 TOTP 也不能替代这段隧道。

### Mac 的屏幕共享

在 Mac「系统设置 → 通用 → 共享」里开启「屏幕共享」，在详情中配置允许的访问用户，并开启「VNC 查看器可以使用密码控制屏幕」。不同系统语言下文字可能略有差异；如果正在使用「远程管理」，先处理它与「屏幕共享」的互斥设置。

- 设置独立 VNC 密码；不要把 macOS 登录密码当成 VNC 密码。
- 第三方 VNC 的传统密码模式存在长度/字符限制，以 Mac 设置界面接受的值为准；网站账号仍使用长密码 + TOTP。
- 首版连接 `host.docker.internal:5900`。这个地址只用于 Docker Desktop 本地验证。
- 保持 Mac 接电联网、系统不休眠；可以锁屏。脚本不更改共享、权限、防火墙、休眠或 FileVault 设置。
- 本地验证时屏幕共享可能同时在局域网监听，需在可信网络进行，不要在路由器上映射 `5900`。正式部署的按来源隔离见后文。

`check` 在服务启动后执行，检查 Docker、Compose、端口隔离、管理员初始化与 **guacd 容器到 VNC 的协议问候**。它不会验证 VNC 密码或控制真实桌面；能收到 `RFB` 不代表远控验收通过。

## 2. 登录与日常账号

1. 使用 `guacadmin` 和初始化时输入的密码登录。
2. 用手机的 TOTP 认证器扫描网页二维码，输入动态验证码，完成管理员注册。初次注册只在本地受控入口或可信 HTTPS 下进行。
3. 在设置中创建日常账号（例如 `mac-user`），设独立长密码，不授予系统管理、创建连接或创建用户权限。
4. 只为日常账号授予 `My Mac` 连接的 **READ / 使用权限**。保留用户自身默认权限，不勾选「Disable TOTP」。
5. 注销管理员，使用日常账号登录，并单独绑定它的 TOTP。

`My Mac` 连接固定当前分辨率、不请求更改显示器大小；允许操作和双向文本剪贴板，关闭音频和 SFTP。连接总并发与每用户并发均为 1；管理员测试前先断开日常账号的桌面连接。

中文和浏览器快捷键需要实测。若浏览器系统剪贴板权限受限，可使用 Guacamole 菜单（`Ctrl+Alt+Shift`）的文本剪贴板面板。不要把剪贴板面板能用等同于系统快捷键复制粘贴已通过。

VNC 可能先显示 macOS 登录窗口，即使本机当前没有锁屏，也可能需要在这个远程画面内正常登录后才能进入当前桌面。这一步由用户手动完成，不把 macOS 登录密码保存到连接配置。若在同一台 Mac 上打开自己的远控网页，会看到屏幕里套着屏幕的镜像递归，属于正常显示；完整操作体验应从另一台设备验证。

验证码变化只影响后续身份验证，不会定时踢掉已连接的人。首版使用内置注销和管理员断开会话，不增加自己的会话计时器。`API_SESSION_TIMEOUT=15` 是 Web API 的空闲认证时限，不是“桌面 15 分钟必断开”。临时断网后，网络恢复并重新连接即可；不承诺保留原网络连接。

## 3. 日常操作与备份

```sh
python3 remote.py status
python3 remote.py logs
python3 remote.py backup
python3 remote.py down
python3 remote.py up
python3 remote.py restore backups/实际备份文件.dump
python3 remote.py up
```

`down` 不删除数据卷和证书。`backup` 生成 PostgreSQL 自定义格式备份，目录 `0700`、文件 `0600`；备份包含账号、连接密码和 TOTP 密钥，需作为秘密保管。另行安全保存 `.env`；不要把它提交、发送到聊天或直接放进公开备份。Linux 还应单独备份 Caddy 数据卷和 WireGuard 私钥。

`restore` 只接受受信任的本工具备份：先在临时数据库恢复并检查，再停止网站、自动备份当前数据库，最后以事务恢复。失败时不自动启动网站；原库的事务失败会回滚，修复问题后再手动 `up`。恢复成功后，账号密码和 TOTP 也会回到备份时刻。临时数据库验证不会更改线上数据。

诊断仅输出固定数量的应用/guacd 日志，不启用 debug 日志。不运行会展开数据库密码的 `docker compose config`；配置检查使用 `--quiet`。Docker 管理员仍可通过容器检查读取环境变量，数据库备份和宿主机都在信任边界内。

## 4. Linux + 域名 HTTPS

参考宿主机为 Ubuntu 24.04 LTS + Docker Engine/Compose + Python 3.9+ + WireGuard。配置文件支持原生 ARM64 和 amd64；Linux 实机部署未完成前不得标为公网验收通过。

将本目录复制到服务器的独立位置。先确保域名 A 记录指向服务器，若有 AAAA 记录也必须正确；云安全组和宿主机防火墙允许 TCP `80/443`、UDP `51820`，保留原有 SSH 管理入口。

首次创建服务器数据库：

```sh
PUBLIC_DOMAIN=remote.your-domain.tld python3 remote.py --server init
```

首次命令会把域名写入新 `.env`。若 `.env` 已存在，直接编辑其中的 `PUBLIC_DOMAIN`。本地和服务器的环境独立生成；不要同时用本地与服务器的 Compose 覆盖文件启动同一项目。

`--server init/up/check` 会用 `ip -j route show table all` 检查 `10.66.0.0/24`、`172.30.66.0/24` 是否与已有路由冲突；如有冲突直接失败。已有 `wg0`、`br-mac-remote` 需确实属于本项目，不能借用其他服务的同名接口。更换网段必须同步修改 WireGuard、Compose、连接地址和防火墙规则，不能仅改一处。

### WireGuard

分别在服务器和 Mac 的 WireGuard 应用中生成密钥；私钥保留本机，只交换公钥。使用 `wg-server.conf.example` 和 `wg-mac.conf.example`：

| 节点 | 隧道地址 | Peer AllowedIPs |
| --- | --- | --- |
| Linux `wg0` | `10.66.0.1/24` | `10.66.0.2/32` |
| Mac | `10.66.0.2/32` | `10.66.0.1/32` |

服务器配置保存到 `/etc/wireguard/wg0.conf`（root 所有、`0600`），手动执行 `systemctl enable --now wg-quick@wg0`。Mac 通过 WireGuard 应用导入私有配置，Endpoint 填服务器公网 IP；`PersistentKeepalive=25` 维持 NAT 映射。Mac 的其他上网流量不经过这个隧道。

在服务器检查 `wg show wg0` 的握手、`ip route get 10.66.0.2` 的出口为 `wg0`，并在 Mac 确认能访问服务器隧道地址。

### Docker 到隧道的路由与防火墙

服务器端 guacd 固定为 `172.30.66.2`，Docker 桥为 `br-mac-remote`。先开启 IPv4 转发（检查 Docker 是否已经启用），并通过宿主机现有的 sysctl 管理方式持久化 `net.ipv4.ip_forward=1`。

以下为 Docker 使用 **iptables 后端**时的规则。先确认 `DOCKER-USER` 链存在；使用 nftables 后端的主机不能照抄这些命令，应先切换到经过验证的 iptables 部署配置。本模板不自动更换防火墙后端。

```sh
sudo iptables -I DOCKER-USER 1 -i wg0 -o br-mac-remote -s 10.66.0.2 -d 172.30.66.2 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -I DOCKER-USER 2 -i br-mac-remote -o wg0 -s 172.30.66.2 -d 10.66.0.2 -p tcp --dport 5900 -j ACCEPT
sudo iptables -I DOCKER-USER 3 -i br-mac-remote -o wg0 -j REJECT
sudo iptables -I DOCKER-USER 4 -i wg0 -o br-mac-remote -j REJECT
sudo iptables -t nat -I POSTROUTING 1 -s 172.30.66.2 -d 10.66.0.2 -o wg0 -p tcp --dport 5900 -j SNAT --to-source 10.66.0.1
```

这样 Mac 看到的连接来源为 `10.66.0.1`，符合它的 WireGuard AllowedIPs。规则只放行 guacd 到 Mac 的 TCP 5900 和返回流量，不开放整个 Docker 子网到 Mac。规则只在首次部署时添加一次，检查顺序，并使用宿主机已有的持久化方式保存；不要覆盖或清空现有规则集。

### Mac 侧限制 VNC 来源

正式部署时，屏幕共享只接受隧道中 `10.66.0.1 → 10.66.0.2:5900` 的连接；其他 IPv4/IPv6 来源均拒绝。macOS 的应用防火墙开关不能代替按来源过滤。

`pf-mac.conf.example` 提供 PF anchor 规则，先用 `sudo pfctl -nf pf-mac.conf.example` 只做语法检查。启用时备份现有 `/etc/pf.conf`，把规则保存到 `/etc/pf.anchors/mac-remote`，在现有过滤规则之前加入：

```text
anchor "mac-remote"
load anchor "mac-remote" from "/etc/pf.anchors/mac-remote"
```

保留 Apple 和其他应用已有的规则，检查是否存在跳过过滤的接口设置。再次用 `sudo pfctl -nf /etc/pf.conf` 检查，通过后由管理员加载规则并确认 PF 已启用。PF 变更可能影响已有网络服务，脚本不会代为执行。停止使用时只移除本项目 anchor，恢复原规则，不清空系统规则集。

此正式规则会拒绝本地 Docker 测试的来源，应用前先停止 Mac 上的测试栈。用另一台局域网设备验证 TCP 5900 被拒绝，用服务器 `--server check` 验证隧道路径允许。Mac 重启后 PF/WireGuard 状态需重新核对，重启恢复不在首版保证范围内。

### 启动服务器入口

```sh
python3 remote.py --server up
python3 remote.py --server check
python3 remote.py --server status
```

访问 `https://你的域名/guacamole/`。Caddy 自动申请证书、续期并将 HTTP 跳转为 HTTPS；证书保留在 `caddy_data` 卷中。`compose.server.yml` 不发布 Guacamole 的 8080，不发布数据库或 guacd。服务器模式的所有管理命令均带 `--server`。

服务器模式启用官方 RemoteIpValve，由内部 Caddy 传递真实客户端地址，供审计和登录限速使用。后端仍只允许内部网络访问；不要另行发布 8080，或让不受信任的容器加入这些网络。

如果从本地备份迁移数据库：服务器先初始化独立数据库，再用 `--server restore` 导入；恢复后保持网站停止，先仅在服务器回环地址临时启动本地入口，通过 SSH 本地端口转发登录管理员，把 `My Mac` 的 hostname 从 `host.docker.internal` 改为 `10.66.0.2`。停止临时本地入口后，再运行 `--server up`，不要用 `--server init` 覆盖已有连接。

## 5. 验收与边界

记录日期、镜像摘要、浏览器、Mac 系统版本，逐项记录通过或失败：

- [ ] 正确账号和动态码登录；错误密码、缺失/错误/过期动态码不能进入；默认管理员密码失效。
- [ ] 日常账号只有 `My Mac` 连接使用权限，不能管理账号或修改连接。
- [ ] 连续办公 30 分钟：点击、拖动、滚动、中文输入、Command 快捷键、双向文本剪贴板，无持续卡键或不明断线。
- [ ] 锁屏后重连；短暂断网恢复后重连。
- [ ] 重建容器后，账号、TOTP 和连接仍在；备份可以恢复到临时数据库并验证配置。
- [ ] 本地网站仅监听回环；数据库/guacd 无公开端口。
- [ ] Linux：手机热点访问 HTTPS 正常；HTTP 跳转；WebSocket 远控正常；VNC 只能通过隧道访问；证书可续期。

先验证 VNC 认证和输入。若 26.6 上失败，记录现象和日志，先停止验收，不自动切到其他客户端或扩大到修改 RustDesk。

睡眠、合盖、重启后的 FileVault 解锁、系统音频、文件传输及自定义周期密码/通知不包含在首版。屏幕共享通常操作真实桌面，不能当作隐私屏幕或独立虚拟桌面。Guacamole 服务器会处理桌面数据，服务器管理员、Docker 管理权限和备份都需要信任。

## 官方依据

- [Guacamole Docker 部署](https://guacamole.apache.org/doc/gug/guacamole-docker.html)
- [PostgreSQL 初始化](https://guacamole.apache.org/doc/gug/postgresql-auth.html)
- [TOTP 注册与验证](https://guacamole.apache.org/doc/gug/totp-auth.html)
- [VNC 连接参数](https://guacamole.apache.org/doc/gug/configuring-guacamole.html#vnc)
- [Docker Desktop 访问宿主机](https://docs.docker.com/desktop/features/networking/networking-how-tos/)
- [Caddy 自动 HTTPS](https://caddyserver.com/docs/automatic-https)
- [WireGuard 配置与 NAT keepalive](https://www.wireguard.com/quickstart/)

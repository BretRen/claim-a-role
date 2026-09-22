# Fluxer 专属角色自领机器人 (ClaimRolesBot)

为 [Fluxer](https://docs.fluxer.app) 聊天平台量身打造的自选身份组/角色领取机器人（Reaction Role）。

管理员可通过 `/set-role` 与 `/set-home` 便捷管理服务器的可自选角色库，机器人将在指定的 Home Channel 发布美观的自选看板并添加 Emoji 反应。群员点击对应的 Emoji 表情即可获得角色，取消点击即可退回角色。

---

## ✨ 功能特性

- **基于表情反应领取 (Reaction Role)**：点击 Emoji 获得角色，取消 Emoji 剥夺角色，支持即时自由多选。
- **双前缀全兼容**：同时支持斜杠 `/` 与感叹号 `!` 前缀（如 `/set-role` 与 `!set-role` 等价）。
- **严格安全权限控制**：基于环境变量 `ADMIN_USER_IDS` 白名单，非管理员执行管理指令一律**静默忽略**，无权限骚扰。
- **看板自动实时同步**：管理员执行 `add` / `update` / `remove` / `clear` 后，Home Channel 看板消息及 Emoji 反应自动实时更新。
- **角色级联清理**：当服务器中某个角色被删除时，自动从自选库中剔除失效角色并刷新看板。
- **纯 JSON 文件持久化**：公会配置与角色映射保存为 `data/config.json`，结构直观、支持随时人工查看与编辑。
- **自动实例探测**：支持官方 `https://api.fluxer.app` 及任意自托管 Fluxer 实例，自动通过 `/.well-known/fluxer` 与 `/v1/gateway/bot` 探测 Gateway 与 API 路由。
- **容器化一键部署**：内置 `Dockerfile` 和 `docker-compose.yml`，开箱即用。

---

## 🚀 快速开始

### 1. 克隆与安装依赖

```bash
git clone <repository_url>
cd claimrolesbot

pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 并重命名为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```ini
# Fluxer Bot Token（格式: <application_id>.<secret>）
FLUXER_BOT_TOKEN=123456789012345678.abcdefghijklmnopqrstuvwxyz

# 允许使用管理指令的用户 Snowflake ID，多个 ID 用半角逗号分隔
ADMIN_USER_IDS=123456789012345678,234567890123456789

# Fluxer API 基础地址（默认为官方 https://api.fluxer.app，若为自建实例请修改）
FLUXER_API_BASE=https://api.fluxer.app

# 配置文件持久化路径（默认 data/config.json）
CONFIG_PATH=data/config.json
```

### 3. 本地启动

```bash
python main.py
```

### 4. Docker 部署

```bash
docker-compose up -d --build
```

---

## 🛠️ 管理员指令大全

> **说明**：所有管理指令仅限 `ADMIN_USER_IDS` 中配置的管理员可用。非管理员执行将被**静默忽略**。

| 指令语法 | 说明 | 示例 |
| :--- | :--- | :--- |
| `/set-home` | 将当前频道设为角色领取专属频道，并发布初始看板 | `/set-home` |
| `/set-home <channel_id>` | 指定某个频道作为角色自选主频道 | `/set-home <#9876543210>` |
| `/set-role add <emoji> <@role/角色ID> [描述]` | 添加一个可领取的自选角色，看板自动同步更新 | `/set-role add ⭐ <@&11223344> 社区贵宾赞助者` |
| `/set-role list` | 查看当前公会配置的所有自选角色清单 | `/set-role list` |
| `/set-role update <角色ID/Emoji> <新Emoji> [新描述]` | 修改已注册角色的表情或介绍说明 | `/set-role update 11223344 🌟 超级赞助者` |
| `/set-role remove <角色ID/Emoji>` | 移除指定的自选角色，看板自动剔除对应项 | `/set-role remove 11223344` 或 `/set-role remove ⭐` |
| `/set-role clear` | 清空当前公会的全部自选角色并重置看板 | `/set-role clear` |
| `/set-role refresh` | 强制重新生成或刷新当前公会的看板消息及表情 | `/set-role refresh` |
| `/set-role help` | 打印指令帮助手册 | `/set-role help` |

*(所有指令均可使用 `!` 替换 `/`，例如 `!set-role add ...`)*

---

## 📂 项目结构

```
claimrolesbot/
├── config.py              # 配置管理与环境变量校验
├── storage.py             # JSON 文件持久化存储管理器
├── fluxer_api.py          # 异步 Fluxer HTTP REST API 客户端
├── fluxer_gateway.py      # 异步 WebSocket Gateway 客户端（心跳、鉴权与事件分发）
├── bot.py                 # 核心业务逻辑（指令解析、权限验证、看板同步与表情反应）
├── main.py                # 机器人运行入口
├── requirements.txt       # Python 依赖清单
├── .env.example           # 环境变量示例文件
├── Dockerfile             # Docker 镜像构建脚本
├── docker-compose.yml     # Docker 容器编排文件
├── tests/                 # 自动化测试套件
│   ├── test_config.py
│   ├── test_storage.py
│   └── test_bot_logic.py
└── data/
    └── config.json        # 运行时持久化数据文件
```

---

## 🧪 运行测试

执行单元测试：

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

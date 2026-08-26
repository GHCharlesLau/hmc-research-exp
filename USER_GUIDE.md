# USER_GUIDE.md — ConExperiment 2.0 使用指南 / User Guide

**版本**: v2.5.1 (2026-08)

### 版本更新记录

| 版本 | 更新内容 |
|------|---------|
| v2.5.1 | **运维与文档**：页面停留超时自动出队；导出增加 `is_timeout` / `is_dropout` / `chat_r*_over_max` 筛选；Welcome 加密失败不再 500；Test Tools 按条件创建后 Consent 不再重新抽组；两轮保持同一 `task_type` |
| v2.5.0 | **Page C 精简为 7 个 outcome scales（25 题）**；Prolific HMAC 去重 + 24 位格式校验；条件分配加锁；R1→R2 chatbot 上下文注入；R2 超时不改写 `partnership`（ITT）；`force_chatbot` 从 DB 状态派生 |
| v2.4.0 | 聊天超时 retry/dropout 对话框；R2 排除 R1 partner；LLM 回复长度控制 |
| v2.3.0 | **问卷 Scale Registry**：`services/scales.py` + Likert 宏；新增 Survey Page C；PostgreSQL ENUM 补 `survey_c`；`display_title` 隐藏学术变量名 |
| v2.2.0 | **HHC Turn 计数修复 + 欺骗泄露修复**：turn 为 `min(A_count, B_count)`；`partner_left` 使用欺骗条件显示名 |
| v2.1.0 | **HHC DB session 修复 + generation counter 修复**：`listen_redis` 使用独立 DB session |
| v2.0.x | HMC 虚假配对、HHC max-turns 横幅、R2 显示、`tojson` JS 转义 |
| v2.0.0 | 监控增强：Resume URL、Dashboard 进度条、事件流、LLM 统计、卡住检测、参与者详情 |
| v1.8.0 | UI 提醒条、头像逻辑、Instructions 去头像、R1 超时改 `partnership`、Admin 认证加固 |
| v1.7.0 | Dashboard 5s 刷新、Test Tools 快捷栏、HHC 消息显示修复 |
| v1.6.0 | R1 HMC 虚假等候室、R2 全员尝试真人配对、R2 回退强制 BOT |
| v1.5.1 | 测试数据删除与清理 |
| v1.5.0 | Demo Mode、Test Tools、导出过滤 `is_test` |
| v1.0.0–v1.4.0 | 初始平台与首轮测试修复（见 Git 历史） |

---

## 中文版 / Chinese Version

### 1. 环境搭建 / Setup

#### 1.1 安装依赖

```bash
# 克隆项目后
cd ConExperiment2.0

# 安装 Python 依赖
pip install -r requirements.txt
```

#### 1.2 启动基础设施

```bash
# 启动 PostgreSQL 和 Redis（需要 Docker）
docker-compose up -d

# 验证服务运行
docker-compose ps
```

#### 1.3 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env，填写以下必要配置：
# - SECRET_KEY: 随机字符串（可用 python -c "import secrets; print(secrets.token_urlsafe(32))"）
# - ENCRYPTION_KEY: Fernet 密钥（Welcome 页必填；缺失会导致无法保存 Prolific ID）
# - ADMIN_PASSWORD_HASH: 管理员密码的 SHA256 哈希（见下方生成方法）
# - 主 LLM：N1N_API_KEY + LLM_API_BASE（网关），或直接填 OPENAI_API_KEY
#
# 可选配置（备用 LLM provider，主 provider 失败时自动切换）：
# - LLM_BACKUP_API_BASE: 备用 API 地址
# - LLM_BACKUP_API_KEY: 备用 API 密钥
# - LLM_BACKUP_MODEL: 备用模型名称（默认 gpt-4o-mini）
```

**生成加密密钥：**
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

**生成管理员密码哈希：**
```python
import hashlib
password = "your-admin-password"
print(hashlib.sha256(password.encode()).hexdigest())
```

#### 1.4 头像与任务图片

`static/avatar/` 已包含正式 PNG/JPG，无需再从 v1 复制：

| 文件 | 用途 |
|------|------|
| `myBot.png` | AI 对话伙伴（MyBot）头像，参与者不可选 |
| `fox.png` | Tommy（伪装人类）头像；也可作为参与者头像 |
| `lion.png` / `rabbit.png` / `tiger.png` | 参与者可选头像 |
| `img_sad.png` | 情绪任务热身图 |
| `img_box.jpg` | 功能任务热身图 |

#### 1.5 数据库迁移

仓库已包含完整迁移链。本地或新环境只需执行：

```bash
alembic upgrade head
```

不要对已有库再跑 `alembic revision --autogenerate -m "initial"`，那会生成重复的初始迁移。只有改了模型（例如新增量表列）才需要 `alembic revision --autogenerate -m "描述"`。

#### 1.6 启动开发服务器

**方法 A: CLI 启动（推荐）**
```bash
# 正常模式
python main.py run --reload

# Demo 模式（测试/演示用，减少等待时间）
python main.py run --demo --reload
```

**方法 B: 直接使用 uvicorn**
```bash
uvicorn main:app --reload --port 8000
```

**CLI 命令说明**:
- `--demo`: 启用 Demo 模式（减少轮次和超时时间，跳过 Prolific 检查）
- `--reload`: 启用自动重载（开发时推荐）
- `--host`: 指定主机地址（默认 0.0.0.0）
- `--port`: 指定端口（默认 8000）

访问：
- 实验入口：http://localhost:8000
- 健康检查：http://localhost:8000/health
- API 文档：http://localhost:8000/docs
- 管理后台：http://localhost:8000/admin/login

运行测试（需先 `pip install -r requirements-dev.txt`）：

```bash
pytest -q
```

#### 1.7 首次运行配置

> **v1.2 更新**: 4 个 CHARACTER_PROMPT 已内置默认值（从 ConExperiment v1 迁移），无需手动配置即可直接测试。管理后台的 Config 页面可以随时覆盖默认值。

首次启动后的可选配置：

1. **登录管理后台** → `/admin/login`（使用 .env 中的管理员密码）
2. **（可选）自定义 LLM 提示词** → Config 页面中修改 4 个 CHARACTER_PROMPT（A/Afake/B/Bfake），留空则使用内置默认值
3. **确认模型配置** → `default_model` 默认为 `gpt-4o-mini`，可修改为 `claude-haiku-4-5` 等

#### 1.8 项目结构

每个目录/文件只做一件事：入口、配置、数据、路由、业务逻辑、页面、静态资源、测试、部署。

```
ConExperiment2.0/
├── main.py                  # FastAPI 入口：注册路由、CORS、lifespan、CLI（typer）
├── config.py                # 从环境变量读取设置（聊天轮次、LLM、Demo 模式等）
├── database.py              # SQLAlchemy 异步引擎与会话（连接池 20+30）
├── docker-compose.yml       # 本地 PostgreSQL + Redis
├── render.yaml              # Render Blueprint（Web + Redis；DATABASE_URL 在 Dashboard 手动填）
├── start.sh                 # 部署启动脚本：迁移 + uvicorn --workers 1
├── alembic.ini / alembic/   # 数据库迁移
├── requirements.txt         # 生产依赖
├── requirements-dev.txt     # pytest 等开发依赖
├── pytest.ini
├── .env.example             # 环境变量模板（不要提交真实 .env）
├── .github/workflows/ci.yml # CI：pytest
│
├── models/                  # SQLAlchemy 表结构（参与者、聊天、问卷、事件日志）
├── schemas/                 # Pydantic 请求/响应校验
├── dependencies/            # 共享依赖（从 Cookie 取参与者会话）
├── routers/                 # HTTP / WebSocket 路由
├── services/                # 业务逻辑（配对、LLM、导出、Prolific、量表…）
├── templates/               # Jinja2 页面（实验页 + 管理后台）
├── static/                  # CSS、chat.js、头像
└── tests/                   # 条件分配、流程、Prolific、导出等测试
```

**入口与配置**

| 文件 | 作用 |
|------|------|
| `main.py` | 应用入口；挂载 experiment / survey / chat / ws / admin 路由；启动时连 Redis、跑后台任务 |
| `config.py` | 所有可调参数的单一来源；Render 的 `postgresql://` 会自动转成 asyncpg / psycopg2 |
| `database.py` | 异步数据库引擎；`pool_size=20`、`max_overflow=30` |

**数据层 `models/`**

| 文件 | 作用 |
|------|------|
| `participant.py` | 参与者：条件（task_type / partnership / partner_label）、当前步骤（13 步）、轮次、超时/退出标记、加密 Prolific ID |
| `chat.py` | 聊天室（HHC/HMC、轮次、turn 数）与消息 |
| `survey.py` | 问卷作答（Likert + 人口统计） |
| `experiment.py` | 事件日志与实验配置（含可覆盖的 LLM prompt） |

**路由 `routers/`**

| 文件 | 作用 |
|------|------|
| `experiment.py` | 知情同意、Welcome、热身、说明、Payment、`/resume/{token}`；条件分配加锁 |
| `survey.py` | 问卷说明 + Page A/B/C + 人口统计 |
| `chat.py` | 聊天页、配对确认页、结束聊天（含 retry/dropout）、HMC/HHC 聊天 WebSocket |
| `ws.py` | 配对等候室 WebSocket（HHC 真排队 / HMC 5–15s 假等待） |
| `errors.py` | 404 / 500 页面 |
| `admin/` | 管理后台拆成多个子路由：登录、仪表盘、参与者、导出、配置、测试工具 |

**业务逻辑 `services/`**

| 文件 | 作用 |
|------|------|
| `__init__.py` | 最小配额条件分配 + 并发锁（防止两人同时抽到同一格） |
| `matchmaking.py` | Redis 有序集合排队、120s 超时回退、出队（含停留超时清队列） |
| `llm.py` | litellm 调用、并发信号量（默认 30）、失败兜底回复、R2 注入 R1 对话上下文 |
| `redis_pubsub.py` | 跨连接广播聊天消息；**每个聊天 WebSocket 占用一条独立 Redis 连接** |
| `prolific.py` | URL 参数、24 位格式校验、HMAC 去重、完成回调 |
| `scales.py` | Likert 量表注册表（改量表主要改这里 + `models/survey.py`） |
| `export.py` | 参与者宽表 / 聊天长表 CSV |
| `monitoring.py` | 事件记录、步骤计时、卡住检测（超时标 `is_timeout` 并移出队列） |
| `chat_settings.py` / `chat_context.py` | 聊天轮次/时长配置；聊天页上下文（身份、头像、force_chatbot） |
| `participant_factory.py` | 测试被试创建 |
| `auth.py` | 管理员密码校验 |

**页面与静态资源**

| 路径 | 作用 |
|------|------|
| `templates/` | 实验页约 16 个（含错误页）+ 管理后台 8 个 + Likert 宏 |
| `static/css/main.css` | 全站样式 |
| `static/js/chat.js` | 聊天 WebSocket 客户端（重连、历史恢复、去重） |
| `static/avatar/` | 头像与热身图 |

**其它**

| 路径 | 作用 |
|------|------|
| `schemas/` | API / 表单校验（参与者、聊天、问卷、管理员） |
| `dependencies/participant.py` | 从会话 Cookie 解析当前参与者，供各路由复用 |
| `alembic/` | 表结构变更历史；部署时 `alembic upgrade head` |
| `tests/` | 不连真实 LLM 的单元/集成测试 |
| `render.yaml` | Render 一键蓝图；**不要把数据库密码写进仓库** |

### 2. 管理后台使用 / Admin Dashboard

#### 2.1 登录

访问 `/admin/login`，输入 `.env` 中配置的管理员密码。会话有效期 24 小时。

#### 2.2 Dashboard（仪表盘）

显示实验概览，**每 5 秒自动刷新**：
- 总参与人数 / 已完成 / 进行中 / 聊天中
- **LLM 调用统计**：总调用次数 + 错误率（蓝色卡片）
- 各条件（2×2×2）分配情况
- **步骤分布表**：显示活跃参与者的当前步骤分布
- **活跃聊天室监控**：实时显示所有进行中的聊天房间
  - HHC 房间按共享 room_id 分组，显示双方参与者
  - HMC 房间单独显示，带参与者信息
  - 房间类型颜色标签（HHC: 蓝色, HMC: 橙色）
  - 实时计算聊天时长
  - **"Peek" 按钮**：点击展开最近 10 条聊天消息的实时预览
- **活跃参与者进度条**：每个活跃参与者显示彩色进度条（蓝色 <40%, 橙色 40-80%, 绿色 >80%）
- **事件流**：实时滚动日志，每 3 秒刷新，显示配对/超时/LLM 调用等事件
- **卡住参与者警告**：超过步骤时间限制时，页面顶部显示黄色警告横幅

#### 2.3 Participants（参与者列表）

查看所有参与者信息，包括：
- 分配条件（taskType, partnership, partnerLabel）
- 当前步骤 + **彩色进度条**（13 步进度百分比）
- 当前轮次
- 状态标签（Finished / Active / Timeout）
- HHC 回退状态
- 创建时间
- **"View" 链接**：点击进入参与者详情页

#### 2.3.1 参与者详情页 (`/admin/participant/{display_id}`) — v2.0 新增

查看单个参与者的完整信息：
- **条件标签**：taskType, partnership, partnerLabel 等彩色标签
- **Resume URL**：可复制的恢复链接，支持参与者恢复会话
- **13 步进度条**：高亮当前步骤位置（consent → … → payment）
- **步骤停留时长**：每步的 from/to/时长/限制/是否超限
- **聊天历史**：按轮次折叠显示，活跃房间支持刷新
- **问卷回答**：所有量表得分
- **事件历史**：该参与者的最近事件记录

#### 2.4 Config（配置编辑器）

可在线编辑的配置项：

| 配置键 | 说明 | 默认值 |
|--------|------|--------|
| `CHARACTER_PROMPT_A` | 情绪任务 + MyBot (AI) 的系统提示词 | 内置 (v1.2) |
| `CHARACTER_PROMPT_Afake` | 情绪任务 + Tommy (伪装人类) 的系统提示词 | 内置 (v1.2) |
| `CHARACTER_PROMPT_B` | 功能任务 + MyBot (AI) 的系统提示词 | 内置 (v1.2) |
| `CHARACTER_PROMPT_Bfake` | 功能任务 + Tommy (伪装人类) 的系统提示词 | 内置 (v1.2) |
| `default_model` | LLM 模型名称 | `gpt-4o-mini` |
| `min_turns` | 最少对话轮数（才可结束） | `5` |
| `max_turns` | 最多对话轮数（自动结束） | `15` |
| `max_duration` | 聊天最长时间（秒） | `600` |

**提示词填写指南：**
- CHARACTER_PROMPT_A/B：可以暴露 AI 身份（如 "You are a conversational AI named MyBot"）
- CHARACTER_PROMPT_Afake/Bfake：需要伪装成人类（如 "You are a conversational partner named Tommy"）
- 所有提示词需包含任务指引（情绪分享 或 功能协作）
- 留空则使用内置默认值（从 ConExperiment v1 迁移），在管理后台清空即可恢复默认

**修改后即时生效**，无需重启服务器。

#### 2.5 Data Export（数据导出）

两种 CSV 导出格式：

**参与者宽表** (`participants.csv`)：
- 每行一个参与者
- 含：`nickname`、`avatar`、条件分配、**分轮搭档** `partner_display_id_r1` / `partner_display_id_r2`（HMC 为空）、问卷、人口统计、两轮聊天统计（含 `chat_r*_room_type`）

**聊天长表** (`chat_messages.csv`)：
- 每行一条聊天消息
- 含：`timestamp`（UTC，Excel 安全格式）、参与者 `display_id` / `nickname` / `avatar`、**该条消息所在房间的** `partner_display_id`、轮次、`room_type`、发送者、turn、正文

> 旧版宽表只有一列 `partner_display_id`，读的是 `Participant.partner_id`。该字段在 Round 2 配对时会被覆盖，所以两轮搭档看起来相同。现已改为按各轮 ChatRoom 的共享 `room_id` 解析。HMC / AI 回退没有真人搭档，对应单元格为空。

> **v1.5 更新**: 导出默认排除测试被试（`is_test=True`）。勾选 "Include test participants" 可包含测试数据。
>
> **数据质量筛选**: 宽表新增 `chat_r1_over_max` / `chat_r2_over_max`（聊天时长是否达到 `max_duration`）。可勾选排除：页面停留超时（`is_timeout`）、中途退出（`is_dropout`）、聊天达到最长时长。未满最少轮数就超时的聊天会标 `is_timeout=True`。页面停留超时的人会被移出配对队列。

#### 2.6 Test Tools（测试工具）— v1.5 新增，v1.7 优化

访问 `/admin/test-tools`，提供以下测试功能：

**Demo Mode（演示模式）**：
- **方法 1（推荐）**: 使用 CLI 启动 `python main.py run --demo`
- **方法 2**: 在 `.env` 中设置 `DEMO_MODE=true` 并重启服务器
- 效果：聊天轮次减少（2–5 轮），超时缩短（10s HHC 匹配 / **300s** 聊天），Prolific 检查跳过
- 适合演示和快速测试

**快捷操作栏** — v1.7 新增:
页面顶部的三个一键按钮：

1. **Quick Create (HMC, instructions_r1)**：一键创建 HMC 测试被试，最快的单人测试方式
2. **Matchmaking Flow Test (HHC)**：创建 2 个 HHC 被试在 instructions_r1。在两个隐身窗口分别打开，可测试完整流程：说明 → 等候室 → 真人匹配 → 聊天
3. **Quick Create HHC (Pair at Chat)**：创建 2 个已配对的 HHC 被试在聊天步骤，直接开始聊天。最快的 HHC 聊天测试方式

**测试被试仪表板** — v1.7 新增:
- 表格显示所有测试被试：Display ID、昵称、任务类型、Partnership、当前步骤、轮次
- 每行**内联操作**：
  - **Open**：在新标签页打开被试实验链接
  - **Next >>**：将被试推进到下一步骤
  - **Delete**：删除测试被试（带确认对话框）
- 步骤值颜色编码：聊天（橙色）、说明（蓝色）、问卷（紫色）

**步骤控制**：
- 将任意参与者跳转到指定步骤（下拉选择器，自动加载测试被试列表）
- 跳到聊天步骤时自动创建 HMC ChatRoom

**高级工具**（可折叠区域）：
- **自定义创建被试**：指定条件、起始步骤、昵称、头像。被试打开 Consent 并同意后，**会沿用你指定的条件**，不会再按 min-quota 重新抽组
- **HHC 队列查看**：查看/清空 Redis 匹配队列

**测试数据管理**：
- 删除单个：仪表板表格中的 "Delete" 按钮（带确认）
- 一键清理：页面底部 "Delete All Test Data" 按钮
- 删除操作自动清理 partner 引用、Redis 队列、聊天/问卷/会话记录

### 3. Prolific 集成 / Prolific Integration

#### 3.1 实验链接格式

在 Prolific 上创建实验时，使用以下链接格式：

```
https://your-domain.com/?PROLIFIC_PID={{%PROLIFIC_PID%}}&SESSION_ID={{%SESSION_ID%}}&STUDY_ID={{%STUDY_ID%}}
```

#### 3.2 配置 Prolific 完成回调

在 `.env` 中设置：
- `PROLIFIC_COMPLETION_URL`：Prolific 提供的完成回调 URL
- `PROLIFIC_API_TOKEN`：Prolific API Token（可选，用于高级功能）

> **注意 (v1.1)**: 系统使用 JSON 格式 (`json=`) 发送完成回调，HTTP 超时为 10 秒。如果 Prolific 要求表单格式，请联系开发者将 `services/prolific.py` 中的 `json=` 改回 `data=`。

Welcome 页也可手动输入 Prolific ID（无 URL 参数时）。ID 必须为 **24 位字母数字**；测试可用任意 24 位字母数字，系统不会向 Prolific 校验真伪。

#### 3.3 重复参与检测

系统用 HMAC-SHA256（`prolific_id_hash`）检测重复，无需解密整表。同一 Prolific ID 不能多次参与。Demo 模式跳过重复检查。

#### 3.4 完成码

参与者完成实验后，会看到形如 `CONEXP-P-0001` 的完成码，需在 Prolific 上输入以获取报酬。

### 4. 实验流程 / Experiment Flow

完整流程：

```
知情同意 → Welcome（Prolific ID + 头像 + 昵称） → 热身写作 → 第1轮说明 → 等候室 → 聊天 → 第2轮说明 → 等候室 → 聊天 → 问卷说明 + A/B/C + 人口统计 → Payment
```

#### 4.0 添加新 Likert 量表 / Adding a New Likert Scale — v2.3 新增

> **v2.3 更新**: 问卷系统采用 Scale Registry 架构，添加新 Likert 量表只需改 **2 个文件**。

**步骤：**

1. 在 `models/survey.py` 中添加 DB 列（如 `trust_1` 到 `trust_4`），然后运行 Alembic 迁移：
   ```bash
   alembic revision --autogenerate -m "add_trust_scale"
   alembic upgrade head
   ```

2. 在 `services/scales.py` 的 `LIKERT_SCALES` 列表中添加一条记录：
   ```python
   LikertScale("trust", "A", "Trust", (
       "I trusted my conversation partner.",
       "My partner was trustworthy.",
       "I felt safe sharing with my partner.",
       "My partner had my best interests in mind.",
   ), display_title="Partner Trustworthiness"),
   ```

完成。Router、模板、验证、CSV 导出全部自动适配。

**技术说明：**
- `page` 参数决定量表出现在哪个页面：`"A"`（Page A）、`"B"`（Page B）、`"C"`（Page C）、`"demographics"`（Demographics 页）
- 量表在 `LIKERT_SCALES` 列表中的顺序决定题目编号顺序
- `title` 参数是学术变量名（仅在 CSV 导出中使用，参与者看不到）
- `display_title` 参数是显示给参与者的中性标题。设为空字符串 `""` 则不显示标题（推荐，避免暴露研究意图）
- 非标准题型（如 `manip_check` 的 3 选项、`ai_usage` 的锚定标签）在 `CUSTOM_ITEMS` 中定义，模板手动渲染
- **注意**：添加新的 Python `Step` enum 值时（如新增页面步骤），Alembic autogenerate 不会检测 PostgreSQL ENUM 变更，需要手动创建迁移（`ALTER TYPE step ADD VALUE IF NOT EXISTS 'new_value'`）

#### 4.1 配对机制

**所有人**阅读说明后都进入等候室（HMC 不是“跳过等待”）。

- **Round 1 HMC**：虚假等候室（随机 5–15 秒），然后与 AI 聊天。身份由 `partner_label` 决定（MyBot 或伪装 Tommy）。
- **Round 1 HHC**：进入真人配对队列。120 秒内匹配成功 → 与真人聊；超时 → 回退 HMC（`hhc_fallback=True`，**`partnership` 改写为 HMC**），仍按 `partner_label` 显示身份。
- **Round 2（所有人）**：都尝试真人配对（按 `task_type` 分组，不按 `partner_label`）。不会与 Round 1 的同一 partner 再配。
  - 匹配成功 → 真人聊天（UI 显示对方真实昵称/头像）
  - 120 秒超时 → 回退 HMC，**强制 MyBot**；`partnership` **不改写**（保留 ITT 分组）；实际模态看该轮 `ChatRoom.room_type`
- 两轮任务类型相同：`task_type` 只在 Consent 时分配一次。

#### 4.2 聊天控制

| 参数 | 值 | 说明 |
|------|-----|------|
| 最少轮数 | 5 | 5 轮前不能结束聊天 |
| 最多轮数 | 15 | 达到 15 轮自动结束 |
| 最长时间 | 600 秒 | 超时自动结束 |

> **v2.2 更新**: HHC 聊天的 turn 计数改为 per-participant 模式：1 turn = 双方各自至少发送 1 条消息（`complete_turns = min(A_count, B_count)`）。例如 A 发 3 条 B 发 1 条 = 1 turn，A 发 2 条 B 发 2 条 = 2 turns。

聊天界面显示实时计时器和消息计数，"End Chat" 按钮在达到最少轮数后才可点击。

若计时结束或对方离开、且未满 `min_turns`，会出现居中对话框：**Yes, Continue** 回到本轮说明重新配对；**No, Leave** 标记 `is_dropout=True` 并退出。刷新页面后对话框仍在（服务端按剩余时间计算）。

#### 4.3 条件分配

使用最小配额策略（min-quota），始终将新参与者分配到人数最少的条件，保证 2×2×2 均衡。

8 个条件：
1. emotionTask × HHC × chatbot
2. emotionTask × HHC × human
3. emotionTask × HMC × chatbot
4. emotionTask × HMC × human
5. functionTask × HHC × chatbot
6. functionTask × HHC × human
7. functionTask × HMC × chatbot
8. functionTask × HMC × human

### 5. 页面恢复 / Page Recovery

系统基于 `participant.current_step` 实现页面恢复：
- 参与者刷新页面或关闭后重新打开，自动跳转到当前步骤
- 无需担心浏览器关闭导致数据丢失
- WebSocket 断开后自动重连（指数退避，最多 5 次），重连后恢复聊天历史

### 6. 安全措施

| 措施 | 说明 |
|------|------|
| Prolific ID 加密 | Fernet 存密文 + HMAC-SHA256 去重索引（无需逐行解密） |
| 聊天消息消毒 | 使用 bleach 防止 XSS 攻击 |
| Admin 会话认证 | 单密码 + Redis Session (24h TTL)，所有页面强制检查登录状态 (v1.8) |
| 欺骗一致性保护 | 对方离开通知使用欺骗条件对应的显示名，不暴露真实身份 (v2.2) |
| Cookie 安全 | HttpOnly 标志，防止 JS 读取 |
| Survey 量表验证 | Scale registry + `validate_likert_fields()` 限制值为 1-7；`display_title` 隐藏学术变量名，防止参与者看到研究意图 (v2.3) |
| Redis 连接池 | 共享连接池，防止连接耗尽 (v1.1) |
| 原子化匹配 | Lua 脚本防止竞态条件 (v1.1) |

### 7. 常见问题 / Troubleshooting

#### Q: 启动报错 "relation does not exist"

```bash
alembic upgrade head
```

#### Q: Redis 连接失败

```bash
docker-compose ps  # 检查 Redis 是否运行
docker-compose restart redis
```

#### Q: 参与者说看不到聊天消息

检查 WebSocket 连接。在浏览器开发者工具 Console 中查看是否有 WebSocket 错误。

#### Q: LLM 没有回复

1. 检查 `.env` 中 `N1N_API_KEY` + `LLM_API_BASE`，或 `OPENAI_API_KEY`
2. 查看日志：主 provider 失败时会自动尝试备用 provider（如果配置了 `LLM_BACKUP_API_BASE`）
3. 检查管理后台 Config 中 `default_model` 是否正确
4. CHARACTER_PROMPT 无需手动配置（内置默认值），但可以自定义
5. 查看 uvicorn 日志中是否有 LLM 错误
6. LLM 全部失败时会返回兜底回复："I'm sorry, I'm having trouble responding right now."

#### Q: Welcome 页提示无法保存 Prolific ID

服务器必须配置有效的 Fernet `ENCRYPTION_KEY`。若库里已有数据，**不要重新生成**密钥（旧密文无法解密）。测试可用任意 24 位字母数字 ID，系统不会向 Prolific 核验。

#### Q: HHC 匹配不成功

1. 需要**至少两个 HHC 参与者同时在线**才能匹配
2. 如果只有一个参与者，等待 120 秒后会自动回退为 HMC
3. 检查 Redis 是否正常运行

#### Q: 部署到 HTTPS 后 HHC 等待室连接失败

已修复：WebSocket URL 会自动适配 `ws://` 和 `wss://` 协议。

#### Q: 如何重置实验数据？

```bash
# 删除所有数据并重新迁移
alembic downgrade base
alembic upgrade head
```

### 8. 部署到 Render / Deploy to Render

#### 8.1 准备

1. 将项目推送到 GitHub
2. 在 Render 上用 Blueprint 导入本仓库（推荐），或手动创建 Web Service

#### 8.2 Render 配置

当前 `render.yaml`：**Web = Free**，**Redis (Key Value) = Free**，Postgres 在 yaml 里也写了 Free（Free Postgres **创建后 30 天过期**，正式收数请用 Starter）。

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `PYTHONPATH=. alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
- **Runtime**: Python **3.12**
- **Health check**: `/health`
- **Workers**: 必须为 **1**（WebSocket 不能多进程）

`DATABASE_URL` 必须在 Dashboard 手动填 **Internal Connection String**（含密码，不要提交到 Git）。`REDIS_URL` 由 `conexperiment-redis` 自动注入。

#### 8.3 环境变量

在 Render Dashboard → Environment 中设置：

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | Postgres **Internal** 连接串（手动） |
| `REDIS_URL` | 通常自动注入 |
| `SECRET_KEY` | 会话密钥 |
| `LLM_API_BASE` / `N1N_API_KEY` | 主 LLM 网关（或改用 `OPENAI_API_KEY`） |
| `LLM_BACKUP_*` | 可选备用 LLM |
| `ENCRYPTION_KEY` | Fernet；有数据后不要轮换 |
| `ADMIN_PASSWORD_HASH` | 管理员密码 SHA256 |
| `PROLIFIC_COMPLETION_URL` | 正式上线时再填 |
| `DEBUG` | `false` |
| `DEMO_MODE` | 正式收数必须 `false` |

#### 8.4 Redis 与 Postgres

- Redis：Blueprint 会创建 `conexperiment-redis`。Free 实例**不落盘**，重启会丢队列/会话。
- Postgres：建议 **Starter**（同区域），把 Internal URL 填进 Web 的 `DATABASE_URL`。Free 库 1 GB、30 天过期、无备份。

#### 8.5 同时在线人数（按 Render 套餐估算）

平台必须 **单 worker**，容量主要卡在 **CPU/内存、Redis 连接数、LLM 并发**，不是“网页能开多少个标签”。

应用侧硬限制：

| 限制 | 数值 | 含义 |
|------|------|------|
| uvicorn workers | 1 | 所有人共用一个事件循环 |
| Redis 共享池 | 最多 20 条 | 排队、会话、监控 |
| 聊天 Pub/Sub | **每人一条独立 Redis 连接** | 人在聊天室里才会占用 |
| LLM 信号量 | 30 | 同时最多 30 个 AI 回复在飞 |
| DB 连接池 | 20+30 | 一般不是瓶颈 |

Render 官方套餐（与本项目相关）：

| 组件 | Free | Starter（建议正式收数） |
|------|------|-------------------------|
| Web | 512 MB / **0.1 CPU**；闲置 15 分钟休眠；冷启动约 1 分钟；每月 750 小时 | 512 MB / **0.5 CPU**；常驻 |
| Redis | 25 MB / **50 连接**；不持久化 | 256 MB / **250 连接**；可持久化 |
| Postgres | 256 MB / 100 连接 / 1 GB / **30 天过期** | 付费、可备份 |

**估多少人同时在线（经验值，不是 SLA）：**

| 部署 | 正在聊天 / 等候室 | 整场实验中（多数在问卷页） | 说明 |
|------|-------------------|----------------------------|------|
| **当前 yaml：三件套全 Free** | 约 **20–30** | 约 **50–80** | Redis 50 连接：共享池约 20 + 聊天约 30。0.1 CPU 在多人同时发消息时会卡。**不适合正式 Prolific 放量。** |
| Web Starter + Redis Starter + Postgres Starter | 约 **80–120** | 约 **150** | Redis 250 连接够用；HMC 仍受 LLM 30 并发限制；512 MB 内存不宜再堆大量 WebSocket |
| Web Standard（2 GB / 1 CPU）+ Redis Standard | **150+** | 200+ | 适合一次放 100+ 人；仍保持 `--workers 1` |

补充：

- **HMC**：30 人同时等 AI 回复是设计上限；再多会排队，聊天变慢。
- **HHC**：同一 `task_type` 队列里至少要有两人才能配上；奇数个会有人等到超时后进 AI。
- **问卷页**几乎不占 Redis 专用连接，所以“在实验里”可以比“在聊天里”多。
- Free Web **休眠**：Prolific 第一人会碰到约 1 分钟加载页，后续人还好；中途 15 分钟没流量又会睡。
- Free Redis **重启丢数据**：正在排队的人可能匹配失败，需刷新。
- 这是**同时在线**，不是总样本量。总人数主要受 Postgres 磁盘和 LLM 费用限制。

**正式收数建议**：Web Starter（避免休眠）+ Redis Starter + Postgres Starter；Prolific 分批放人（Starter 上每批约 40–80 人更稳）。当前 Free 只适合自己点开测试。

---

## English Version

### 1. Setup

#### 1.1 Install Dependencies

```bash
cd ConExperiment2.0
pip install -r requirements.txt
```

#### 1.2 Start Infrastructure

```bash
docker-compose up -d
docker-compose ps  # verify services are running
```

#### 1.3 Configure Environment

```bash
cp .env.example .env
# Edit .env with required values (see Chinese version for generation instructions)
```

Required `.env` variables:
- `SECRET_KEY`: Random string
- `DATABASE_URL`: PostgreSQL connection string (driver prefix auto-converted)
- `REDIS_URL`: Redis connection string
- `ENCRYPTION_KEY`: Fernet key (required on Welcome; do not rotate if data exists)
- `ADMIN_PASSWORD_HASH`: SHA256 hash of admin password
- Primary LLM: `N1N_API_KEY` + `LLM_API_BASE`, **or** `OPENAI_API_KEY`

Optional `.env` variables (backup LLM provider, auto-fallback on primary failure):
- `LLM_BACKUP_API_BASE`: Backup API base URL
- `LLM_BACKUP_API_KEY`: Backup API key
- `LLM_BACKUP_MODEL`: Backup model name (default: `gpt-4o-mini`)

#### 1.4 Avatars and Priming Images

`static/avatar/` already contains the production PNG/JPG files. No copy from v1 is required.

| File | Use |
|------|-----|
| `myBot.png` | AI partner (MyBot); not selectable |
| `fox.png` | Tommy (fake human) and selectable avatar |
| `lion.png` / `rabbit.png` / `tiger.png` | Selectable participant avatars |
| `img_sad.png` | Emotion-task priming image |
| `img_box.jpg` | Function-task priming image |

#### 1.5 Database Migration

The repo already includes the migration chain. On a new environment run only:

```bash
alembic upgrade head
```

Do **not** run `alembic revision --autogenerate -m "initial"` against an existing database. Generate a new revision only after you change models.

#### 1.6 Start Development Server

```bash
python main.py run --reload
# or
uvicorn main:app --reload --port 8000
```

URLs:
- Experiment: http://localhost:8000
- Health: http://localhost:8000/health
- API Docs: http://localhost:8000/docs
- Admin: http://localhost:8000/admin/login

```bash
pip install -r requirements-dev.txt
pytest -q
```

#### 1.7 First-Run Configuration

All 4 CHARACTER_PROMPT values have built-in defaults. The Config page can override them at any time (clear a field to restore the default).

#### 1.8 Project Structure

See the Chinese **§1.8** for the same tree. Short map:

| Path | Role |
|------|------|
| `main.py` | FastAPI entry, routers, lifespan, CLI |
| `config.py` | Settings from env (chat limits, LLM, demo mode) |
| `database.py` | Async SQLAlchemy engine (pool 20+30) |
| `models/` | Tables: participant, chat, survey, experiment events |
| `schemas/` | Pydantic validation |
| `dependencies/` | Shared session helpers (load participant from cookie) |
| `routers/experiment.py` | Consent, welcome, priming, instructions, payment, resume |
| `routers/survey.py` | Survey prompt + pages A/B/C + demographics |
| `routers/chat.py` | Chat UI, pairing confirmed, chat WebSocket, retry/dropout |
| `routers/ws.py` | Matchmaking WebSocket (real HHC queue / fake HMC wait) |
| `routers/admin/` | Login, dashboard, participants, export, config, test tools |
| `services/matchmaking.py` | Redis queues, 120s fallback, dequeue on idle timeout |
| `services/llm.py` | litellm, semaphore (30), fallback reply, R1→R2 context |
| `services/redis_pubsub.py` | Per-chat dedicated Redis pub/sub connection |
| `services/prolific.py` | 24-char ID check, HMAC dedup, completion callback |
| `services/scales.py` | Likert registry (add scales here + `models/survey.py`) |
| `services/export.py` | Wide/long CSV + quality flags |
| `services/monitoring.py` | Events, stuck detection, `is_timeout` + queue removal |
| `templates/` | ~16 experiment pages + 8 admin pages + Likert macros |
| `static/` | CSS, `chat.js`, avatars |
| `tests/` | Condition assignment, flow, Prolific, export |
| `alembic/` | Schema migrations |
| `render.yaml` | Blueprint; set `DATABASE_URL` in Dashboard only |

### 2. Admin Dashboard

#### 2.1 Login

Visit `/admin/login` and enter the admin password configured in `.env`. Sessions last 24 hours.

#### 2.2 Dashboard

Overview of experiment status, **auto-refreshing every 5 seconds**:
- Total / Completed / Active / In-Chat participant counts
- **LLM Stats**: total calls + error rate (blue cards, 5s refresh)
- Condition distribution across all 8 conditions
- **Step Distribution table**: shows current step distribution of active participants
- **Active Chat Rooms monitor**: real-time display of all in-progress chat rooms
  - HHC rooms grouped by shared room_id, showing both participants
  - HMC rooms shown individually with participant info
  - Color-coded room type badges (HHC: blue, HMC: orange)
  - Real-time duration calculation
  - **"Peek" button**: click to expand inline chat preview (last 10 messages)
- **Active Participants**: mini progress bars for each active participant (blue <40%, orange 40-80%, green >80%)
- **Event Feed**: real-time scrolling event log (3s poll), showing match/timeout/LLM/survey events
- **Stuck Participant Warning**: yellow banner when participants exceed step time limits

#### 2.3 Participants

View all participants with:
- Condition assignments (taskType, partnership, partnerLabel)
- Current step + **color-coded progress bar** (13-step percentage)
- Status badges (Finished / Active / Timeout)
- **"View" link** to participant detail page

#### 2.3.1 Participant Detail (`/admin/participant/{display_id}`) — v2.0 new

Full participant observation page:
- Condition badges + status indicators
- **Resume URL**: copyable link to resume participant session
- **13-step progress bar** with highlighted current position (consent → … → payment)
- **Step Duration History**: from/to/duration/limit/over-limit per step
- **Chat History**: collapsible per room, auto-refresh for active rooms
- **Survey Responses**: all questionnaire answers
- **Event History**: recent events for this participant

#### 2.4 Config Editor

| Key | Description | Default |
|-----|-------------|---------|
| `CHARACTER_PROMPT_A` | Emotion task + MyBot (AI) system prompt | Built-in (v1.2) |
| `CHARACTER_PROMPT_Afake` | Emotion task + Tommy (fake human) system prompt | Built-in (v1.2) |
| `CHARACTER_PROMPT_B` | Function task + MyBot (AI) system prompt | Built-in (v1.2) |
| `CHARACTER_PROMPT_Bfake` | Function task + Tommy (fake human) system prompt | Built-in (v1.2) |
| `default_model` | LLM model name | `gpt-4o-mini` |
| `min_turns` | Min turns before End Chat is enabled | `5` |
| `max_turns` | Max turns (auto-end) | `15` |
| `max_duration` | Max chat duration in seconds | `600` |

**Note**: All 4 CHARACTER_PROMPT values have built-in defaults from ConExperiment v1. Clear a field in Config to restore its default. Changes take effect immediately.

#### 2.5 Data Export

Two CSV formats:

1. **Participant Wide Table** (`participants.csv`): One row per participant with nickname, avatar, **per-round partners** (`partner_display_id_r1` / `partner_display_id_r2`; empty for HMC), survey responses, demographics, and chat stats (`chat_r*_room_type`).
2. **Chat Messages Long Table** (`chat_messages.csv`): One row per message with an Excel-safe UTC `timestamp` (before `text`), nickname, avatar, and the partner for **that room/round**.

> The old single `partner_display_id` column read `Participant.partner_id`, which Round 2 overwrites. Export now resolves partners from each round's shared HHC `room_id`.

> **v1.5 update**: Exports default to excluding test participants (`is_test=True`). Check "Include test participants" to include them.
>
> **Quality filters**: The wide table adds `chat_r1_over_max` / `chat_r2_over_max`. Checkboxes can exclude page/chat timeouts (`is_timeout`), dropouts (`is_dropout`), and chats that reached max duration. Incomplete chats that hit the timer are flagged `is_timeout=True`. Idle participants are removed from the matchmaking queue.

#### 2.6 Test Tools — v1.5 new, v1.7 enhanced

Visit `/admin/test-tools` for the following testing features:

**Demo Mode**:
- **Method 1 (Recommended)**: Start with CLI `python main.py run --demo`
- **Method 2**: Set `DEMO_MODE=true` in `.env` and restart the server
- Reduced turns (2–5), shorter timeouts (10s HHC matching / **300s** chat), Prolific checks skipped
- Ideal for presentations and quick testing

**Quick Actions Bar** — v1.7 new:
Three one-click buttons at the top of the page:

1. **Quick Create (HMC, instructions_r1)**: One-click HMC test participant. Fastest for single-participant testing.
2. **Matchmaking Flow Test (HHC)**: Creates 2 HHC participants at instructions_r1. Open both in separate incognito windows to test full flow: instructions → waiting room → real matchmaking → chat.
3. **Quick Create HHC (Pair at Chat)**: Creates 2 HHC participants pre-matched at chat step. Open both URLs to immediately start chatting.

**Test Participant Dashboard** — v1.7 new:
- Table showing all test participants: Display ID, Nickname, Task, Partnership, Current Step, Round
- **Inline actions** per participant: Open / Next >> / Delete
- Step values color-coded: chat (orange), instructions (blue), survey (purple)
- Auto-refreshes after create/delete/step operations

**Step Control**:
- Jump any participant to a specific step. Dropdown selector auto-populated with test participants.
- Auto-creates HMC ChatRoom when jumping to a chat step

**Advanced Tools** (collapsible section):
- **Create Test Participant (Custom)**: specify conditions, start step, nickname, avatar. After Consent, those conditions are **kept** (min-quota does not re-assign)
- **HHC Queue Status**: view/clear matchmaking queues

**Test Data Management**:
- Delete single: inline "Delete" button in dashboard table (with confirmation)
- Delete all: "Delete All Test Data" button at page bottom
- Cascading cleanup: partner references, Redis queues, chat/survey/session records

### 3. Prolific Integration

#### 3.1 Experiment URL

```
https://your-domain.com/?PROLIFIC_PID={{%PROLIFIC_PID%}}&SESSION_ID={{%SESSION_ID%}}&STUDY_ID={{%STUDY_ID%}}
```

#### 3.2 Completion Callback

Set `PROLIFIC_COMPLETION_URL` in `.env` to the callback URL provided by Prolific.

> **Note (v1.1)**: The system sends completion callbacks in JSON format (`json=`) with a 10-second HTTP timeout. If Prolific requires form-encoded data, change `json=` back to `data=` in `services/prolific.py`.

The Welcome page also accepts a typed Prolific ID. It must be **exactly 24 alphanumeric characters**. A fake 24-character ID is enough for testing; Prolific is not called to verify it.

#### 3.3 Duplicate Detection

Duplicates are detected via HMAC-SHA256 (`prolific_id_hash`) without decrypting every row. The same Prolific ID cannot participate twice. Demo mode skips this check.

### 4. Experiment Flow

```
Consent → Welcome → Priming → R1 Instructions → Waiting → Chat → R2 Instructions → Waiting → Chat → Survey prompt + A/B/C + Demographics → Payment
```

#### 4.1 Pairing

**Everyone** goes to a waiting room after instructions (HMC does not skip it).

- **Round 1 HMC**: Fake wait (5–15s), then AI chat. Identity follows `partner_label` (MyBot or fake Tommy).
- **Round 1 HHC**: Real queue. Match within 120s or fallback to HMC (`hhc_fallback=True`, **`partnership` rewritten to HMC**). Display still follows `partner_label`.
- **Round 2 (everyone)**: Try real HHC (queued by `task_type` only). The Round 1 partner is excluded.
  - Match → human chat (real nickname/avatar)
  - 120s timeout → HMC with **forced MyBot**; **`partnership` is not rewritten** (ITT); actual modality is `ChatRoom.room_type`
- Both rounds use the same `task_type` (assigned once at Consent).

#### 4.2 Chat Controls

| Parameter | Value | Description |
|-----------|-------|-------------|
| `min_turns` | 5 | Cannot end chat before 5 turns |
| `max_turns` | 15 | Chat auto-ends at 15 turns |
| `max_duration` | 600s | Chat auto-ends on timeout |

> **v2.2 update**: HHC chat turn counting now uses per-participant mode: 1 turn = both participants each send at least 1 message (`complete_turns = min(A_count, B_count)`). E.g., A sends 3, B sends 1 = 1 turn; A sends 2, B sends 2 = 2 turns.

If the timer ends or the partner leaves before `min_turns`, a dialog appears: **Yes, Continue** returns to this round’s instructions; **No, Leave** sets `is_dropout=True`. The dialog is computed on the server, so it survives refresh.

#### 4.3 Condition Assignment

Min-quota strategy: always assigns to the condition with fewest participants.

### 5. Page Recovery

- Participants auto-redirect to their current step on page refresh
- WebSocket auto-reconnects (exponential backoff, max 5 attempts)
- Chat history restored from DB on reconnect

### 6. Security

| Measure | Description |
|---------|-------------|
| Prolific ID encryption | Fernet ciphertext + HMAC-SHA256 index for dedup |
| Chat message sanitization | bleach XSS prevention |
| Admin session auth | Single password + Redis session (24h TTL), all pages enforce login check (v1.8) |
| Deception consistency | Partner left notification uses deception-correct display name, never exposes real identity (v2.2) |
| Cookie security | HttpOnly flag |
| Survey scale validation | Scale registry + `validate_likert_fields()` restricts values to 1-7; `display_title` hides academic variable names from participants (v2.3) |
| Redis connection pool | Shared pool prevents connection exhaustion (v1.1) |
| Atomic matching | Lua script prevents race conditions (v1.1) |

### 7. Troubleshooting

| Issue | Solution |
|-------|----------|
| "relation does not exist" | Run `alembic upgrade head` |
| Redis connection failed | `docker-compose restart redis` |
| LLM not responding | Check `N1N_API_KEY` + `LLM_API_BASE` (or `OPENAI_API_KEY`); fallback provider if configured |
| Welcome cannot save Prolific ID | Set a valid Fernet `ENCRYPTION_KEY`; do not rotate if data exists. Fake 24-char IDs work for tests |
| HHC not matching | Requires 2+ HHC participants in the same task-type queue |
| WebSocket errors | Check browser console for errors |
| HTTPS WebSocket fails | Already fixed — protocol auto-detection (ws/wss) |
| Reset all data | `alembic downgrade base && alembic upgrade head` |

### 8. Deploy to Render

#### 8.1 Prerequisites

- GitHub repository with this code
- Render account

#### 8.2 Web Service Settings

Current `render.yaml`: **web Free**, **Redis Free**, Postgres listed as Free (Free Postgres **expires after 30 days** — use Starter for real collection).

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `PYTHONPATH=. alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
- **Runtime**: Python **3.12**
- **Health check**: `/health`
- **Workers**: MUST be **1** (WebSocket)

Set `DATABASE_URL` to the Postgres **Internal Connection String** in the Dashboard (do not commit it). `REDIS_URL` is injected from `conexperiment-redis`.

#### 8.3 Environment Variables

Set in Render Dashboard → Environment:
- `DATABASE_URL` (Internal URL, manual)
- `REDIS_URL` (usually auto)
- `SECRET_KEY`, `ENCRYPTION_KEY`, `ADMIN_PASSWORD_HASH`
- `LLM_API_BASE`, `N1N_API_KEY` (or `OPENAI_API_KEY`)
- `LLM_BACKUP_API_BASE`, `LLM_BACKUP_API_KEY` (optional)
- `PROLIFIC_COMPLETION_URL` (optional until go-live)
- `DEBUG=false`, `DEMO_MODE=false` for real data collection

#### 8.4 Redis and Postgres

- Free Redis is in-memory only (queues/sessions vanish on restart).
- Prefer **Starter** Postgres in the same region as the web service.

#### 8.5 Concurrent Capacity (Render plans)

The app runs **one worker**. Capacity is limited by CPU/RAM, **Redis connections**, and the LLM semaphore — not by “how many tabs can open.”

App limits: Redis shared pool ≤ 20; **each person in chat uses one extra Redis pub/sub connection**; `LLM_MAX_CONCURRENT=30`; DB pool 20+30.

| Deploy | In chat / waiting | In the study (mostly survey pages) | Notes |
|--------|-------------------|--------------------------------------|-------|
| **Current yaml (all Free)** | ~**20–30** | ~**50–80** | Free Redis = **50 connections** (≈20 pool + ≈30 chats). Web is 0.1 CPU and **spins down after 15 min idle**. **Not for live Prolific.** |
| Starter web + Starter Redis + Starter Postgres | ~**80–120** | ~**150** | Redis 250 connections; HMC still capped at 30 simultaneous LLM calls; 512 MB RAM |
| Standard web (2 GB / 1 CPU) + Standard Redis | **150+** | 200+ | For launching 100+ people at once; still `--workers 1` |

HMC: at most 30 AI replies in flight. HHC: pairing needs two people in the same `task_type` queue. Survey pages barely use dedicated Redis connections, so “in the experiment” can exceed “in chat.” Concurrent ≠ total sample size.

**For real collection:** Starter web (always-on) + Starter Redis + Starter Postgres; release Prolific in batches (~40–80 on Starter). Use Free only for your own tests.

---

## File Reference / 文件索引

Full descriptions: Chinese **§1.8**. Summary:

| File | Purpose |
|------|---------|
| `main.py` | FastAPI entry + CLI |
| `config.py` | Settings from env |
| `database.py` | SQLAlchemy async engine |
| `models/` | ORM (participant, chat, survey, experiment) |
| `services/` | Matchmaking, LLM, export, Prolific, scales, monitoring |
| `routers/` | Experiment, chat, survey, ws, `admin/` sub-routers |
| `schemas/` | Pydantic models |
| `dependencies/` | Participant session helpers |
| `templates/` | ~16 experiment + 8 admin pages + Likert macros |
| `static/` | CSS, `chat.js`, avatar PNGs |
| `tests/` | pytest |
| `alembic/` | Migrations |
| `render.yaml` | Render Blueprint |
| `docker-compose.yml` | Local PostgreSQL + Redis |
| `.env.example` | Env template (never commit `.env`) |

# USER_GUIDE.md — ConExperiment 2.0 使用指南 / User Guide

**版本**: v2.3.0 (2026-05-25)

### 版本更新记录

| 版本 | 更新内容 |
|------|---------|
| v2.3.0 | **问卷 Scale Registry 重构 + Outcome Variables 页面 + UI 优化**：新增 `services/scales.py` 量表注册表 + `templates/macros/likert.html` Jinja2 宏；新增 Survey Page C 包含 25 个 outcome variable 量表（80 题）；修复 PostgreSQL ENUM 缺失 `survey_c` 导致的 500 错误；`display_title` 字段隐藏学术变量名（参与者看不到 "Agency" 等术语）；Likert 量表 CSS 重写（等间距 + 选中高亮 + 锚定文字） |
| v2.2.0 | **HHC Turn 计数修复 + 欺骗泄露修复**：HHC 聊天 turn 改为 per-participant 计数（`min(A_count, B_count)`，每人至少发 1 条才算 1 turn）；对方离开聊天时 `partner_left` 通知不再暴露真实身份（使用欺骗条件对应的显示名） |
| v2.1.0 | **HHC DB session 修复 + generation counter 修复**：`listen_redis` 使用独立 DB session 防止 cross-contamination；BUG-21 `.decode()` 修复使 stale handler 检测恢复生效；诊断日志增强 |
| v2.0.x | **Bug 修复轮次**：HMC 虚假配对错误、HHC max-turns 通知横幅、R2 HHC 真实匹配显示、JS 语法错误（`tojson` 过滤） |
| v2.0.0 | **监控增强**：参与者恢复链接（`/resume/{token}`）、Dashboard 进度条、步骤停留时长追踪、实时事件流、LLM 调用监控（成功率/延迟）、聊天内容实时预览、卡住参与者自动检测、参与者详情页 |
| v1.8.0 | **UI 优化 + 安全修复**：聊天框上方添加对话说明提醒条；对方头像逻辑更新（human 标签使用用户自己的 avatar）；Instructions 页面移除头像显示；HHC 超时回退时 partnership 改为 HMC；**Admin 认证修复**（未登录无法访问管理页面）；启动时显示 Admin dashboard 链接 |
| v1.8.0 | **UI 优化 + 安全修复**：聊天框上方添加对话说明提醒条；对方头像逻辑更新（human 标签使用用户自己的 avatar）；Instructions 页面移除头像显示；HHC 超时回退时 partnership 改为 HMC；**Admin 认证修复**（未登录无法访问管理页面）；启动时显示 Admin dashboard 链接 |
| v1.7.0 | **Admin 界面优化 + HHC 聊天修复**：Dashboard 5s 自动刷新、活跃聊天室实时监控、步骤分布表；Test Tools 快捷操作栏（一键创建、配对流程测试）、测试被试仪表板（内联 Open/Next/Delete 操作）；**HHC 聊天消息不显示修复**（redis-py 5.x API 兼容 + 频道名前缀 + sender_role 翻转） |
| v1.6.0 | **配对机制重大修复**：第一轮 HMC 虚假等候室、第二轮统一真人配对尝试、第二轮回退强制显示 BOT 身份、WebSocket 断线竞态修复、display_id 生成修复（避免删除后重复） |
| v1.5.1 | 测试数据管理：删除单个测试被试、一键清理所有测试数据、测试数据计数显示 |
| v1.5.0 | 测试与演示工具：Demo Mode 配置、Admin Test Tools 页面（创建测试被试、一键 HHC 配对、步骤控制、队列查看）、数据导出自动过滤测试数据、is_test 标记 |
| v1.4.0 | 综合测试修复：HHC 断连队列清理、三人竞争孤儿修复、LLM 超时增至 60s、Survey 范围校验、完成后重定向 payment、服务端 min_turns、WebSocket JSON 容错、HHC fallback 标签统一 |
| v1.3.1 | 修复：Priming 页面恢复任务图片；Chat 结束后 POST 导航修复（405 错误）；Admin 侧栏留白修复 |
| v1.3.0 | 首轮测试修复：Admin 登录、Consent 对齐 v1、Avatar 选择反馈、Priming 页面、HHC 匹配机制 |
| v1.2.0 | 预部署配置：备用 LLM provider、内置默认 prompt、导入修复、.env 预配置 |
| v1.1.0 | 基础设施优化：Redis 连接池、原子化匹配、Pub/Sub 重连、Prolific 回调优化 |
| v1.0.0 | 初始版本 |

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
# - OPENAI_API_KEY: OpenAI API 密钥（主 LLM provider）
# - ENCRYPTION_KEY: Fernet 密钥（见下方生成方法）
# - ADMIN_PASSWORD_HASH: 管理员密码的 SHA256 哈希（见下方生成方法）
#
# 可选配置（备用 LLM provider，主 provider 失败时自动切换）：
# - LLM_BACKUP_API_BASE: 备用 API 地址（如 https://api.chatanywhere.tech/v1）
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

#### 1.4 替换占位头像

```
static/avatar/ 目录中的文件是 SVG 占位图，需要替换为真实图片：

需替换的文件（从 v1 项目 ../ConExperiment/_static/avatar/ 复制）：
- myBot.png → AI 对话伙伴头像
- fox.png → Tommy（伪装人类）头像，同时也是可选参与者头像
- lion.png → 可选参与者头像
- rabbit.png → 可选参与者头像
- tiger.png → 可选参与者头像

从 v1 项目 ../ConExperiment/_static/task1/img/ 复制：
- img_sad.png → 情绪任务热身图片
- img_box.jpg → 功能任务热身图片
```

#### 1.5 数据库迁移

```bash
# 生成迁移脚本
alembic revision --autogenerate -m "initial"

# 执行迁移
alembic upgrade head
```

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
- API 文档：http://localhost:8000/docs
- 管理后台：http://localhost:8000/admin/login

#### 1.7 首次运行配置

> **v1.2 更新**: 4 个 CHARACTER_PROMPT 已内置默认值（从 ConExperiment v1 迁移），无需手动配置即可直接测试。管理后台的 Config 页面可以随时覆盖默认值。

首次启动后的可选配置：

1. **登录管理后台** → `/admin/login`（使用 .env 中的管理员密码）
2. **（可选）自定义 LLM 提示词** → Config 页面中修改 4 个 CHARACTER_PROMPT（A/Afake/B/Bfake），留空则使用内置默认值
3. **确认模型配置** → `default_model` 默认为 `gpt-4o-mini`，可修改为 `claude-haiku-4-5` 等

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
- 当前步骤 + **彩色进度条**（12步进度百分比）
- 当前轮次
- 状态标签（Finished / Active / Timeout）
- HHC 回退状态
- 创建时间
- **"View" 链接**：点击进入参与者详情页

#### 2.3.1 参与者详情页 (`/admin/participant/{display_id}`) — v2.0 新增

查看单个参与者的完整信息：
- **条件标签**：taskType, partnership, partnerLabel 等彩色标签
- **Resume URL**：可复制的恢复链接，支持参与者恢复会话
- **12步进度条**：高亮当前步骤位置
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
- 包含：条件分配、问卷所有题项、人口统计、两轮聊天统计

**聊天长表** (`chat_messages.csv`)：
- 每行一条聊天消息
- 包含：参与者 ID、房间 ID、轮次、发送者角色、消息文本、时间戳

> **v1.5 更新**: 导出默认排除测试被试（`is_test=True`）。勾选 "Include test participants" 可包含测试数据。

#### 2.6 Test Tools（测试工具）— v1.5 新增，v1.7 优化

访问 `/admin/test-tools`，提供以下测试功能：

**Demo Mode（演示模式）**：
- **方法 1（推荐）**: 使用 CLI 启动 `python main.py run --demo`
- **方法 2**: 在 `.env` 中设置 `DEMO_MODE=true` 并重启服务器
- 效果：聊天轮次减少（2-5 轮），超时缩短（10s HHC 匹配 / 120s 聊天），Prolific 检查跳过
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
- **自定义创建被试**：指定条件、起始步骤、昵称、头像
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

#### 3.3 重复参与检测

系统自动检测 Prolific ID 重复。同一 Prolific ID 不能多次参与，会显示错误提示。

#### 3.4 完成码

参与者完成实验后，会看到形如 `CONEXP-P-0001` 的完成码，需在 Prolific 上输入以获取报酬。

### 4. 实验流程 / Experiment Flow

完整流程：

```
知情同意 → 头像昵称 → 热身写作 → 第1轮说明 → 聊天 → 第2轮说明 → 聊天 → 问卷(4页) → 完成
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

- **HMC（人机对话）**：参与者阅读说明后直接进入与 AI 的聊天
- **HHC（人人对话）**：参与者进入等待室，系统自动匹配（Redis 队列，每 3 秒检查一次）
  - 匹配成功：两人进入双人聊天（通过 WebSocket）
  - 120 秒未匹配：自动回退为 HMC（`partnership` 改为 HMC，与 AI 聊天，数据仍保留 `hhc_fallback=True` 标记）

#### 4.2 聊天控制

| 参数 | 值 | 说明 |
|------|-----|------|
| 最少轮数 | 5 | 5 轮前不能结束聊天 |
| 最多轮数 | 15 | 达到 15 轮自动结束 |
| 最长时间 | 600 秒 | 超时自动结束 |

> **v2.2 更新**: HHC 聊天的 turn 计数改为 per-participant 模式：1 turn = 双方各自至少发送 1 条消息（`complete_turns = min(A_count, B_count)`）。例如 A 发 3 条 B 发 1 条 = 1 turn，A 发 2 条 B 发 2 条 = 2 turns。

聊天界面显示实时计时器和消息计数，"End Chat" 按钮在达到最少轮数后才可点击。

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
| Prolific ID 加密 | 使用 Fernet 对称加密存储 |
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

1. 检查 `.env` 中 `OPENAI_API_KEY` 是否正确
2. 查看日志：主 provider 失败时会自动尝试备用 provider（如果配置了 `LLM_BACKUP_API_BASE`）
3. 检查管理后台 Config 中 `default_model` 是否正确
4. CHARACTER_PROMPT 无需手动配置（v1.2 内置默认值），但可以自定义
5. 查看 uvicorn 日志中是否有 LLM 错误
6. LLM 全部失败时会返回兜底回复："I'm sorry, I'm having trouble responding right now."

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
2. 在 Render 上创建新 Web Service

#### 8.2 Render 配置

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
- **Environment**: Python 3.11+
- **Workers**: 必须为 1（避免 WebSocket 跨进程问题）

#### 8.3 环境变量

在 Render Dashboard → Environment 中设置：
- `DATABASE_URL` (PostgreSQL 连接串，Render 会提供)
- `REDIS_URL` (Redis 连接串，使用 Render Redis 服务)
- `SECRET_KEY`
- `OPENAI_API_KEY`
- `ENCRYPTION_KEY`
- `ADMIN_PASSWORD_HASH`
- `PROLIFIC_COMPLETION_URL` (可选)
- `DEBUG` = `false`

#### 8.4 Redis 服务

Render 提供托管的 Redis 服务，创建后在环境变量中配置 `REDIS_URL`。

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
- `DATABASE_URL`: PostgreSQL async connection string
- `REDIS_URL`: Redis connection string
- `OPENAI_API_KEY`: Your OpenAI API key (primary LLM provider)
- `ENCRYPTION_KEY`: Fernet key (for Prolific ID encryption)
- `ADMIN_PASSWORD_HASH`: SHA256 hash of admin password

Optional `.env` variables (backup LLM provider, auto-fallback on primary failure):
- `LLM_BACKUP_API_BASE`: Backup API base URL (e.g., `https://api.chatanywhere.tech/v1`)
- `LLM_BACKUP_API_KEY`: Backup API key
- `LLM_BACKUP_MODEL`: Backup model name (default: `gpt-4o-mini`)

#### 1.4 Replace Placeholder Avatars

The `static/avatar/` directory contains SVG placeholders. Replace them with real images from the v1 project (`../ConExperiment/_static/avatar/`):

- `myBot.png` — AI partner avatar
- `fox.png` — Tommy (fake human) avatar / selectable participant avatar
- `lion.png`, `rabbit.png`, `tiger.png` — Selectable participant avatars
- `img_sad.png` — Emotion task priming image
- `img_box.jpg` — Function task priming image

#### 1.5 Database Migration

```bash
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

#### 1.6 Start Development Server

```bash
uvicorn main:app --reload --port 8000
```

URLs:
- Experiment: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Admin: http://localhost:8000/admin/login

#### 1.7 First-Run Configuration

> **v1.2 update**: All 4 CHARACTER_PROMPT values have built-in defaults (migrated from ConExperiment v1). No manual configuration needed to start testing. The Config page can override defaults at any time.

Optional configuration:
1. Login to Admin → `/admin/login`
2. (Optional) Customize LLM prompts in Config — clear a field to restore its built-in default
3. Verify `default_model` setting (default: `gpt-4o-mini`)

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
- Current step + **color-coded progress bar** (12-step percentage)
- Status badges (Finished / Active / Timeout)
- **"View" link** to participant detail page

#### 2.3.1 Participant Detail (`/admin/participant/{display_id}`) — v2.0 new

Full participant observation page:
- Condition badges + status indicators
- **Resume URL**: copyable link to resume participant session
- **12-step progress bar** with highlighted current position
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

1. **Participant Wide Table** (`participants.csv`): One row per participant with all survey responses, demographics, and chat stats.
2. **Chat Messages Long Table** (`chat_messages.csv`): One row per message with sender, text, timestamp.

> **v1.5 update**: Exports default to excluding test participants (`is_test=True`). Check "Include test participants" to include them.

#### 2.6 Test Tools — v1.5 new, v1.7 enhanced

Visit `/admin/test-tools` for the following testing features:

**Demo Mode**:
- **Method 1 (Recommended)**: Start with CLI `python main.py run --demo`
- **Method 2**: Set `DEMO_MODE=true` in `.env` and restart the server
- Reduced turns (2-5), shorter timeouts (10s HHC matching / 120s chat), Prolific checks skipped
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
- **Create Test Participant (Custom)**: specify conditions, start step, nickname, avatar
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

#### 3.3 Duplicate Detection

Duplicate Prolific IDs are automatically rejected with an error message.

### 4. Experiment Flow

```
Consent → Welcome → Priming → R1 Instructions → Chat → R2 Instructions → Chat → Survey (4 pages) → Payment
```

#### 4.1 Pairing

- **HMC**: Participant reads instructions → enters chat with AI immediately
- **HHC**: Participant enters waiting room → auto-matched via Redis queue (3s polling)
  - Match found: Both enter HHC chat via WebSocket
  - 120s timeout: Fallback to HMC (`partnership` changed to HMC, AI chat, data still has `hhc_fallback=True` flag)

#### 4.2 Chat Controls

| Parameter | Value | Description |
|-----------|-------|-------------|
| `min_turns` | 5 | Cannot end chat before 5 turns |
| `max_turns` | 15 | Chat auto-ends at 15 turns |
| `max_duration` | 600s | Chat auto-ends on timeout |

> **v2.2 update**: HHC chat turn counting now uses per-participant mode: 1 turn = both participants each send at least 1 message (`complete_turns = min(A_count, B_count)`). E.g., A sends 3, B sends 1 = 1 turn; A sends 2, B sends 2 = 2 turns.

#### 4.3 Condition Assignment

Min-quota strategy: always assigns to the condition with fewest participants.

### 5. Page Recovery

- Participants auto-redirect to their current step on page refresh
- WebSocket auto-reconnects (exponential backoff, max 5 attempts)
- Chat history restored from DB on reconnect

### 6. Security

| Measure | Description |
|---------|-------------|
| Prolific ID encryption | Fernet symmetric encryption at rest |
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
| LLM not responding | Check `OPENAI_API_KEY`; system auto-falls back to backup provider if configured; check uvicorn logs |
| HHC not matching | Requires 2+ HHC participants online simultaneously |
| WebSocket errors | Check browser console for errors |
| HTTPS WebSocket fails | Already fixed — protocol auto-detection (ws/wss) |
| Reset all data | `alembic downgrade base && alembic upgrade head` |

### 8. Deploy to Render

#### 8.1 Prerequisites

- GitHub repository with this code
- Render account

#### 8.2 Web Service Settings

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
- **Runtime**: Python 3.11+
- **Instance Type**: Free tier or higher
- **Workers**: MUST be 1 (WebSocket constraint)

#### 8.3 Environment Variables

Set in Render Dashboard → Environment:
- `DATABASE_URL` (provided by Render PostgreSQL)
- `REDIS_URL` (provided by Render Redis)
- `SECRET_KEY`, `OPENAI_API_KEY`, `ENCRYPTION_KEY`, `ADMIN_PASSWORD_HASH`
- `LLM_BACKUP_API_BASE`, `LLM_BACKUP_API_KEY` (optional, backup LLM provider)
- `PROLIFIC_COMPLETION_URL` (optional)
- `DEBUG=false`

---

## File Reference / 文件索引

| File | Purpose |
|------|---------|
| `main.py` | FastAPI entry point + admin middleware |
| `config.py` | Settings (env vars) |
| `database.py` | SQLAlchemy async engine |
| `models/` | ORM models (participant, chat, survey, experiment) |
| `services/` | Business logic (LLM, matchmaking, export, Prolific, scales) |
| `routers/` | Route handlers (experiment, chat, survey, admin, ws) |
| `schemas/` | Pydantic request/response models |
| `templates/` | Jinja2 HTML templates (12 experiment + 6 admin + macros) + Alpine.js |
| `static/css/main.css` | Complete CSS design system |
| `static/avatar/` | Avatar images (replace SVG placeholders with real files) |
| `alembic/` | Database migrations |
| `docker-compose.yml` | PostgreSQL + Redis for local dev |
| `.env.example` | Environment variable template |

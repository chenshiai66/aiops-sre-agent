# AIOps 故障处置 Agent

一个跑在**真实 Kubernetes 集群**上的故障处置 Agent。

它和大多数 Agent 项目的区别不在于用了多少技术，而在于：

> **它真的会在生产资源上动手，而且每动一次手都会回真实世界确认动没动成。**

不是 mock、不是模拟器 —— 每一个判断读的都是真集群，每一次处置改的都是真资源。

---

## 它做什么

```
告警进来
  → 查真实集群取证（实例就绪状态 / ReplicaSet 拓扑 / Deployment 发布状态）
  → 检索运维知识库（包括它自己以前写下的复盘）
  → 判断该不该动手、该动哪个
  → 需要人工放行就停下来等（interrupt + Redis checkpoint）
  → 真的执行（rollout restart / scale / rollback）
  → 轮询观测真实集群，确认恢复
  → 判定结局、通知人、把这次的结论写回知识库
```

**最后一步让它越用越好**：第二次遇到同类故障时，检索结果里排第一的
就是它自己上次写的复盘。

---

## 快速开始

### 前置要求

| | |
|---|---|
| Python | 3.12+ |
| Docker + kind | 本地 K8s 集群 |
| kubectl | |
| DashScope API Key | LLM + embedding 都用它 |

### ① 起依赖

```bash
docker compose up -d
```

Redis（6379）和 Qdrant（**6343**）起来。确认：

> ⚠️ Qdrant 的宿主端口是 **6343**，不是默认的 6333 ——
> 因为 6333 被本机另一个项目的 qdrant 占着（两边各用各的，互不干扰）。
> `.env` 里的 `QDRANT_URL` 要和 `docker-compose.yml` 保持一致。

```bash
docker compose ps
```

### ② 建集群 + 部署演示应用

```bash
# 建 kind 集群（名字必须是 aiops，后面的命令都按这个名字）
kind create cluster --name aiops

# 构建演示应用镜像
docker build -t aiops-demo-app:latest ./deploy/demo_app

# ★ 把镜像灌进 kind —— 集群里 imagePullPolicy: Never，不灌进去会 ImagePullBackOff
kind load docker-image aiops-demo-app:latest --name aiops

# 部署
kubectl apply -f ./deploy/k8s/namespace.yaml
kubectl apply -f ./deploy/k8s/order-svc.yaml

# 等三个 Pod 就绪
kubectl -n prod-order get pods -w
```

**期望**：三个 `1/1 Running`。

### ③ 配置

```bash
cp .env.example .env        # Windows: Copy-Item .env.example .env
```

填上 DashScope 的两个 key。字段说明见 `app/config.py`。

### ④ 灌知识库

```bash
python -m app.rag.indexer
```

**期望**：`重新索引 8 条`（7 条种子 + 可能的自动回写记录）。

> 这一步不能跳。索引为空的话，`retriever` 检索不到任何东西，
> 图会走到 `escalator` 直接转人工 —— 它不会瞎猜。

### ⑤ 起服务

```bash
python run_server.py
```

**期望**：

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

> ⚠️ **必须用 `run_server.py` 启动，不要直接跑 `app/main.py`。**
> 直接跑 `app/` 下的文件会把 `app/` 放进 `sys.path[0]`，
> 于是 `app/` 里的任何包名都会**遮蔽同名的第三方库**。
> 这个坑真踩过：`app/mcp/` 遮蔽了 `mcp` 库，而报错信息指向我们自己的文件。

---

## 演示前检查

**每次演示（或者每次重启服务）之前先跑一次**：

```powershell
cd D:\PythonProject\aiops-sre-agent
.\check_env.ps1
```

它检查四件事：

| 检查 | 为什么 |
|---|---|
| **端口 8000 有没有被占** | **最容易被忽略**——上一个服务没停，你会一直在跟一个**旧进程**说话 |
| python 进程有几个 | 正常只有 1 个（服务主进程）。多的可能是旧实例，或者**被强杀后留下的 MCP 子进程** |
| 集群 Pod 状态 | 确认 demo 应用是好的 |
| Redis / Qdrant 通不通 | |

**端口那一条最重要。** 因为它造成的症状是"**演示卡住**"或者"**改了代码却没生效**"，
而**真正的原因在另一个进程里**——你会顺着错误的方向查很久。

> **真踩过**：演示时命令卡住不动，查下来端口被一个**从来没被停过**的实例占着，
> 而我一直以为那是"刚才启动的那个"。
>
> **判断方法**：看那个进程的**启动时间**。如果比你以为的早很多，就是它。

**顺带一提**：PyCharm 的运行配置里可以勾 **"Single instance only"**
（`Run → Edit Configurations → run_server → Modify options`），
勾上之后再按 Run 会**自动停掉上一个实例**，就不会出现两个进程抢端口。

---

## 演示：两条路

演示应用有个开关 `START_BROKEN`，可以造出两种故障，**走两条不同的处置路径**。

> ⚠️ **下面给的是 PowerShell 写法**（这个项目的演示环境是 Windows）。两个容易踩的坑：
>
> - **`curl` 在 PowerShell 里是 `Invoke-WebRequest` 的别名**，它不认识 `-H` / `-d`。
>   要用真的 curl 请写 `curl.exe`
> - **`\` 换行是 bash 的写法**，PowerShell 用反引号 `` ` ``

### 路径 A：单个实例异常 → 自动重启（不需要审批）

```powershell
# 让某一个 Pod 的就绪探针开始失败
$POD = kubectl -n prod-order get pods -o jsonpath="{.items[0].metadata.name}"
kubectl -n prod-order exec $POD -- curl -s -X POST http://127.0.0.1:8000/break
```

```powershell
python -m app.scripts.smoke
```

**期望**：`action: restart_deployment`（`auto` 风险，直接执行）→ `outcome: resolved`。

### 路径 B：新版本整体失败 → 回滚（需要审批）

```powershell
# 改 Pod 模板 → 滚动更新 → 新版本的 Pod 起不来 → 发布会卡住
kubectl -n prod-order set env deployment/order-svc START_BROKEN=1

# 等 40 秒，确认卡住
kubectl -n prod-order get pods
```

**期望**：3 个旧 Pod `1/1`，1 个新 Pod `0/1`。

```powershell
python -m app.scripts.smoke
```

**期望**：停在审批点，`action: rollback_deployment`，`risk_level: approval`。

把打印出来的 `fault_id` 填进去：

```powershell
$fid  = "<从 smoke 输出复制，不要尖括号>"
$body = @{ approved = $true; by = "you"; comment = "确认回滚" } | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/faults/$fid/approve" `
  -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json
```

**期望**：`status: accepted` —— **批准也是异步的**，执行和 30 秒观测还在后台跑。

所以要轮询到它结束：

```powershell
do {
  Start-Sleep -Seconds 10
  $s = Invoke-RestMethod -Uri "http://127.0.0.1:8000/faults/$fid"
  "$($s.status)   outcome=$($s.outcome)"
} until ($s.status -eq "finished")
```

**期望**：`finished   outcome=resolved`。然后：

```powershell
kubectl -n prod-order get pods
```

**三个 Pod 全部 `1/1`，而且 AGE 几乎没变** —— 回滚是零中断的：
K8s 发现模板和已有的某个 ReplicaSet 一致，直接复用了它，
坏版本被悄悄缩到 0。

---

## 架构

### 八个节点

```
START → dispatcher → detector → retriever → remediator
                                                │
                        ┌───────────────────────┴───────────────┐
                   risk=auto                              risk=approval
                        │                                       │
                        ▼                                       ▼
                    executor  ◄─── 批准 ──────────────  escalator
                        │          （interrupt 暂停等人）   ▲
                        ▼                                  │
                      verify ──── 没修好 / 执行出错 ────────┘
                        │
                        └──→ reviewer → END
```

| 节点 | 干什么 |
|---|---|
| `dispatcher` | 归一化告警，**把逻辑服务名解析成真实工作负载名** |
| `detector` | 带工具循环的 ReAct 取证 + 结构化诊断 |
| `retriever` | Qdrant 检索（本服务 OR 通用手册） |
| `remediator` | 从白名单选动作，过参数校验和风险判定 |
| `executor` | **唯一会改集群的地方** |
| `verify` | 轮询观测，确认真的恢复了 |
| `escalator` | 人工介入的唯一入口（暂停等人 / 纯交接） |
| `reviewer` | 判定结局、通知、写回知识库 |

### 四道闸门

**代码可以否决模型** —— 这是整个设计的核心。

| 闸门 | 在哪 | 拦什么 |
|---|---|---|
| ① 动作白名单 | `remediation/actions.py` | 模型不能发明动作名 |
| ② 参数形状 | Pydantic `extra="forbid"` | 多传一个字段就拒 |
| ③ **资源名解析** | `remediation/executor.py` | **资源名从集群解析，不信模型填的**，不一致就拒 |
| ④ 风险等级取严 | `actions.stricter()` | 白名单和模型建议里取更保守的 |

**为什么第 ③ 道最重要**：告警里的 `demo-service` 是逻辑服务名，
而 K8s 里的 Deployment 叫 `order-svc`。模型很容易填错，
所以**执行器只信自己从 `ownerReferences` 解析出来的名字**。

### 目录结构

```
app/
  main.py              FastAPI 入口（受理 + 轮询 + 审批 + 通知查询）
  config.py            配置（pydantic-settings）
  llm.py               LLM 客户端
  k8s.py               ★ 和 K8s 打交道的唯一入口
  pending.py           待审批索引（Redis Set）
  notify.py            通知层（Redis List + 日志，幂等）
  mcp_client.py        MCP 客户端（长期持有会话）
  mcp_servers/         MCP server（被当作子进程拉起）
  graph/
    builder.py         图的组装
    state.py           状态定义
    outcome.py         ★ 结局判定（全局唯一一份）
    nodes/             八个节点
  rag/
    client.py          ★ Qdrant / embedding 客户端的唯一创建点
    retriever.py       检索
    indexer.py         索引
    seed.py            种子数据
    writeback.py       ★ 知识回写（自进化）
  remediation/
    actions.py         ★ 可执行动作白名单
    executor.py        ★ 最后一道闸门
    resolver.py        资源名解析
deploy/
  demo_app/            演示应用（有 /health 和 /break，读 START_BROKEN）
  k8s/                 namespace 和 Deployment 清单
```

---

## 几个刻意的设计

### 为什么用状态机，不用自主循环

运维要的是**可预测**，不是"智能"。

每一步都在 `audit` 里留痕、都能回放、都能被人工打断。
一个会自己决定下一步干什么的 Agent，在生产环境里是不可接受的。

### 为什么"命令成功"不等于"故障恢复"

`executor` 和 `verify` 是**两个节点**。

执行器只知道"我把请求发出去了"；确认恢复必须**重新观测真实集群**——
`verify` 会轮询 Pod 就绪状态最多 30 秒。

项目里真实发生过：执行返回 `executed`，而集群状态一点没变。

### 为什么知识回写只写"修好了"的

失败的案例看起来也有价值（"这么做不管用"），但**故意不写**：

> 失败的原因可能是**我们自己代码的 bug**，而不是这个动作不对。
> 把它写进知识库，等于教未来的自己"别用这个动作"。

这种"把工具缺陷记成领域知识"的污染，是自进化系统最危险的失败模式。

### 为什么写操作不注册给模型

MCP 的价值不是"把所有能力都给模型"，是**用统一协议把能力边界定清楚**：

- **只读工具** → 注册成 MCP 工具，模型自由调用
- **写操作** → **一个都不注册**，只由 `executor` 节点内部调用

否则模型可以绕过四道闸门直接调 `rollback_deployment`。

---

## 已知局限



| 局限 | 现在为什么不做 / 要做怎么做 |
|---|---|
| **A2A 没做** | 它解决的是**跨权限边界协作**。现在只有一个 Agent，硬做只能是接口层的事。等真有第二个独立 Agent（比如下游团队的服务）再做 |
| **长期记忆没做** | 现在有跨故障的共享知识库，但没有**按实体组织的记忆**（"这个服务的 owner 是谁、SLA 多少"）。用 LangGraph Store 存 |
| **知识库没有人工复核** | 自动回写的记录标了 `verified: false`，将来要加人工确认环节，否则质量会慢慢漂 |
| **单进程** | 后台任务的 `_running` set 在内存里，服务起两个副本会重复跑。要改成任务队列才能真正水平扩 |
| **`namespace` 有硬编码默认值** | 工具签名里的 `namespace="prod-order"`，应该从配置或告警来 |

---

## 开发

### 常用脚本

```bash
python -m app.scripts.smoke              # 完整跑一次故障处置（会打印诊断全过程）
python -m app.scripts.outcome_test       # 结局判定的真值表（纯逻辑，不碰集群）
python -m app.scripts.notify_test        # 通知的幂等 / 过滤
python -m app.scripts.executor_test      # 四道闸门（只读，不改集群）
python -m app.scripts.k8s_test           # K8s 只读接口
python -m app.scripts.rollout_test       # Deployment 发布状态
python -m app.scripts.rag_search_test    # 检索对比（三种过滤方式）
python -m app.scripts.writeback_test     # 知识回写：条数 / 计数 / 排名
python -m app.scripts.embed_diag         # embedding 空间 + 索引漂移
python -m app.scripts.verify_persist <fault_id>   # checkpoint 的逐步历史
```

### 排查工具

**checkpoint 的逐步历史**（排查"图为什么停在这一步"）：

```bash
python -m app.scripts.verify_persist <fault_id>
```

**通知列表**：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/notifications?limit=20" | ConvertTo-Json -Depth 4
```

**待审批**：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/faults/pending" | ConvertTo-Json
```

### API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/faults` | 受理告警，**立即返回 202**，处理在后台 |
| `GET` | `/faults/{id}` | 查状态（`running` / `awaiting_approval` / `finished`） |
| `GET` | `/faults/pending` | 待审批列表 |
| `POST` | `/faults/{id}/approve` | 批准或否决，**立即返回 202** |
| `GET` | `/notifications` | 最近的通知 |

**`POST /faults` 为什么是异步的**：一次故障包含 3~4 次 LLM 调用
加上 30 秒的观测窗口，总共 40~60 秒。同步跑的话客户端/网关会先超时断开，
而图还在后台继续跑 —— 调用方以为失败了，实际还在动。

**改成**：受理后立即返回 `fault_id`，用 `GET /faults/{id}` 轮询。

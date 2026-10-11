# Robot Policy Playground

在 Cloudflare Workers（Python，免费计划）上运行的自然语言 → 机械臂动作回放演示台。
输入一句指令（如 `pick up the cube`），后端返回 `task_id`，浏览器通过 WebSocket
接收预计算好的关节角帧，并在 **浏览器内的 MuJoCo 物理仿真** 中回放。

> 这里的 "infer" 是**精确查表**，不是神经网络推理。原因见
> [.trae/rules/project_rules.md](.trae/rules/project_rules.md)：免费计划 Worker 只有
> 10ms CPU，ONNX WASM 又超过单文件 25 MiB 限制，所以策略必须离线预计算。

## 文档入口（先读这些）

| 文档 | 内容 |
| --- | --- |
| [.trae/rules/project_rules.md](.trae/rules/project_rules.md) | **权威规则**：平台约束、技术栈、IK/轨迹规范、相机规范、已知问题 |
| [.trae/documents/robot_policy_playground_plan.md](.trae/documents/robot_policy_playground_plan.md) | 三阶段开发计划、文件清单、验证项、风险表 |
| [.trae/documents/mujoco-react-integration-plan.md](.trae/documents/mujoco-react-integration-plan.md) | MuJoCo 集成设计决策与 9 个阶段状态 |
| [.trae/documents/troubleshooting-log.md](.trae/documents/troubleshooting-log.md) | 25 个历史问题的原因与解决（部署/QUIC/WSL/IK/WebSocket） |
| [.trae/commands/summarize-pause.md](.trae/commands/summarize-pause.md) | 暂停并总结任务的流程约定 |
| [frontend/README.md](frontend/README.md) | 仅 Vite 官方模板说明，**与本项目无关** |

## 架构

```
浏览器 (React 18 + three.js + MuJoCo WASM)
  │  POST /api/infer          { instruction }
  │  ← { success, task_id }                      → src/main.py  (FastAPI Worker，仅做索引查表)
  │  WS   /ws/stream          { task_id }
  │  ← { type:"start"|"frame"|"done" }            → src/ws_stream.py (WSStream DO，逐帧推送)
  └─  静态资源 /data/*                             → public/ (ASSETS 绑定，不走 Worker，不占配额)
```

| 路径 | 说明 |
| --- | --- |
| [src/main.py](src/main.py) | Worker 入口：`/api/health`、`/api/infer`，并把 `/ws/*` 转给 Durable Object |
| [src/ws_stream.py](src/ws_stream.py) | `WSStream` DO：按 ~30ms 间隔推送 `ja` 帧（8 维 = 7 关节 + 夹爪） |
| [frontend/](frontend) | React 18 + Vite + TS 前端（R3F v8，不支持 React 19） |
| [public/data/](public/data) | Franka Panda 模型（`panda/scene.xml`）、5×60 帧轨迹、任务索引 |
| [scripts/](scripts) | `generate_ik_actions.py`（离线 6-DOF IK 生成轨迹）、`verify_ik.py`、`check_json.py` |
| [start_dev.sh](start_dev.sh) | WSL 下的本地开发启动脚本 |
| [wrangler.jsonc](wrangler.jsonc) | Worker / DO（`new_sqlite_classes`）/ ASSETS 绑定 |

## 本地开发（WSL Ubuntu）

**所有终端操作都在 WSL Ubuntu 中执行**，Windows 端只用于编辑文件
（原因见 [troubleshooting-log D4/问题 24](.trae/documents/troubleshooting-log.md)：沙箱阻止写入
Windows 的 `~/.wrangler` 与 site-packages）。Windows 下的 `node_modules`
不能复用，WSL 里需独立安装。

```bash
cd /mnt/e/robot-policy-playground

# 后端 + 已构建页面：单进程即可（推荐，见下）
./start_dev.sh                 # 等价于 pywrangler dev

# 前端热更新开发（可选）
cd frontend && npm run dev     # http://localhost:5173
```

`start_dev.sh` 会 `cd` 到仓库根并执行 `pywrangler dev`：Worker 同时提供
`/api/*`、`/ws/*` 和 `public/` 里的静态资源，所以**只要 `public/` 里有构建产物，
打开它打印的地址就是完整应用**，不需要 Vite。

只有需要前端热更新（HMR）时才额外起 Vite；此时 [vite.config.ts](frontend/vite.config.ts)
会把 `/api`、`/ws` 代理到 `http://127.0.0.1:8787`（wrangler dev 默认端口，
可用 `VITE_WORKER_ORIGIN` 覆盖），`/data/*` 由 Vite 直接从仓库根 `public/` 提供。
也可以不用代理，改用 [frontend/.env.example](frontend/.env.example) 里的绝对地址方案。

## 构建与部署（WSL）

```bash
cd /mnt/e/robot-policy-playground/frontend && npm run build   # 产物复制到 ../public
cd /mnt/e/robot-policy-playground && npx wrangler deploy
```

`npm run build` 的第三段是 [scripts/sync-public.mjs](scripts/sync-public.mjs)：同步产物到
`public/`，并对全部静态文件做 **25 MiB 单文件上限校验**（免费计划硬限制）。
超限时它会让构建直接失败并报出文件名与体积，**不会**静默删除——历史上曾用
"删掉所有 `.wasm`"来绕过 ONNX Runtime 25.6 MiB 超限，结果把问题推迟到线上才暴露
（见 [troubleshooting-log 问题 21](.trae/documents/troubleshooting-log.md)）。
确实需要排除某个文件时，在 `sync-public.mjs` 顶部的 `EXCLUDED` 里显式登记原因。

部署需要 `export CLOUDFLARE_API_TOKEN=...`（非交互环境无法 `wrangler login`，
Token 不持久化）。上线 URL：`https://robot-playground.qmes743628.workers.dev`。

### 仓库里的产物与 `.gitignore` 不一致（已知）

[public/index.html](public/index.html) **是被 git 跟踪的**，而它引用的
`public/assets/*` 被 [.gitignore](.gitignore) 忽略（第 8 行）。所以刚 clone 出来的仓库
里有一个指向不存在 asset 的 HTML，必须先执行 `npm run build` 才能跑起来。
要么把 `public/assets/` 从 `.gitignore` 移除并一并提交，要么把
`public/index.html` 也忽略掉（因为它是构建产物）——目前是"一半跟踪"的状态。

## 已知边界与坑

- **没有真实策略**：`/api/infer` 把小写化指令在 [task_index.json](public/data/task_index.json)
  里精确匹配，措辞不同即失败；轨迹是离线 IK 预计算（60 帧/任务，约 3KB/任务），
  无观测输入、无闭环。
- **单 DO 实例**：所有客户端共用 `idFromName("stream")`，见 [src/main.py](src/main.py)。
- **慢网 + QUIC**：67 个 mesh（8 个 .stl + 59 个 .obj，都被 `panda.xml` 引用）共 33.59 MB，
  且碎片化（`link6` 一个连杆就有 18 个文件）。慢网下 `workers.dev` 的 HTTP/3 会
  `ERR_QUIC_PROTOCOL_ERROR 200`。**根治方向是把每个 link 的 mesh 合并**（请求数与体积都能大幅下降），
  "让访客禁用 QUIC"只是临时绕过。
- **跨域隔离**：MuJoCo 多线程 WASM 需要 COOP/COEP 头，只有 Vite dev server
  和 Cloudflare 线上会带；用普通静态服务器打开会失败。

## 关于"代码 / 文档 / 线上"三者的一致性

这个仓库曾经出现三方不一致，排查时请注意：

- **前端 bundle 是内容寻址的**：`index-CL0HiSH1.js` 这个名字由内容哈希决定。
  只要源码没变，重新构建会得到**同名同哈希**的文件；因此"线上文件名 == 本地构建文件名"
  能证明前端已同步，反之则没同步。
- **但 `public/data/*.json` 不是内容寻址的**：文件名固定，改了内容文件名也不变，
  无法从文件名判断线上是否是旧数据。验证必须**逐字节比对**（`Invoke-WebRequest`
  取回后与本地 `ReadAllBytes` 对比字节数与首个差异位置）。
- 文档里的 ✅ 表示"当时验证通过"，不等于"当前线上如此"。回放后请以
  **线上实际抓取结果**为准。


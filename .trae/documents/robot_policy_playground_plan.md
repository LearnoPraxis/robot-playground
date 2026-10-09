# Robot Policy Playground 开发计划

## 仓库研究结论

- 当前工作目录 `e:\robot-policy-playground` 为空，是全新项目，无既有代码、无既有配置。
- 目标平台：**Cloudflare Workers 免费计划**。
- 核心策略：**本地预计算 + 云端回放**。Worker 仅做索引查找并返回 `task_id`；完整动作序列由 Durable Object（SQLite 后端）通过 WebSocket 流式推送。
- 三条不可逾越红线：
  1. Worker 中不做任何推理，`/api/infer` 仅返回 `task_id`。
  2. `wrangler.jsonc` 必须使用 `new_sqlite_classes`，不设置 `run_worker_first`。
  3. 前端锁定 **React 18**（R3F v8 不支持 React 19），后端不引入 `numpy`/`torch` 等 C 扩展依赖。
- 约束摘要：Worker CPU ≤10ms/请求、内存 ≤128MB、日请求 ≤10万（API + WS 建立共享）、单静态文件 ≤25MiB、静态文件总数 ≤2万/Worker、免费计划 DO 仅支持 SQLite 后端。

## 阶段划分总览

| 阶段 | 内容 | 产出 |
|------|------|------|
| 阶段 A：后端 | Wrangler 配置、Pydantic 模型、FastAPI Worker、DO WebSocket 推流、预计算数据与索引 | `src/`、`public/data/`、`wrangler.jsonc`、`pyproject.toml` |
| 阶段 B：前端 | Vite + React 18 + R3F 机械臂渲染、控制面板、WebSocket Hook、SPA 构建产物 | `frontend/` 及构建后的 `public/` 静态资源 |
| 阶段 C：部署与验证 | 本地联调、生产部署、端到端验证、日志观测 | 线上可访问的 Workers 应用 |

## 文件与模块清单

### 阶段 A — 后端

- `wrangler.jsonc`：Workers 配置，含 `python_workers` 兼容标记、静态资源目录、DO 绑定（`new_sqlite_classes`）。
- `pyproject.toml`：Python 依赖（仅 `fastapi`、`pydantic`）。
- `.trae/rules/project_rules.md`：项目规则与约束文档。
- `src/schemas.py`：`InferRequest`、`InferResponse` Pydantic v2 模型。
- `src/main.py`：FastAPI 应用 + `asgi.fetch` 入口；`/api/infer` 读取索引并返回 `task_id`。
- `src/ws_stream.py`：`WSStream` Durable Object，接收 `task_id`、从 ASSETS 读取动作 JSON、逐帧推送 `joint_angles`。
- `public/data/task_index.json`：指令 → `task_id` 精简索引（≤100 条）。
- `public/data/<task_id>.json`：每个任务的预计算动作序列（≤500 帧、≤25MiB、压缩 JSON、短键名）。

### 阶段 B — 前端

- `frontend/package.json`：React 18、R3F v8、three、drei。
- `frontend/.env.example`：`VITE_API_BASE_URL`、`VITE_WS_URL` 相对路径。
- `frontend/src/components/RobotArm.tsx`：2 连杆机械臂 3D 组件。
- `frontend/src/components/ControlPanel.tsx`：指令输入、预设下拉、状态显示。
- `frontend/src/hooks/useWebSocket.ts`：WS 连接、自动重连、心跳保活、动作帧消费。
- `frontend/src/App.tsx`：左侧 3D 画布 + 右侧控制面板 + 底部播放控制。
- `public/`：前端构建产物（`npm run build` 后从 `frontend/dist/` 复制）。

### 阶段 C — 部署与验证

- 本地联调：`wrangler dev` 运行、curl 测试 API、浏览器测试完整流程。
- 生产部署：`wrangler deploy`、线上验证、`wrangler tail` 日志观测。

## 实施步骤（按依赖顺序）

### 阶段 A：后端

**A1. 项目结构与规则文档**
1. 创建目录骨架：`src/`、`public/data/`、`public/assets/`、`.trae/rules/`。
2. 写入 `.trae/rules/project_rules.md`（部署平台、硬性约束、技术栈、预计算策略、代码规范、Skills 管理、交互约定）。

**A2. Wrangler 配置**
3. 创建 `wrangler.jsonc`：`main: src/main.py`、`compatibility_flags: ["python_workers"]`、`assets.directory: ./public`、DO 绑定 `WSStream`/`WS_STREAM`、`migrations` 使用 `new_sqlite_classes: ["WSStream"]`。
4. 不设置 `run_worker_first`；设置 `not_found_handling: "single-page-application"`。
5. 创建 `pyproject.toml`，仅声明 `fastapi`、`pydantic`。

**A3. 数据模型**
6. 创建 `src/schemas.py`：`InferRequest(instruction: str)`、`InferResponse(task_id: str, success: bool, message: str)`，使用 Pydantic v2，类型注解完整。

**A4. FastAPI Worker 入口**
7. 创建 `src/main.py`：`FastAPI()` 应用，`POST /api/infer` 从 `ASSETS` 读取 `task_index.json`，匹配 `instruction` → `task_id`，仅返回 `task_id`（不解析完整动作序列）。
8. `on_fetch(request, env)` 委托给 `asgi.fetch(app, request, env)`。

**A5. Durable Object WebSocket 推流**
9. 创建 `src/ws_stream.py`：`WSStream(DurableObject)`，`fetch` 升级 WebSocket，接收 `task_id` 后从 `ASSETS` 读取对应动作 JSON，逐帧推送 `joint_angles`（约 30ms 间隔），推送完毕发送结束标记。

**A6. 预计算数据**
10. 在 `public/data/` 下放置 5 个任务的动作序列 JSON（短键名、`separators=(',', ':')` 压缩）及 `task_index.json` 索引。
11. 确认每个文件 ≤25MiB、≤500 帧。

### 阶段 B：前端

**B1. 项目脚手架**
12. `frontend/` 下执行 `npm create vite@latest . -- --template react-ts`。
13. 立即锁定 React 18：`npm install react@18 react-dom@18`，并安装 `three @react-three/fiber @react-three/drei`。

**B2. 组件与 Hook**
14. `RobotArm.tsx`：2 连杆机械臂，props `jointAngles: [number, number]`，含 `<OrbitControls>`。
15. `ControlPanel.tsx`：指令输入框 + 发送按钮 + 预设下拉（5 个任务）+ 状态显示。
16. `useWebSocket.ts`：连接 `/ws/stream`，发送 `task_id`，接收动作帧，自动重连（指数退避），30s 心跳保活。
17. `App.tsx`：布局（左 3D / 右控制 / 底播放控制），串联 Hook 与组件。

**B3. 构建与静态资源**
18. `npm run build`，将 `frontend/dist/*` 复制到项目根 `public/`。
19. 创建 `frontend/.env.example`。

### 阶段 C：部署与验证

**C1. 本地联调**
20. `wrangler dev` 启动本地 Worker。
21. curl 测试 `POST /api/infer`，验证返回 `task_id`。
22. 浏览器打开本地页面，验证 3D 渲染、指令发送、WebSocket 流式回放。

**C2. 生产部署**
23. `wrangler deploy` 部署到 Cloudflare。
24. 线上验证前端加载、API 调用、WebSocket 连接。
25. `wrangler tail` 观测实时日志。

## 依赖与注意事项

- **命令环境**：Windows PowerShell 5，禁止 `&&`/`||`，使用 `;` 或分两次执行；脚本用 `.cmd` 版本（如 `npm.cmd`）。
- **Wrangler 配置**：`new_sqlite_classes` 是免费计划强制要求；`run_worker_first` 不设为 true 以避免消耗静态资源配额。
- **Python Workers**：运行于 Pyodide/WASM，不支持任意 C 扩展；禁止 `import numpy/torch/PocketVLA`。
- **Worker 10ms CPU**：`task_index.json` ≤100 条，`/api/infer` 只做索引查找，不解析动作 JSON。
- **WebSocket**：连接建立计入日请求配额；前端需自动重连 + 心跳 + 指数退避。
- **React 版本**：锁定 React 18，R3F v8 不支持 React 19。
- **静态资源**：单文件 ≤25MiB、总数 ≤2万；动作 JSON 用短键名 + 无空格压缩。
- **路径一致性**：API 以 `/api/` 开头、WS 以 `/ws/` 开头，避免被 SPA 路由拦截返回 HTML。
- **预计算数据**：重新生成动作序列后必须同步更新 `task_index.json`。

## 验证项

- `wrangler.jsonc` 中 `new_sqlite_classes` 拼写正确、无 `run_worker_first`。
- `src/` 代码无 `numpy`/`torch`/`sklearn` 等重型依赖导入。
- `POST /api/infer` 返回 JSON 且仅含 `task_id`，CPU 时间远低于 10ms。
- WebSocket 连接能持续接收动作帧并完成回放。
- 前端在 React 18 + R3F v8 下正常渲染机械臂并跟随动作帧运动。
- `npm run build` 产物完整复制到 `public/`，SPA 路由正常。
- 部署后线上页面、API、WS 全链路可用。

## 风险与应对

| 风险 | 应对 |
|------|------|
| `new_sqlite_classes` 写错导致部署失败 | 部署前人工核对；作为第一步校验项 |
| Worker CPU 超时 | 索引 ≤100 条；端点仅做字符串查找 |
| React 19 与 R3F v8 不兼容 | 脚手架创建后立即 `npm install react@18 react-dom@18` |
| WebSocket 因网络重启中断 | 前端自动重连 + 30s 心跳 + 指数退避 |
| 日请求配额耗尽 | 不设 `run_worker_first`；前端连接复用 |
| 动作 JSON 超 25MiB | 短键名 + 去空格压缩；必要时拆分文件 |
| DO 本地与生产行为不一致 | 部署后在生产环境重新验证 WS 全流程 |
| API 路径被 SPA 拦截 | API 严格以 `/api/` 开头，前端常量统一管理 |

## 执行方式说明

本计划分为后端、前端、部署三个阶段。每个阶段内部步骤按依赖顺序执行；阶段之间可串行推进。**部署（阶段 C2）等高影响动作将在执行前再次征求确认。** 预计算数据（A6）需要由用户本地运行 PocketVLA 推理生成，若暂无真实数据，可先用占位动作序列跑通全链路，再替换为真实数据。

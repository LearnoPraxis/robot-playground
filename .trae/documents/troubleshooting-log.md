# Robot Policy Playground — 问题与解决记录

> 从项目部署至今的完整问题记录，按时间顺序排列，方便后续回顾。

---

## 一、部署阶段

### D1. Durable Object 后端类型错误

| 项 | 内容 |
|---|------|
| **时间** | 初始部署 |
| **问题** | `wrangler deploy` 报错：Durable Objects 必须使用 SQLite 后端 |
| **原因** | `wrangler.jsonc` 使用 `new_classes` 而非 `new_sqlite_classes` |
| **解决** | 改为 `"new_sqlite_classes": ["WSStream"]` |
| **文件** | [wrangler.jsonc](file:///e:/robot-policy-playground/wrangler.jsonc) |
| **教训** | Cloudflare 免费计划仅支持 SQLite 后端 DO |

### D2. 静态资源消耗请求配额

| 项 | 内容 |
|---|------|
| **时间** | 初始部署 |
| **问题** | 静态资源请求也消耗每日 100,000 次配额，导致 429 错误 |
| **原因** | `run_worker_first: true` 使所有请求（包括静态文件）都经过 Worker |
| **解决** | 移除 `run_worker_first`，让静态资源直接由 Cloudflare CDN 返回 |
| **文件** | [wrangler.jsonc](file:///e:/robot-policy-playground/wrangler.jsonc) |
| **教训** | 不要设置 `run_worker_first`，保留静态资源免费无限配额 |

### D3. npm 缓存锁损坏

| 项 | 内容 |
|---|------|
| **时间** | 部署阶段 |
| **问题** | `npx wrangler deploy` 报 `npm error code ECOMPROMISED` / `Lock compromised` |
| **原因** | npm 缓存锁文件损坏 |
| **解决** | `npm cache clean --force` 清除缓存后重新执行 |
| **教训** | 非文件替换操作导致，是 npm 缓存问题 |

### D4. Wrangler 沙箱限制

| 项 | 内容 |
|---|------|
| **时间** | 部署阶段 |
| **问题** | Windows PowerShell 中执行 `wrangler deploy` 失败，无法写入 `~/.wrangler` 配置目录 |
| **原因** | Trae 沙箱阻止写入 `C:\Users\Administrator\AppData\Roaming\xdg.config\.wrangler\` |
| **解决** | 改在 WSL Ubuntu 终端中执行部署命令 |
| **教训** | Wrangler 始终在 WSL 中运行，不在 Windows PowerShell 中 |

### D5. Cloudflare API 认证

| 项 | 内容 |
|---|------|
| **时间** | 部署阶段 |
| **问题** | 非交互环境下 wrangler 需要 `CLOUDFLARE_API_TOKEN` 环境变量 |
| **原因** | 沙箱无法执行交互式 `wrangler login` |
| **解决** | 在 Cloudflare Dashboard 创建 API Token（Workers Scripts Edit + Workers Tail Read，Entire Account），在 WSL 中 `export CLOUDFLARE_API_TOKEN="token"` |
| **教训** | Token 不会持久化，需每次设置或写入 `~/.bashrc` |

---

## 二、前端 3D 可视化阶段

### F1. React 19 与 R3F v8 不兼容

| 项 | 内容 |
|---|------|
| **时间** | 前端开发 |
| **问题** | React Three Fiber v8 与 React 19 不兼容，运行时报错 |
| **原因** | `npm install` 安装了 React 19 |
| **解决** | 锁定 React 18：`npm install react@18 react-dom@18` |
| **教训** | R3F v8 只支持 React 18，不要升级到 React 19 |

### F2. 拖拽 getBoundingClientRect 报错

| 项 | 内容 |
|---|------|
| **时间** | 4-DOF 机械臂开发 |
| **问题** | 拖拽小球时控制台报 `event.target.getBoundingClientRect is not a function` |
| **原因** | R3F 中 `event.target` 是 Three.js Object3D（不是 DOM 元素），没有 DOM API |
| **解决** | 用 `gl.domElement`（canvas 元素）替代 `event.target`，调用 `getBoundingClientRect`、`setPointerCapture`、`releasePointerCapture` |
| **文件** | [RobotArm.tsx](file:///e:/robot-policy-playground/frontend/src/components/RobotArm.tsx) |
| **教训** | R3F 事件对象的 target 不是 DOM 元素，需要通过 `useThree()` 获取 `gl.domElement` |

### F3. IK 拖拽手柄不能作为交互对象

| 项 | 内容 |
|---|------|
| **时间** | 4-DOF 机械臂开发 |
| **问题** | 绿色 TargetPoint（IK 拖拽手柄）被当作"小球"，但它跟随机械臂末端，不是独立物体 |
| **原因** | 场景中没有独立的球 mesh，TargetPoint 同时承担了拖拽手柄和操作目标两个角色 |
| **解决** | 添加独立的小球 mesh（固定位置 `BALL_POSITION`），与 TargetPoint 分离 |
| **教训** | IK 拖拽手柄和交互对象必须是不同的 mesh |

### F4. 正运动学未包含底座旋转

| 项 | 内容 |
|---|------|
| **时间** | 4-DOF 机械臂开发 |
| **问题** | 机械臂与小球在相反方向，末端位置计算错误 |
| **原因** | `forwardKinematics(j1, j2)` 只计算底座局部坐标，没有乘 j0 底座 Y 轴旋转矩阵 |
| **解决** | 新增 `forwardKinematicsWorld(j0, j1, j2)` 包含底座旋转：`worldX = localX * cos(j0)`、`worldZ = -localX * sin(j0)` |
| **文件** | [RobotArm.tsx](file:///e:/robot-policy-playground/frontend/src/components/RobotArm.tsx) |
| **教训** | 多关节 FK 需要从底座到末端逐级累积变换 |

### F5. 预计算角度过高

| 项 | 内容 |
|---|------|
| **时间** | 4-DOF 机械臂开发 |
| **问题** | 机械臂末端远离地面目标，无法接触小球 |
| **原因** | 预计算 j1 最大 0.75 rad（~43°），末端 y ≈ 1.7m，远高于地面（y ≈ 0.08） |
| **解决** | 调整 j1 为负值（-1.08 至 -1.5 rad），使末端接近地面 |
| **教训** | 预计算轨迹需验证末端可达性 |

### F6. 无物理引擎导致无法交互

| 项 | 内容 |
|---|------|
| **时间** | 4-DOF 机械臂开发 |
| **问题** | 机械臂穿过球，球不移动；夹爪只改间距，无法抓取 |
| **原因** | R3F 手动几何体无物理碰撞检测，小球是静态 mesh |
| **解决** | 决定集成 mujoco-react（MuJoCo 物理引擎 + Franka Panda 7-DOF） |
| **教训** | 手动 R3F 几何体 + FK/IK 无法实现物理交互，需要物理引擎 |

---

## 三、WebSocket 实时通信阶段

### W1. WebSocket 连接失败

| 项 | 内容 |
|---|------|
| **时间** | 部署后验证 |
| **问题** | 生产环境 WebSocket 连接失败，底部显示"重连中..." |
| **原因** | DO WebSocket API 使用了 Python 级别的 WebSocket 处理（非标准） |
| **解决** | 改用 Python Hibernation API：`WebSocketPair` + `self.ctx.acceptWebSocket` + `Response(None, status=101, web_socket=client)` |
| **文件** | [ws_stream.py](file:///e:/robot-policy-playground/src/ws_stream.py) |
| **教训** | Cloudflare Workers Python DO 需用 Hibernation API 处理 WebSocket |

### W2. Missing task_id 心跳问题

| 项 | 内容 |
|---|------|
| **时间** | 部署后验证 |
| **问题** | 执行完指令后出现 "Missing task_id" 错误 |
| **原因** | DO 未过滤心跳消息（`{"type":"ping"}`），将其当作 task_id 请求处理 |
| **解决** | DO `webSocketMessage` 中过滤 `{"type":"ping"}` 消息，回复 `{"type":"pong"}` |
| **文件** | [ws_stream.py](file:///e:/robot-policy-playground/src/ws_stream.py) |
| **教训** | WebSocket 心跳消息需在 DO 层过滤 |

---

## 四、浏览器端 AI 推理阶段

### A1. SmolVLM 模型加载失败

| 项 | 内容 |
|---|------|
| **时间** | SmolVLM 验证 |
| **问题** | 浏览器端 SmolVLM-256M 模型加载失败，`batch_decode` undefined |
| **原因** | HuggingFace 访问受网络影响，模型下载失败 |
| **解决** | 移除 Vite 代理，让浏览器直接访问 HuggingFace；添加 debug 日志；简化 decode 逻辑 |
| **教训** | 浏览器/Node.js 可能使用不同代理设置；HuggingFace 访问不稳定 |

### A2. Pyodide xbuildenv 下载失败

| 项 | 内容 |
|---|------|
| **时间** | Python Workers 编译 |
| **问题** | Pyodide xbuildenv 从 GitHub 下载失败（超时 + 证书错误） |
| **原因** | 网络不稳定 + GitHub 连接超时 |
| **解决** | 手动下载 xbuildenv 包，放到本地缓存目录 |
| **教训** | WSL Ubuntu 26.04 apt 源提供 nodejs 22.22.1（满足 Pyodide ≥18 要求） |

### A3. 浏览器端推理性能不一致

| 项 | 内容 |
|---|------|
| **时间** | SmolVLM 验证 |
| **问题** | 不同设备上推理性能差异大（加载 2.67s vs 52.3s） |
| **原因** | 浏览器端推理完全依赖访客设备 CPU/GPU |
| **解决** | 接受现状，作为可选功能；记录性能预期供用户参考 |
| **教训** | 浏览器端推理体验因设备而异，不适合作为核心功能 |

---

## 五、构建阶段

### B1. WASM 文件被构建脚本删除

| 项 | 内容 |
|---|------|
| **时间** | 构建部署 |
| **问题** | 构建产物中的 .wasm 文件被删除，运行时找不到 WASM |
| **原因** | `package.json` build 脚本中有 `node -e "...删除 .wasm..."` 逻辑（之前为绕过 25MiB 限制） |
| **解决** | 移除 build 脚本中的 .wasm 删除逻辑（MuJoCo WASM 10.1MB < 25MiB） |
| **文件** | [package.json](file:///e:/robot-policy-playground/frontend/package.json) |
| **教训** | MuJoCo WASM 必须保留在构建输出中 |

### B2. Vite 端口自动递增

| 项 | 内容 |
|---|------|
| **时间** | 前端开发 |
| **问题** | Vite dev server 端口自动递增（5173 → 5174 → ...） |
| **原因** | 默认 `strictPort: false`，端口被占用时自动切换 |
| **解决** | `vite.config.ts` 设置 `strictPort: true`，固定端口 5173 |
| **教训** | 固定端口方便调试和 CORS 配置 |

---

## 六、网络与环境阶段

### N1. workers.dev 域名访问受限

| 项 | 内容 |
|---|------|
| **时间** | 部署后验证 |
| **问题** | 中国内地网络可能无法访问 `*.workers.dev` |
| **原因** | workers.dev 子域名在大陆部分网络被 DNS 污染 |
| **解决** | 方案 A：科学上网；方案 B：绑定自定义域名（需备案） |
| **教训** | 部署后需验证目标用户网络可达性 |

### N2. Vite 代理返回 index.html

| 项 | 内容 |
|---|------|
| **时间** | SmolVLM 开发 |
| **问题** | Vite 代理 HuggingFace 请求返回 index.html 而非 API 响应 |
| **原因** | 代理配置错误，SPA 回退把 API 路由当前端路由 |
| **解决** | 移除自定义代理，让浏览器直接访问 HuggingFace |
| **教训** | 外部 API 请求不要通过 Vite 代理 |

### N3. WSL 与 Windows 网络差异

| 项 | 内容 |
|---|------|
| **时间** | 部署阶段 |
| **问题** | 浏览器可以访问 HuggingFace，但 PowerShell/Node.js 不行 |
| **原因** | 浏览器和 Node.js 使用不同的代理设置 |
| **解决** | 确认浏览器直连，绕过 Node.js 代理 |
| **教训** | 不同运行环境可能有不同网络配置 |

---

## 七、经验总结

### 高频问题类型

| 类型 | 出现次数 | 核心原因 |
|------|----------|----------|
| 网络/环境问题 | 5 | 中国网络特殊 + 沙箱限制 + WSL/Windows 差异 |
| 3D 渲染问题 | 4 | R3F 事件模型与 DOM 不同 + 无物理引擎 |
| WebSocket 问题 | 2 | DO API 不标准 + 心跳未过滤 |
| 部署配置问题 | 3 | DO 后端类型 + run_worker_first + 缓存损坏 |

### 可复用经验

1. **Cloudflare Workers 免费计划**：SQLite DO + 不设 run_worker_first + API Token 认证
2. **R3F 事件处理**：用 `gl.domElement` 而非 `event.target`；多关节 FK 需逐级累积变换
3. **WebSocket DO**：用 Hibernation API + 过滤心跳消息
4. **浏览器端 AI**：性能因设备而异，不适合核心功能
5. **部署流程**：WSL 中执行 wrangler + API Token 环境变量 + 验证网络可达性

## 阶段 7: MuJoCo 集成后生产环境验证 (2026-10-08)

### 问题 18: ERR_QUIC_PROTOCOL_ERROR 200 (OK) — MuJoCo 加载失败

**时间**: 2026-10-08 22:09
**问题**: 部署成功后访问 https://robot-playground.qmes743628.workers.dev/，3D 画布全黑，Console 报错 `MuJoCo 加载失败: Failed to fetch`，共 12 个错误。
**原因**: 所有 67 个 mesh 文件 (.obj/.stl) 在通过 QUIC (HTTP/3) 协议传输时出现 `net::ERR_QUIC_PROTOCOL_ERROR 200 (OK)`。HTTP 状态码为 200 但 QUIC 传输层失败，响应体未完整接收。根因是用户网络极慢（3.3MB JS 耗时 2.3 分钟，约 24 KB/s），大 mesh 文件（如 link0_8.obj 3.35MB）在 QUIC 传输中超时。
**解决方案**: 
1. 浏览器地址栏输入 `chrome://flags/#enable-quic` → Disabled → Relaunch（禁用 QUIC 回退 HTTP/2 TCP）
2. 备选方案: 精简 mesh 文件（移除碰撞 mesh、简化视觉 mesh）/ 切换更快网络 / 使用自定义域名
**涉及文件**: 
- `frontend/src/components/RobotArm.tsx` (line 89: console.error("MuJoCo 加载失败:", error))
- `public/data/panda/assets/*.obj` (67 个 mesh 文件，总计约 30-40MB)
- `public/data/panda/scene.xml` (引用所有 mesh 文件)
**经验教训**: 
- Cloudflare workers.dev 默认使用 QUIC (HTTP/3)，在慢速网络下传输大文件容易超时
- `ERR_QUIC_PROTOCOL_ERROR 200` 是 deceptive 错误：HTTP 状态 200 但传输层失败
- MuJoCo mesh 文件总量大（30-40MB），不适合慢速网络一次性加载
- 应考虑 mesh 文件压缩或懒加载策略

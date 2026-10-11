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

### F2. 无物理引擎导致无法交互

| 项 | 内容 |
|---|------|
| **时间** | 早期手动 R3F 几何体阶段（已废弃） |
| **问题** | 机械臂穿过球，球不移动；夹爪只改间距，无法抓取 |
| **原因** | R3F 手动几何体无物理碰撞检测 |
| **解决** | 集成 mujoco-react（MuJoCo 物理引擎 + Franka Panda 7-DOF），手动 R3F 几何体已全部移除 |
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

---

## 阶段 8: MuJoCo 场景与相机控制修复 (2026-10-09)

### 问题 19: 地面竖直渲染

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-09 |
| **问题** | 地面在 3D 场景中始终竖直，无法水平显示 |
| **原因** | mujoco-react 不做 Z-up→Y-up 坐标转换，源码 `index.js:575` 直接映射 `data.xpos` 到 `ref.position` |
| **解决** | 设置 `camera.up.set(0, 0, 1)` 使 three.js 使用 Z 轴向上，匹配 MuJoCo Z-up 坐标系 |
| **文件** | [RobotArm.tsx](file:///e:/robot-policy-playground/frontend/src/components/RobotArm.tsx) |
| **教训** | mujoco-react 不自动转换坐标系，需手动设置相机 up 向量 |

### 问题 20: 右键拖拽触发浏览器导航

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-09 |
| **问题** | 右键拖拽旋转视角时触发浏览器返回/上下文菜单 |
| **原因** | OrbitControls 右键按钮触发浏览器默认行为 |
| **解决** | 设置 `mouseButtons.RIGHT = undefined` + `mouseButtons.LEFT = undefined`（避免与 IK 手柄冲突），改用 WASD 键盘控制视角（球坐标操作） |
| **文件** | [RobotArm.tsx](file:///e:/robot-policy-playground/frontend/src/components/RobotArm.tsx) |
| **教训** | 鼠标拖拽与 IK 交互冲突，键盘控制更可靠 |

### 问题 21: ort-wasm 超出 25 MiB 部署限制

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-09 |
| **问题** | `ort-wasm-simd-threaded.asyncify-CxOG5pUO.wasm` (25.6 MiB) 超出 Cloudflare 单文件 25 MiB 限制 |
| **原因** | `@huggingface/transformers` (SmolVLM) 依赖 ONNX Runtime，其 WASM 文件过大 |
| **解决** | 1. 移除 `@huggingface/transformers` 依赖 + SmolVLMTester 组件 2. build 脚本排除 .wasm 文件 |
| **文件** | [package.json](file:///e:/robot-policy-playground/frontend/package.json) |
| **教训** | ONNX WASM 无法部署到 Cloudflare Workers 免费计划，浏览器端 VLM 不适合本架构 |

---

## 阶段 9: IK 轨迹与 WSL 迁移 (2026-10-10)

### 问题 22: 机械臂回放时未接触物体

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-10 |
| **问题** | 发送指令后机械臂始终未接触方块与小球 |
| **原因** | 旧的 `generate_panda_actions.py` 使用手动猜测的关节角度，无 FK/IK 验证 |
| **解决** | 创建 `generate_ik_actions.py`，使用 MuJoCo Python 绑定的 Jacobian DLS IK 求解器离线计算关键帧 |
| **文件** | [generate_ik_actions.py](file:///e:/robot-policy-playground/scripts/generate_ik_actions.py) |
| **教训** | 预计算轨迹必须通过 IK/FK 验证，不能靠手动猜测 |

### 问题 23: 3-DOF IK 朝向不受控导致抓取失败

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-10 |
| **问题** | "place the cube on the shelf" 指令机械臂未正确抓取方块 |
| **原因** | 3-DOF 位置 IK 不控制夹爪朝向，夹爪可能侧向接近方块；关节空间插值导致 TCP 走弧线 |
| **解决** | 1. 升级为 6-DOF IK（`mj_jacSite` 同时计算 `jacp` + `jacr`，朝向目标=home 朝向） 2. 添加笛卡尔空间直线插值（`cartesian_segment` 逐帧 IK 求解） 3. 分段轨迹：关节空间移动 + 笛卡尔直线接近/撤离 |
| **文件** | [generate_ik_actions.py](file:///e:/robot-policy-playground/scripts/generate_ik_actions.py) |
| **教训** | 抓取任务需要 6-DOF IK 保证夹爪朝向；接近/撤离阶段必须用笛卡尔空间直线插值 |

### 问题 24: 沙箱限制 → WSL 迁移

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-10 |
| **问题** | Trae 沙箱阻止 Python 脚本访问 site-packages 和 `~/.wrangler` 目录 |
| **原因** | 沙箱文件系统限制，无法运行 MuJoCo Python 绑定和 wrangler 部署 |
| **解决** | 方案 A：项目保留 E 盘，所有终端操作在 WSL Ubuntu 中执行，node_modules 和 Python 依赖在 WSL 中安装，Windows 端仅编辑文件 |
| **教训** | WSL 迁移后 Windows 端依赖冗余需清理；node_modules 和 Python 包是平台特定的 |

### 问题 25: Home 位姿不一致

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-10 |
| **问题** | 前端 HOME_POSE 与 MuJoCo keyframe 0 不一致，回放结束时机械臂不在正确位置 |
| **原因** | HOME_POSE 使用旧值 `[1.707, -1.754, ...]`，IK 脚本使用 keyframe 0 `[0, 0, 0, -1.5708, ...]` |
| **解决** | 统一 HOME_POSE 为 MuJoCo keyframe 0 值：`[0, 0, 0, -1.5708, 0, 1.5708, -0.7854, 0.5]` |
| **文件** | [RobotArm.tsx](file:///e:/robot-policy-playground/frontend/src/components/RobotArm.tsx) |
| **教训** | 前端初始位姿必须与 MuJoCo keyframe 一致 |

---

## 阶段 10: 遥测驱动的抓取调试与动作放慢 (2026-10-11)

> 本轮新增了「动作遥测」功能（记录"下发目标 vs 仿真实际"），以下问题的定位
> 大多依赖它。完整分析见 [telemetry-analysis.md](telemetry-analysis.md)，
> 会话级总结见 [session-summary-2026-10-11.md](session-summary-2026-10-11.md)。

### 问题 26: 指令速度超出执行器物理极限

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | `pick up the cube` 夹爪闭合并未抓住方块；遥测显示夹爪闭合瞬间 TCP 离方块 0.4353 m（空夹） |
| **原因** | 轨迹峰值指令速度 **23.3 rad/s**（`place_shelf` 39.1 rad/s），而 Panda `forcerange=±87`、`armature=0.1` 估算饱和约 17 rad/s——**指令本身物理上不可执行**。实测关节跟踪误差最大 1.11 rad，TCP 因此到不了目标 |
| **解决** | 1. IK 改为"位置-only 优先 + 多初值择优"（6-DOF 硬拉会把朝向翻到 π）2. 按速度上限自动分配帧数 3. 段边界自动插入过渡帧 4. 新增迭代平滑 `smooth_velocity`。峰值降到 2.97 rad/s |
| **文件** | [generate_ik_actions.py](file:///e:/robot-policy-playground/scripts/generate_ik_actions.py) |
| **教训** | 下发速度必须与执行器能力匹配；生成脚本应内置速度校验，超限即报错而不是静默产出 |

### 问题 27: 位置-only IK 依赖"手臂残留状态"导致结果不可复现

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | 把 `pick_cube` 的抓取段复用进 `place_shelf` 后，抓取段从第 34 帧起分叉、方块不再被抬起 |
| **原因** | `solve_ik` 有两处隐藏状态依赖：① 用 `globals().get("ik_cube_touch")` 之类"顺便"把已算出的关键帧当候选初值 → 候选集合取决于调用时已算出几个关键帧；② `warm_start=None` 时求解起点实际是调用前的 `data.qpos`，内部并不复位 |
| **解决** | 新增模块级 `_SEED_POOL` 按固定顺序显式 append，`solve_ik` 只读快照；`warm_start=None` 时显式以 `home_qpos` 起算；初值去重；`cartesian_segment` 新增 `first_seed` 参数强制显式指定第 0 帧起点。**验证：连续两次生成 6 个产物 md5 逐字节一致** |
| **文件** | [generate_ik_actions.py](file:///e:/robot-policy-playground/scripts/generate_ik_actions.py) |
| **教训** | IK/优化类代码不要让结果依赖"调用前的全局或数据状态"；复用分段的前提是生成过程可复现 |

### 问题 28: 夹爪倾斜 35° 导致两指一高一低，夹不住矮物体

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | 5cm 立方体夹爪闭合瞬间 TCP 离方块仅 0.0201 m（已到位），但方块始终没被提起 |
| **原因** | 抓取姿态夹爪**倾斜 31.7°**，两指高度差 **19.0 mm**，而立方体半高仅 25 mm → 两指一高一低无法同时贴住侧面。离线模拟证实：与方块接触的只有右指和手掌，**左指从未接触** |
| **解决** | 1. 抓取物改为 3.5×3.5×10 cm（高度 10cm 让 4.4cm 的两指高度差落在物体高度内）2. 位置从 `(0.5,0.30)` 移到 `(0.5,0.22)`（更靠近基座，抬臂横扫更垂直）3. 动作放慢到 1.2 rad/s。**离线回放确认抬高 18.5cm，用户实测成功** |
| **文件** | [scene.xml](file:///e:/robot-policy-playground/public/data/panda/scene.xml) |
| **教训** | 夹爪姿态对抓取成败的影响远大于位置精度；矮物体的可用高度必须明显大于两指高度差 |

### 问题 29: 误以为夹爪开口 8cm 就能夹 6cm 物体

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | 把方块加宽到 6cm 后抓取失败，且离线模拟显示"每指只有约 5mm 夹持行程" |
| **原因** | 用 `actuator8` 实测才发现：两指对称各 4cm 行程、**总开口确实是 8cm**，但**指垫在手指内侧面**（`fingertip_pad_collision_1 pos="0 0.0055 0.0445"`），指垫间距 = 指间距 − 1.1cm，完全张开时只有 **6.9cm**。6cm 物体只需移动约 5mm 就贴上，等于"碰一下"而不是"夹住" |
| **解决** | 物体宽度改为 3.5cm（单侧夹持行程 1.70cm）；并在 `report_grasp_quality()` 里加入**夹持行程判据**，行程不足即标 ✗ |
| **文件** | [generate_ik_actions.py](file:///e:/robot-policy-playground/scripts/generate_ik_actions.py) |
| **教训** | 不要用"关节范围 × 2"推断可夹持尺寸——必须考虑接触体（指垫）相对关节的实际偏移 |

### 问题 30: 方块"被放到架子下方"

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | 用户观察到 `place the cube on the shelf` 每次都像把方块放到货架下方 |
| **原因** | 离线追踪显示：方块在**运输途中从夹爪滑脱**（抬到 z=0.2429 保持 62 帧后掉到地面 z=0.0174），释放夹爪时方块早已落地。另外原货架顶面只到 0.4 m、平台下方没有净空，放置接近路径也会被平台挡住 |
| **解决** | 1. 货架整体抬高：顶面 0.4 → **0.55 m**，腿高同步 2. 方块 `friction="1.0"`（保持时间 20 → 62 帧）。**仍未彻底解决**：夹爪倾斜 35° 产生力偶，方块在关节空间搬运段会被转出夹爪 |
| **文件** | [scene.xml](file:///e:/robot-policy-playground/public/data/panda/scene.xml) |
| **教训** | 现象（"放到架子下方"）与根因（"运输途中滑脱"）可能完全不同；必须用离线回放逐帧追踪物体高度才能区分 |

### 问题 31: 构建产物堆积导致 public/ 体积虚高

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | `public/` 达 67.65 MiB（应为 ~45 MiB），`public/assets` 里堆了 3 个 bundle 共 35MB |
| **原因** | Vite 在某些情况下没有清空 `dist`，旧 hash 包残留在 `dist/assets`，被 `sync-public.mjs` 一并复制进 `public/` |
| **解决** | 构建脚本在 `vite build` 前先清空 `frontend/dist`。现在稳定输出 80 个文件 / 45.00 MiB / 单个 bundle |
| **文件** | [package.json](file:///e:/robot-policy-playground/frontend/package.json) |
| **教训** | 内容寻址的产物目录必须每次从干净状态开始构建，否则会静默堆积 |

### 问题 32: 构建脚本"静默删除所有 .wasm"把问题推迟到线上

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | 历史上为解决 ONNX Runtime WASM 25.6MiB 超限，build 脚本里加了无条件删除所有 `.wasm` 的逻辑，依赖移除后仍保留 |
| **原因** | `@huggingface/transformers` 的 `ort-wasm-*.wasm` 超 Cloudflare 单文件 25MiB 限制；当时的应对是静默删除 |
| **解决** | 换成显式的 **25 MiB 校验闸门**（[sync-public.mjs](file:///e:/robot-policy-playground/scripts/sync-public.mjs)）：超限即带文件名/体积失败并退出，不再静默删除；需排除时在 `EXCLUDED` 清单显式登记原因 |
| **文件** | [sync-public.mjs](file:///e:/robot-policy-playground/scripts/sync-public.mjs) |
| **教训** | 用"静默删除"绕过配额限制，只会把故障从构建期推迟到线上（白屏 + Failed to fetch） |

### 问题 33: 诊断脚本自身状态不一致导致错误结论

| 项 | 内容 |
|---|------|
| **时间** | 2026-10-11 |
| **问题** | 一批诊断脚本报出"400 次随机初值扫描得最小倾斜 2.7°"，据此得出"竖直解存在、只是难找"的结论；但同一批脚本在 home 的 TCP 位置上竟报出 39.8° 倾斜，而脚本自己打印的是 `Z轴=[0,0,-1]`（0°） |
| **原因** | 诊断脚本里 `mj_forward` 的调用时机不一致、且位置-only 求解未收敛就读取朝向，导致数据不可信。**该结论已作废**；用严格归一化联合 6-DOF 求解复核后，最佳倾斜仅 **24.6°**（即该位置无法竖直抓取） |
| **解决** | 所有结论改为用"离线回放真实轨迹"（与网页行为一致：home 起始、30ms 一帧、逐帧写 actuator）交叉验证；不可复现的诊断脚本不再作为依据 |
| **文件** | [telemetry-analysis.md](telemetry-analysis.md) |
| **教训** | 诊断工具本身必须先自检（例如在已知答案的位姿上验证）；基于未收敛解得出的结论必须复核后再采信 |


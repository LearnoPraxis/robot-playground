# mujoco-react 集成规划书

> **状态：阶段 1-9 已完成，生产环境已部署**

## Context

当前项目的机械臂用 R3F 手动几何体（圆柱/盒子）实现，无物理引擎，导致：
- 机械臂穿过球，球不会移动
- 夹爪只改变间距，无法抓取物体
- IK 仅支持 2 连杆 XY 平面，运动不自然

集成 mujoco-react 后，使用 MuJoCo 物理引擎 + 真实 Franka Panda 7-DOF 机器人模型，实现物理碰撞、抓取、3D IK 拖拽。

## 可用 Skills

| Skill | 路径 | 用途 |
|-------|------|------|
| skill-creator | `c:\Users\Administrator\.trae-cn\builtin\global\skills\skill-creator` | 验证通过后，将 mujoco-react 集成模式保存为可复用 Skill |
| TRAE-code-mode-orchestrator | `c:\Users\Administrator\.trae-cn\builtin\global\skills\TRAE-code-mode-orchestrator` | 多步骤开发协调，减少 token 消耗 |
| digital-avatar-creator | `c:\Users\Administrator\.trae-cn\builtin\global\skills\digital-avatar-creator` | 代码审查 + 性能优化建议 |

## 高 Star 参考项目

| 项目 | Star | 参考价值 |
|------|------|----------|
| [mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie) | 2k+ | Franka Panda 模型源 |
| [mujoco-react-example](https://github.com/noah-wardlow/mujoco-react-example) | — | 官方 demo，IK + gizmo + 物理 |
| [panda-gym](https://github.com/qgallouedec/panda-gym) | 500+ | push/slide/pick-and-place 任务定义参考 |
| [Gemini Robotics Simulator](https://aistudio.google.com/apps/bundled/robotics_franka_pick_and_place) | — | MuJoCo WASM + Three.js + AI 控制端到端案例 |

---

## 一、设计决策

| 问题 | 决策 | 理由 |
|------|------|------|
| replay/interactive 模式切换 | App.tsx 增加 `mode: "interactive" \| "replay"` 状态 | 单一真源，模式切换原子化 |
| WS 帧应用到 MuJoCo | 用 `useCtrl()` 写 actuator 目标，物理引擎驱动 qpos | 天然支持碰撞响应 |
| 模型加载来源 | 复制 mujoco_menagerie panda 到 `public/data/panda/` 本地加载 | 避免运行时 GitHub fetch 不稳定 |
| 夹爪处理 | 每帧 8 值 = 7 关节 + 1 夹爪标量 g ∈ [0,1] | 单值控制对称手指，保持帧格式紧凑 |

## 二、实施步骤

### 阶段 1：安装与基础设施

1. **安装 mujoco-react**：`npm.cmd install mujoco-react`（在 frontend/ 目录）
2. **复制 Franka Panda 模型**：从 [mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie/tree/main/franka_emika_panda) 下载 `panda.xml` + `scene.xml` + `meshes/*.stl` 到 `public/data/panda/`
3. **自定义 scene.xml**：在场景中添加 free body 小球、立方体、货架
4. **修改 build 脚本**：移除 [package.json](file:///e:/robot-policy-playground/frontend/package.json) 中的 .wasm 删除逻辑
5. **修改 vite.config.ts**：`optimizeDeps.exclude` 添加 `mujoco-react`、`mujoco-js`

### 阶段 2：替换 RobotArm.tsx

完全重写 [RobotArm.tsx](file:///e:/robot-policy-playground/frontend/src/components/RobotArm.tsx)：

```tsx
// 公共接口
interface RobotArmProps {
  jointAngles: [number, number, number, number, number, number, number, number];
  onJointAnglesChange?: (a: typeof jointAngles) => void;
  mode: "interactive" | "replay";
}

// 组件结构
<MujocoProvider>
  <MujocoCanvas config={{ src: "/data/panda/", sceneFile: "scene.xml", homeJoints: [...] }}>
    <Scene jointAngles={jointAngles} mode={mode} />
  </MujocoCanvas>
</MujocoProvider>

// Scene 内部：
// - useIkController({ siteName: "tcp", numJoints: 7 }) → 3D IK 拖拽
// - useBeforePhysicsStep → replay 模式写入 actuator 目标
// - IkGizmo → interactive 模式显示 3D 拖拽手柄
// - 删除所有手动几何体、IK/FK 函数、TargetPoint
```

### 阶段 3：App.tsx 双模式

修改 [App.tsx](file:///e:/robot-policy-playground/frontend/src/App.tsx)：
- `jointAngles` 从 4-DOF → 8-DOF（7 关节 + 夹爪）
- 新增 `mode` 状态：发送指令时切到 `replay`，完成后切回 `interactive`
- WS 帧解析取 8 维
- footer 显示 8 个角度值

### 阶段 4：预计算数据生成 ✅

新建 `scripts/generate_ik_actions.py`（已替换 `generate_panda_actions.py`）：
- 6-DOF Jacobian DLS IK 求解器（`mj_jacSite` 同时计算 jacp + jacr）
- 朝向目标 = home 朝向（夹爪垂直向下），抓取/放置任务必须 6-DOF
- 球类任务（推球）使用纯位置 IK（3-DOF），不约束朝向
- 笛卡尔空间直线插值（`cartesian_segment`）用于接近/撤离阶段
- 关节空间插值（`joint_segment`）用于大范围移动
- 5 个任务：push_left、push_forward、pick_cube、place_shelf、push_right
- 每帧 8 值 `[j0..j6, g]`，60 帧/任务
- 输出到 `public/data/*.json`，覆盖旧 4-DOF 文件
- `task_index.json` 映射指令到 task ID

### 阶段 5：后端（最小改动） ✅

- [ws_stream.py](file:///e:/robot-policy-playground/src/ws_stream.py)：帧推送逻辑维度无关，仅更新注释
- [main.py](file:///e:/robot-policy-playground/src/main.py)、[schemas.py](file:///e:/robot-policy-playground/src/schemas.py)：无需改动
- [wrangler.jsonc](file:///e:/robot-policy-playground/wrangler.jsonc)：无需改动

### 阶段 6：构建与部署 ✅

1. `npm run build`（在 WSL 中）→ 验证 dist/assets/ 含 .wasm 文件（~10MB）
2. build 脚本排除 .wasm 文件（防 25 MiB 限制）
3. WSL 中 `npx wrangler deploy`
4. 验证生产 URL: https://robot-playground.qmes743628.workers.dev

### 阶段 7-9：生产环境修复与 IK 升级 ✅

- **阶段 7**: 修复 ERR_QUIC_PROTOCOL_ERROR（浏览器禁用 QUIC）
- **阶段 8**: 修复地面竖直（camera.up=[0,0,1]）、相机控制（WASD 键盘）、移除 SmolVLM（ONNX WASM 超 25 MiB）
- **阶段 9**: WSL 迁移（沙箱限制）、6-DOF IK 升级、笛卡尔空间直线插值、HOME_POSE 统一、回放后回归初始姿态

## 三、文件改动清单

| 操作 | 文件 |
|------|------|
| **REPLACE** | `frontend/src/components/RobotArm.tsx` |
| **MODIFY** | `frontend/src/App.tsx`（8-DOF + mode + resetSignal + 回放后回归 HOME_POSE） |
| **MODIFY** | `frontend/package.json`（build 脚本 + dep，移除 @huggingface/transformers） |
| **MODIFY** | `frontend/vite.config.ts`（optimizeDeps + COOP/COEP headers） |
| **MODIFY** | `frontend/src/hooks/useWebSocket.ts`（仅注释） |
| **MODIFY** | `frontend/src/components/ControlPanel.tsx`（重置机械臂按钮） |
| **MODIFY** | `src/ws_stream.py`（仅 docstring） |
| **NEW** | `scripts/generate_ik_actions.py`（6-DOF IK + 笛卡尔直线插值） |
| **NEW** | `public/data/panda/`（panda.xml, scene.xml, meshes/） |
| **NEW** | `public/data/*.json`（5 个 8-DOF 任务文件 + task_index.json） |
| **DELETE** | `scripts/generate_actions.py`（旧 4-DOF 脚本） |
| **DELETE** | `scripts/generate_panda_actions.py`（手动猜测角度，无 IK 验证） |
| **DELETE** | `frontend/src/components/SmolVLMTester.tsx`（ONNX WASM 无法部署） |

## 四、验证清单

1. ✅ `npm run build` 后 dist/assets/ 含 .wasm（~10MB）
2. ✅ Franka Panda 模型加载无白屏
3. ✅ interactive 模式拖拽 IkGizmo → 7-DOF 跟随
4. ✅ 拖拽 TCP 接触小球 → 球被物理推开
5. ✅ 发送 "push ball left" → replay 模式 60 帧动画
6. ✅ replay 完成后自动切回 interactive + 回归 HOME_POSE
7. ✅ 部署后 workers.dev 模型加载正常
8. ⏳ pick_cube 任务夹爪先开后合 → 立方体被提起（6-DOF IK + 笛卡尔直线插值，待验证）
9. ⏳ place_shelf 任务方块放置到货架正中间（待验证）

## 五、风险

| 风险 | 缓解 |
|------|------|
| mujoco-react 依赖弃用 mujoco-js | PoC 验证后迁移到 @mujoco/mujoco |
| WASM 首次加载慢 1-3s | isPending 显示 loading |
| actuator 名字不符 | 用 Python 导出实际 actuator 名单 |
| 路径大小写 Linux 敏感 | 统一用小写路径 |
| React 18 StrictMode 双挂载 | dev 期临时移除 StrictMode |
| 慢速网络 QUIC 传输大 mesh 超时 | 浏览器禁用 QUIC 回退 HTTP/2 |
| 6-DOF IK 朝向约束过严（球太低） | 球类任务用 3-DOF 位置 IK 不约束朝向 |

# 会话总结（2026-10-11）—— 遥测驱动调试 / 动作放慢 / 抓取成功

> 本文按 [.trae/commands/summarize-pause.md](../commands/summarize-pause.md) 的要求撰写，
> 供下次恢复时快速定位上下文。

## 一、本次完成的工作

### 1. 动作遥测功能（新增，前端）

给网页加了「动作遥测」面板：在**物理引擎回调内部**采样"下发目标 vs 仿真实际"，
导出可复制的 JSON，回答两个肉眼无法区分的问题——轨迹算错 vs 仿真跟不上。

| 文件 | 作用 |
| --- | --- |
| `frontend/src/telemetry/telemetry.ts` | 模块级单例录制器；`useBeforePhysicsStep` 记下发目标、`useAfterPhysicsStep` 记实际 qpos/夹爪/TCP/物体/接触数 |
| `frontend/src/telemetry/useTelemetry.ts` | `useSyncExternalStore` 订阅，不经过 React 渲染 |
| `frontend/src/telemetry/actions.ts` | 手动录制、下载/复制 JSON |
| `frontend/src/components/DebugPanel.tsx` | 侧栏面板 + 启发式判据文字 |

采样内容：`cmd` / `cmdLive` / `cmdi` / `cmdage` / `arm` / `grip` / `tcp` / 物体坐标 /
`ncon` / 物理时间 / 墙钟时间；结算出逐关节跟踪误差、夹爪行程、物体位移、
夹爪闭合瞬间 TCP→物体距离、实时因子、物理步长、采样率。

### 2. 部署与线上验证（2026-10-11）

- 前端 bundle 本来就与线上**一致**（内容哈希相同），落后的是 5 个轨迹 JSON
  （`wrangler deploy` 输出 "Found 5 new or modified static assets" 可印证）
- 部署后逐字节比对：5 个 JSON + `task_index.json` 与本地完全一致
- HTTP / WebSocket 端到端验证通过（60 帧、8 维、首末帧符合预期）

### 3. IK 生成脚本的多轮修复

| 修复 | 效果 |
| --- | --- |
| 位置-only 优先 + 多初值择优（替代会让朝向翻到 π 的 6-DOF 硬拉） | 消除"夹爪朝上"的坏解 |
| 按速度上限自动分配帧数 + 段边界自动过渡 + 迭代平滑 | `pick_cube` 峰值 23.3 → 2.97 rad/s |
| 「迭代步长」与「帧间位移上限」拆成两个常量 | 修掉早期把两者混用导致 IK 不收敛的问题 |
| **动作整体放慢**：`MAX_JOINT_VEL` 3.0 → **1.2 rad/s** | 帧数按比例增加（服务端帧间隔固定 30ms，放慢只能靠加帧） |
| `save_task` 按**实测峰值速度**迭代放大帧数 | 仅用公式估算会低估（关键帧时间占比不均） |
| **消除生成过程的隐藏状态依赖**（见下） | 两次生成 md5 逐字节一致 |

### 4. 抓取成功（用户实测确认）

**关键两处改动**：

1. 放慢到 1.2 rad/s（`pick_cube` 49 → 107 帧）
2. 方块位置 `(0.5, 0.30)` → **`(0.5, 0.22)`**（更靠近基座，抬臂横扫更垂直）

离线回放验证（真实轨迹喂 MuJoCo，home 起始、30ms 一帧）：
**cube z 0.0500 → 峰值 0.2354，抬高 18.5 cm** ✓

### 5. 场景改动

- 抓取物：5cm 立方体 → **3.5×3.5×10 cm 长方体**（依据：夹爪总开口 8cm，但指垫在内侧面、
  指垫间距仅 6.9cm；3.5cm 宽给出 1.70cm 单侧夹持行程。高度 10cm 容忍 4.4cm 两指高度差）
- 方块 `friction="1.0 0.005 0.0001"`（提高摩擦，减少运输滑脱）
- **货架抬高**：顶面 0.4 → **0.55 m**，腿高同步（原来平台下方没有净空，放置路径被挡）

### 6. 构建与仓库治理

- `scripts/sync-public.mjs`：用 **25 MiB 校验闸门**替代"静默删除所有 .wasm"
- 构建前清空 `frontend/dist`（此前会堆积旧 hash 包，`public/` 虚高到 67.65 MiB，现 45.00 MiB）
- 忽略 `src/vendor/`（`pywrangler sync` 的产物）
- 13 个提交推送到 GitHub；新增根级 `README.md`

## 二、未完成的工作及原因

### 1. `place_shelf_001` 端到端失败（高优先级）

| 指标 | 值 |
| --- | --- |
| 帧数 / 峰值 / 超限帧 | 239 / 2.12 rad/s / **53 帧超限** |
| 离线验证 | **未抬起方块**（峰值 0.0567） |

三个独立问题：

1. **速度峰值与帧数无关**：放大 1.4 倍后峰值反而升到 3.5 rad/s，说明是
   **段间不连续**而非速度问题，`smooth_velocity` 压不下。已改为"放大无改善即停止并回退历史最佳"。
2. **运输途中方块滑脱**：夹爪倾斜 35° 产生力偶，方块在搬运段被转出夹爪。
   摩擦 1.0 使保持时间 20 → 62 帧，但仍会掉。
3. 表现为用户观察到的 **"每次都放到架子下方"**（释放时方块早已落地）。

### 2. 合并抓取段失败（任务 2，已尝试但回退）

把 `pick_cube` 的抓取段复用进 `place_shelf` 后，抓取段**从第 34 帧起分叉**
（夹爪闭合帧 36 vs 40）。已排除的原因：

| 怀疑点 | 验证结果 |
| --- | --- |
| 关键帧值不同 | 调试打印 → 两处**逐个数值完全一致** |
| `_SEED_POOL` 大小不同 | 两处都是 9 |
| 位置-only IK 依赖残留状态 | 单独验证 → **给定同一初值时与残留状态无关** |
| `cartesian_segment` 首帧起点不定 | 已用 `first_seed` 显式固定 |

**仍有至少一个未定位的状态依赖。** `build_place_shelf` 因此保持**自包含**生成。

### 3. 浏览器端的最终确认需要用户执行

`pick_cube` 用户已实测成功；`place_shelf` 尚未在浏览器里验证过修复效果。

## 三、关键文件路径与配置

### 场景与数据

| 路径 | 关键值 |
| --- | --- |
| `public/data/panda/scene.xml` | 方块 `pos="0.5 0.22 0.05"`、`size="0.0175 0.0175 0.05"`、`friction="1.0 0.005 0.0001"`；货架顶面 `pos="0 0 0.55"` |
| `public/data/*.json` | 5 条轨迹（pick_cube 113 / place_shelf 239 / push_left 161 / push_right 161 / push_forward 214 帧） |
| `src/ws_stream.py` | `_FRAME_INTERVAL = 0.03`（服务端帧间隔固定，改不了 → 放慢只能加帧） |

### 生成脚本常量（`scripts/generate_ik_actions.py` 顶部）

```python
FRAMES = 60              # 默认帧数
FRAME_DT = 0.03          # 服务端帧间隔
MAX_JOINT_VEL = 1.2      # 单关节角速度上限（rad/s）
FRAMES_MAX = 400         # 单任务帧数上限
IK_MAX_ITER_STEP = 0.15  # IK 单次迭代步长（与帧间位移上限是两回事）
_SEED_POOL = []          # 显式初值池（不要再改成读 globals()）
```

### 前端

| 路径 | 说明 |
| --- | --- |
| `frontend/src/telemetry/telemetry.ts` | 遥测录制器（本次新增的核心） |
| `frontend/vite.config.ts` | `publicDir: '../public'`、`/api` 与 `/ws` 代理、COOP/COEP |
| `frontend/package.json` | build 脚本含清空 dist + 25MiB 闸门 |

### 环境要点

- **所有终端操作必须在 WSL Ubuntu 中执行**（Windows 侧 `node_modules` 是 WSL 装的，
  缺 `@rollup/rollup-win32-x64-msvc`，Windows 里 `npm run build` 必然失败）
- 生成轨迹：`wsl -d Ubuntu -- bash -lc 'cd /mnt/e/robot-policy-playground && python3 scripts/generate_ik_actions.py'`
- 本地起服务：`./start_dev.sh`（= `pywrangler dev`，默认 8787）
- 部署：`export CLOUDFLARE_API_TOKEN=... && pywrangler deploy`（不是 `npx wrangler deploy`）

## 四、下次恢复时的待办

按优先级：

1. **定位最后的 IK 状态依赖**：在 `build_pick_segments` 内对每个分段的**首末帧关节值**
   各打印一次（两次调用分别打），缩小到具体哪一段、哪一帧开始不同。
   重点怀疑 `solve_ik` 候选择优里 `min(...)` 在**多个候选评分相同时**的选取
   （`min` 取第一个，但候选顺序可能受之前分段影响）。
2. **修 `place_shelf` 的段间不连续**：3.1 rad/s 峰值与帧数无关，定位到具体边界后
   用 `save_segments` 的过渡帧逻辑覆盖。
3. **解决运输滑脱**：夹爪倾斜是硬约束（该位置无法竖直抓取，已用归一化联合 6-DOF
   求解 + 30 初值确认最佳仅 24.6°）。可考虑：缩短搬运路径（货架挪近）／
   加一段"夹紧稳定"保持／换更矮胖、不易被力偶转出的抓取物。
4. 需要时把 `pick_cube` 的临时改动（`_SEED_POOL` 相关）回归验证一遍浏览器端。

### 明确的历史结论（避免重复走弯路）

- **"400 次初值扫描得最小倾斜 2.7°"是不可靠的**：那批脚本 `mj_forward` 状态不一致
  （在 home 的 TCP 位置上竟报 39.8°，而脚本自己打印 `Z轴=[0,0,-1]`）。结论作废。
- **home 位姿的夹爪是严格竖直的（0.0°）**，`MAT[2,2] = -1.0`。
  生成脚本"用 home 朝向当朝下目标"的前提**没有错**。
- **夹爪真实几何**（用 `actuator8` 实测）：两指对称各 4cm 行程、总开口 8cm；
  但指垫在**内侧面**，指垫间距 = 指间距 − 1.1cm，完全张开时仅 **6.9cm**。
- **旧位置 `(0.5,0.30)` 的失败机制**：第 19-20 帧两指同时接触、只抬高 0.9mm 后
  方块翻倒（末态 z=0.0174 = 半宽），一倒就夹不住。

## 五、进程与状态

- 本会话无残留后台任务、无 subagent
- WSL 中 `pywrangler dev`（PID 9849，端口 8787）**是用户自己的测试服务，未关闭**
- 工作区干净，全部改动已推送到 GitHub

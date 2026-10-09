# 4 DOF 机械臂升级计划

## Context

当前机械臂只有 2 DOF（肩+肘），无法完成抓取和放置任务（缺少夹爪和底座旋转）。升级为 4 DOF（底座旋转 + 2 连杆 + 夹爪）后可覆盖全部 5 个预设任务，同时修复坐标系不一致问题（IK 在 XY 平面计算，但渲染绕 X 轴旋转导致运动在 YZ 平面）。

## 关节配置

| 关节 | 轴 | 用途 |
|------|-----|------|
| j0 | Y 轴 (底座旋转) | 水平转向目标 |
| j1 | Z 轴 (肩关节) | 平面内俯仰 |
| j2 | Z 轴 (肘关节) | 平面内弯曲 |
| j3 | 标量 (夹爪) | 0=闭合, 1=打开 |

## 实施步骤

### 1. 前端 RobotArm.tsx 改动

文件：`frontend/src/components/RobotArm.tsx`

**1a. 类型定义**
- `RobotArmProps.jointAngles`: `[number, number]` → `[number, number, number, number]`
- `inverseKinematics` 返回类型: `[number, number, number] | null`（j0, j1, j2）
- `forwardKinematics` 输入改为 `(j1, j2)` 返回 `[number, number]`（平面内坐标）

**1b. IK 改动**
- `inverseKinematics(x, y)` 保持不变（2 连杆解析解），只解 j1, j2
- 新增 `computeBaseAngle(targetX, targetZ)`: `atan2(targetZ, targetX)` 计算 j0
- j3 从外部传入（拖拽时不改变夹爪）

**1c. FK 改动**
- `forwardKinematics(j1, j2)` 返回平面内 `[x, y]`（不变逻辑）
- 新增 `forwardKinematics3D(j0, j1, j2)`: 先 FK 得 `[x, y]`，再绕 Y 轴旋转得 3D 坐标

**1d. Arm 组件改动**
- 解构 `[j0, j1, j2, j3]`
- 嵌套结构：
  ```
  <group rotation={[0, j0, 0]}>     // 底座旋转
    <group rotation={[0, 0, j1]}>   // 肩关节（Z 轴，修复坐标系）
      连杆 1
      <group position={[0, L1, 0]} rotation={[0, 0, j2]}>
        连杆 2
        <group position={[0, L2, 0]}>
          夹爪（两个方块，间距 = j3 * 0.1）
        </group>
      </group>
    </group>
  </group>
  ```
- 夹爪 mesh：两个小 box，position 随 j3 变化

**1e. 拖拽逻辑**
- 拖拽目标点保持在 XY 平面（z=0），解释为底座局部坐标
- X = 水平距离, Y = 高度
- j0 不随拖拽变化（从预计算数据或球方向自动计算）
- 拖拽时 IK 解 j1, j2，j3 保持当前值

**1f. Scene 组件**
- `targetPos` 初始化用 `forwardKinematics(j1, j2)`
- 球位置改为 3D（x, z 在水平面，y=固定高度）

### 2. App.tsx 改动

文件：`frontend/src/App.tsx`

- `jointAngles` state: `[0, 0]` → `[0, 0, 0, 0.5]`（夹爪半开）
- WebSocket actions 取值: `last[0], last[1]` → `last[0], last[1], last[2], last[3]`

### 3. 预计算数据重新生成

编写生成脚本 `scripts/generate_actions.py`，为 5 个任务生成 4 维动作序列：

| 任务 | j0 (底座) | j1, j2 (连杆) | j3 (夹爪) |
|------|-----------|---------------|-----------|
| push ball left | 转向球 | 弧线推动 | 0 (闭合) |
| push ball right | 转向球 | 弧线推动 | 0 |
| push ball forward | 0 | 直线推动 | 0 |
| pick up cube | 转向方块 | 伸出-收回 | 1→0 (开→合) |
| place on shelf | 转向货架 | 举高-放下 | 0→1 (合→开) |

每任务 60 帧，格式：`{"i": "...", "ja": [[j0,j1,j2,j3],...], "d": 2.0, "fc": 60}`

### 4. 后端无改动

- `ws_stream.py` 的 `_stream_task` 只推送 `ja` 数组，不关心维度
- `main.py` 不变
- DO 的 `webSocketMessage` 不变

### 5. 构建与部署

- `npm run build`（前端）
- 复制 `dist/` 到 `public/`
- `npx wrangler deploy`

## 验证

1. 前端构建无 TypeScript 错误
2. 生产环境打开后 4 DOF 机械臂正确渲染（底座 + 2 连杆 + 夹爪）
3. 拖拽目标点时 j1, j2 实时变化，无控制台报错
4. 发送 "push ball left" 指令后 60 帧动作播放，底座旋转 + 推球 + 夹爪闭合
5. 发送 "pick up the cube" 指令后夹爪先开后合

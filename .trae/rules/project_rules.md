# Robot Policy Playground 项目规则

## 部署平台
- Cloudflare Workers（免费计划）
- 禁止使用 Containers、Workers AI

## 免费计划硬性约束（必须遵守）
- Worker CPU 时间 ≤ 10ms/请求，禁止在 Worker 中执行推理
- Worker 内存 ≤ 128 MB
- 每日请求 ≤ 100,000 次（API + WebSocket 连接建立共享）
- 静态资源请求免费无限
- 单个静态文件 ≤ 25 MiB
- 静态文件总数 ≤ 20,000 个/Worker
- Durable Objects 必须使用 SQLite 后端（new_sqlite_classes）

## 技术栈
- 前端：React 18 + TypeScript + Vite + React Three Fiber + mujoco-react@8.2.1
- 后端：Python Workers + FastAPI（workers.asgi）
- 实时通信：Durable Objects + WebSocket
- 3D 物理引擎：MuJoCo WASM（内联于 JS chunk，10.1MB）

## 开发环境
- 项目文件保留在 E 盘（E:\robot-policy-playground）
- 所有终端操作在 WSL Ubuntu 中执行（npm、pip、wrangler、python）
- Windows 端仅用于编辑文件
- node_modules 和 Python 依赖是平台特定的，WSL 中需独立安装
- **Windows 侧无法构建前端**：`frontend/node_modules` 是 WSL 装的，
  缺 `@rollup/rollup-win32-x64-msvc`，在 Windows 里 `npm run build` 必然失败
- **部署命令用 `pywrangler deploy`**（不是 `npx wrangler deploy`）：
  `pywrangler` 是 Cloudflare 的 Python Workers CLI，会在部署前自动 `sync`
  把 `pyproject.toml` 的依赖装进 `src/vendor/`（该目录已 gitignore）。
  需要 `export CLOUDFLARE_API_TOKEN=...`（非交互环境无法 `wrangler login`）
- 本地起服务：`./start_dev.sh`（= `pywrangler dev`，默认 8787）
- 前端构建命令：`cd /mnt/e/robot-policy-playground/frontend && npm run build`
  （脚本已内含"清空 dist"与"25 MiB 单文件校验闸门"）

## 预计算策略
- IK 推理在本地 WSL 中完成（generate_ik_actions.py）
- 动作序列 JSON ≤ 500 帧（脚本内实际上限 `FRAMES_MAX = 400`），压缩存储
- **帧数必须由实测峰值速度反推**，不要写死：服务端帧间隔固定 30ms
  （`src/ws_stream.py` 的 `_FRAME_INTERVAL`），所以"放慢动作"只能靠增加帧数
- **单关节角速度上限 `MAX_JOINT_VEL = 1.2 rad/s`**（2026-10-11 用户要求放慢；
  历史上 3.0 也曾可用，23.3 则物理上不可执行）。生成脚本会按实测值迭代放大帧数
- **生成过程必须可复现**：`solve_ik` 的初值必须全部显式传入
  （禁止读 `globals()` 或依赖调用前的手臂状态）；连续两次生成应逐字节一致
- 预计算数据放在 public/data/ 下
- Franka Panda 7-DOF + 夹爪模型放在 public/data/panda/ 下
- **抓取/放置几何从模型读取**（`qpos0` + `geom_size`），不要在脚本里写死坐标，
  否则改场景后脚本与数据会不同步

## IK 与轨迹规范
- **位置-only IK 优先**：先用多个显式初值做 3-DOF 位置求解，接受"位置准 + 夹爪朝下"
  的解；6-DOF（`mj_jacSite` 同时算 jacp + jacr）**仅作兜底**。
  原因：朝向误差接近 π 时 6-DOF 阶段是不稳定平衡，会把好解推成"夹爪朝上"的坏解
- 朝向目标 = home 朝向；**home 的夹爪是严格竖直的（0°，`MAT[2,2] = -1.0`）**，
  以此为朝向目标的前提没有错
- 球类任务（推球）使用纯位置 IK（3-DOF），不约束朝向
- 接近/撤离阶段使用笛卡尔空间直线插值（cartesian_segment，逐帧 IK）；
  它的**第 0 帧必须显式传 `first_seed`**，否则起点取决于内部初值池
- 大范围移动使用关节空间插值（joint_segment）
- **段边界必须检查关节跳变**：`save_segments` 会在超限处插入过渡帧；
  残留尖峰由 `smooth_velocity` 迭代插中点消除；仍超限说明是段间不连续而非速度问题
- HOME_POSE = MuJoCo keyframe 0：[0, 0, 0, -1.5708, 0, 1.5708, -0.7854, 0.5]
- 回放结束后自动回到 HOME_POSE

## 夹爪几何与抓取物选型（2026-10-11 实测）
- 夹爪**总开口 8cm**（两指对称、各 4cm 行程，`finger_joint range 0 0.04`）
- 但**指垫在手指内侧面**（`fingertip_pad_collision_1 pos="0 0.0055 0.0445"`），
  **指垫间距 = 指间距 − 1.1cm，完全张开时只有 6.9cm**
- 因此抓取物宽度必须**明显小于 6.9cm**：太接近会让夹持行程只剩几毫米，
  等于"碰一下"而不是"夹住"（6cm 方箱实测失败）。当前取 3.5cm → 单侧行程 1.70cm
- 抓取物高度必须**明显大于两指高度差**。夹爪在抓取点无法竖直（该位置最佳
  倾斜约 25°，实际约 35°），两指高度差约 4.4cm，故物体取 10cm 高
- `report_grasp_quality()` 会在生成时打印倾斜角/两指高度差/单侧夹持行程，
  任一项不达标即标 ✗

## 相机控制规范
- camera.up = [0, 0, 1]（匹配 MuJoCo Z-up 坐标系）
- OrbitControls mouseButtons：LEFT=undefined（IK 专用），MIDDLE=zoom，RIGHT=undefined
- 视角旋转：WASD/方向键（球坐标操作，不使用鼠标拖拽）
- 缩放：Q/E 键

## 文件位置规则
- 模型文件（mesh、XML、JSON）统一存放在 E:\robot-policy-playground\public\data\panda\
- 尽量避免操作 C 盘文件，新文件优先使用 E 盘路径

## 已知问题
- Cloudflare workers.dev 默认 QUIC (HTTP/3)，慢速网络下大 mesh 文件传输可能触发 ERR_QUIC_PROTOCOL_ERROR
- 如遇 MuJoCo 加载失败，建议浏览器禁用 QUIC 或精简 mesh 文件
- ONNX WASM 无法部署到 Cloudflare Workers 免费计划（25 MiB 限制）
- mujoco-react 不自动转换坐标系，需手动设置 camera.up
- **静态资源单文件 25 MiB 是硬限制**：构建脚本内置校验闸门，超限即失败并报出
  文件名与体积（`scripts/sync-public.mjs`）。不要用"静默删除"绕过——那只会让故障
  推迟到线上变成白屏
- **构建前必须清空 `frontend/dist`**，否则旧 hash 产物会堆积并被复制进 `public/`
- **夹爪倾斜是该抓取点的硬约束**（该位置最佳约 25°）：不要指望通过调 IK 得到竖直抓取，
  应通过物体选型（窄而高）来容忍倾斜

## 代码规范
- 前端函数组件 + Hooks，TypeScript 严格模式
- 后端 Pydantic v2，类型注解完整
- API 路径以 /api/ 开头，WebSocket 以 /ws/ 开头
- **数值/优化类代码必须可复现**：函数结果只由图传入的入参决定，
  不要读全局变量（尤其不要用 `globals()` 去"顺便"收集已算出的中间结果），
  也不要依赖"上一次调用留下的全局/数据状态"
- 生成或构建类脚本要**自检并报错**（速度超限、尺寸超限、朝向不达标等），
  不要静默产出坏数据或静默删除文件

## 调试与验证约定
- **验证结论必须用"离线回放真实轨迹"交叉确认**：与网页行为一致
  （home 起始、30ms 一帧、逐帧写 actuator），逐帧记录物体高度与接触
- 诊断脚本本身要先自检（在已知答案的位姿上验证），
  不要用未收敛的解或状态不一致的读数下结论
- 网页端「动作遥测」面板是定位"下发目标 vs 仿真实际"差异的首选工具；
  改了前端逻辑后，遥测的判据（跟踪误差、TCP→物体距离、物体高度）要用它复核

## Skills 管理
- Agent 自主安装 Skills 前必须列出候选及来源，等待确认

## 交互约定
- 代码变更前先说明修改意图
- 生成文件放入正确目录
- 终端命令先给出再执行

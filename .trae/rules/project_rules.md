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

## 预计算策略
- PocketVLA 推理在本地完成
- 动作序列 JSON ≤ 500 帧，压缩存储
- 预计算数据放在 public/data/ 下
- Franka Panda 7-DOF + 夹爪模型放在 public/data/panda/ 下

## 文件位置规则
- 模型文件（mesh、XML、JSON）统一存放在 E:\robot-policy-playground\public\data\panda\
- 尽量避免操作 C 盘文件，新文件优先使用 E 盘路径

## 已知问题
- Cloudflare workers.dev 默认 QUIC (HTTP/3)，慢速网络下大 mesh 文件传输可能触发 ERR_QUIC_PROTOCOL_ERROR
- 如遇 MuJoCo 加载失败，建议浏览器禁用 QUIC 或精简 mesh 文件

## 代码规范
- 前端函数组件 + Hooks，TypeScript 严格模式
- 后端 Pydantic v2，类型注解完整
- API 路径以 /api/ 开头，WebSocket 以 /ws/ 开头

## Skills 管理
- Agent 自主安装 Skills 前必须列出候选及来源，等待确认

## 交互约定
- 代码变更前先说明修改意图
- 生成文件放入正确目录
- 终端命令先给出再执行

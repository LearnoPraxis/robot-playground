"""通过 WebSocket 流式推送预计算动作帧的 Durable Object。

该 DO 从静态资源中加载单个任务的动作 JSON，然后以约 30ms 的间隔
将关节角度帧推送给客户端。由于 Durable Object 每次调用有 30 秒的
CPU 预算（而普通 Worker 只有 10ms），因此完整序列的解析和流式
推送都在这里完成。

帧格式（与维度无关）：
- Franka Panda 7-DOF + 夹爪：每帧 ``ja`` 为长度 8 的数组
  ``[j0, j1, j2, j3, j4, j5, j6, gripper]``，gripper ∈ [0, 1]
- 该 DO 不关心维度，只透传 ``ja`` 数组给客户端
"""

import asyncio
import json

from js import WebSocketPair
from workers import DurableObject, Response

_FRAME_INTERVAL = 0.03  # 帧间隔约 30ms（约 33 fps）
_TASK_DATA_PREFIX = "/data/"


class WSStream(DurableObject):
    """将预计算的动作序列流式推送给 WebSocket 客户端。"""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)

    async def fetch(self, request):
        """将传入的请求升级为 WebSocket 连接。

        使用 Hibernation API（self.ctx.acceptWebSocket）接受连接，
        允许 DO 在空闲时休眠以节省费用。
        """
        # 创建 WebSocket 对（客户端 + 服务端）
        client, server = WebSocketPair.new().object_values()

        # 使用 Hibernation API 接受服务端 WebSocket
        self.ctx.acceptWebSocket(server)

        # 返回客户端 WebSocket 给浏览器
        return Response(None, status=101, web_socket=client)

    async def webSocketMessage(self, ws, message):
        """处理来自客户端的消息。

        期望的载荷格式为 ``{"task_id": "<id>"}``。
        之后 DO 会流式推送该任务的所有关节角度帧。
        心跳消息 ``{"type": "ping"}`` 会被忽略。
        """
        if isinstance(message, bytes):
            message = message.decode("utf-8")

        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self._send_json(ws, {"type": "error", "message": "Invalid JSON payload"})
            return

        # 忽略心跳消息
        if payload.get("type") == "ping":
            self._send_json(ws, {"type": "pong"})
            return

        task_id = payload.get("task_id")
        if not task_id:
            self._send_json(ws, {"type": "error", "message": "Missing task_id"})
            return

        await self._stream_task(ws, str(task_id))

    async def webSocketClose(self, ws, code, reason, wasClean):
        """客户端断开连接时的清理回调。"""
        pass

    async def _stream_task(self, ws, task_id: str) -> None:
        """从资源中加载任务的动作 JSON 并流式推送其帧。"""
        from workers import Request

        path = f"{_TASK_DATA_PREFIX}{task_id}.json"
        req = Request(f"http://assets{path}")
        resp = await self.env.ASSETS.fetch(req)

        if resp.status != 200:
            self._send_json(
                ws,
                {"type": "error", "message": f"Task data not found for task_id={task_id!r}"},
            )
            return

        text = await resp.text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._send_json(ws, {"type": "error", "message": "Task data is not valid JSON"})
            return

        frames = data.get("ja") or data.get("joint_angles") or []
        if not isinstance(frames, list):
            self._send_json(ws, {"type": "error", "message": "Task data has no frame list"})
            return

        self._send_json(ws, {"type": "start", "fc": len(frames)})

        for idx, frame in enumerate(frames):
            self._send_json(ws, {"type": "frame", "i": idx, "ja": frame})
            await asyncio.sleep(_FRAME_INTERVAL)

        self._send_json(ws, {"type": "done"})

    @staticmethod
    def _send_json(ws, obj: dict) -> None:
        """将对象序列化为 JSON 并发送给客户端。"""
        ws.send(json.dumps(obj, separators=(",", ":")))

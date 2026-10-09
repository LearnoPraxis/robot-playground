"""Robot Policy Playground 的 FastAPI Worker 入口。

本 Worker 故意不执行任何推理。它仅从静态资源中读取一份小型的
任务索引并返回 task_id；完整的动作序列由 WSStream Durable Object
通过 WebSocket 连接流式推送。这样可以确保每个请求都远低于免费套餐
10ms 的 CPU 预算。
"""

import json

from fastapi import FastAPI, Request as FastAPIRequest
from workers import WorkerEntrypoint, asgi, Response

from schemas import InferRequest, InferResponse
from ws_stream import WSStream  # noqa: F401  （导出以供 Durable Object 绑定使用）

app = FastAPI(title="Robot Policy Playground")

_INDEX_PATH = "/data/task_index.json"


async def _load_task_index(env) -> dict:
    """从静态资源中加载精简的任务索引。

    索引故意保持很小（<=100 条），使得 json.loads
    能远低于 Worker 10ms 的 CPU 预算。完整的动作
    序列永远不会在这里加载。
    """
    from workers import Request

    req = Request(f"http://assets{_INDEX_PATH}")
    resp = await env.ASSETS.fetch(req)
    text = await resp.text()
    return json.loads(text)


@app.get("/api/health")
async def health() -> dict:
    """轻量级健康检查。"""
    return {"status": "ok"}


@app.post("/api/infer")
async def infer(body: InferRequest, request: FastAPIRequest) -> InferResponse:
    """将自然语言指令解析为 task_id。

    仅返回 task_id。客户端需要向 WSStream Durable Object
    建立 WebSocket 连接，以接收流式推送的动作帧。
    """
    env = request.scope.get("env")
    if env is None:
        return InferResponse(success=False, message="Worker environment unavailable")

    try:
        index = await _load_task_index(env)
    except Exception as exc:  # noqa: BLE001
        return InferResponse(success=False, message=f"Failed to load task index: {exc}")

    instruction = (body.instruction or "").strip().lower()
    task_id = index.get(instruction)
    if task_id:
        return InferResponse(task_id=task_id, success=True, message="ok")

    return InferResponse(
        success=False,
        message=f"Unknown instruction: {body.instruction!r}",
    )


class Default(WorkerEntrypoint):
    """Worker 入口点，将请求委托给 FastAPI ASGI 应用处理。

    WebSocket 请求（路径以 /ws/ 开头）被转发到 WSStream
    Durable Object，由其处理 WebSocket 升级和帧流式推送。
    其余请求交给 FastAPI 应用。
    """

    async def fetch(self, request):
        from urllib.parse import urlparse

        path = urlparse(request.url).path
        if path.startswith("/ws/"):
            # 检查 WebSocket 升级请求
            upgrade_header = request.headers.get("Upgrade")
            if not upgrade_header or upgrade_header != "websocket":
                return Response("Expected Upgrade: websocket", status=426)

            do_id = self.env.WS_STREAM.idFromName("stream")
            do_stub = self.env.WS_STREAM.get(do_id)
            return await do_stub.fetch(request)
        return await asgi.fetch(app, request, self.env)

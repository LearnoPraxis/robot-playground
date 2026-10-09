"""Robot Policy Playground API 的 Pydantic v2 数据模型。"""

from pydantic import BaseModel, Field


class InferRequest(BaseModel):
    """推理接口的请求体。

    仅携带自然语言指令；Worker 执行轻量级的索引查找，
    并返回 task_id，而不将任何动作序列加载到内存中。
    """

    instruction: str = Field(..., description="自然语言指令。")


class InferResponse(BaseModel):
    """推理接口的响应体。

    仅返回 task_id，以便客户端可以向 Durable Object
    建立 WebSocket 连接来流式接收完整的动作序列。
    """

    task_id: str = Field(default="", description="解析得到的任务标识符。")
    success: bool = Field(default=False, description="指令是否匹配到已知任务。")
    message: str = Field(default="", description="人类可读的状态消息。")

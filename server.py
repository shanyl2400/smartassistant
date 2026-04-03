from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from agentscope.pipeline import stream_printing_messages
from agentscope.session import RedisSession
from agentscope_runtime.engine import AgentApp
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope.agent import AgentBase
from agents.route_agent import get_router_agent


from agents.smartassistant import get_smartassistant_agent
from agents.docqa import get_docqa_agent
from agents.writing import get_writing_agent
from agents.chat import get_chat_agent
from agents.translate import get_translate_agent
from memory.short_term_memory import get_short_term_memory
from memory.long_term_memory import get_long_term_memory

print("✅ 依赖导入成功")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理服务启动和关闭时的资源"""
    # 启动时：初始化 Session 管理器
    import fakeredis

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # 注意：这个 FakeRedis 实例仅用于开发/测试。
    # 在生产环境中，请替换为你自己的 Redis 客户端/连接
    #（例如 aioredis.Redis）。
    app.state.session = RedisSession(connection_pool=fake_redis.connection_pool)

    yield  # 服务运行中

    # 关闭时：可以在此处添加清理逻辑（如关闭数据库连接）
    print("AgentApp is shutting down...")

agent_app = AgentApp(
    app_name="知识助手",
    app_description="一个智能的知识助手，可以根据用户的问题，调用工具来回答问题。",
    lifespan=lifespan, # 传入生命周期函数
)

print("✅ Agent App创建成功")


def _pre_print_attach_tool_trace(self: AgentBase, kwargs: dict[str, Any]) -> dict[str, Any]:
    """在 print 进入队列前，把本轮消息里的 tool 调用参数与结果写入 metadata，便于前端读取。

    仅在流式片段的最后一次 print（last=True）写入，避免参数/结果尚未拼完就推送。
    """
    msg = kwargs.get("msg")
    if msg is None:
        return kwargs
    content = getattr(msg, "content", None)
    if not isinstance(content, list):
        return kwargs
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "arguments": block.get("input"),
                },
            )
        elif btype == "tool_result":
            tool_results.append(
                {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "output": block.get("output"),
                },
            )
    if not tool_calls and not tool_results:
        return kwargs
    md = dict(msg.metadata) if getattr(msg, "metadata", None) else {}
    if tool_calls:
        md["tool_calls"] = tool_calls
    if tool_results:
        md["tool_results"] = tool_results
    msg.metadata = md
    return kwargs


def register_tool_trace_pre_print(agent: AgentBase) -> None:
    agent.register_instance_hook(
        "pre_print",
        "attach_tool_trace_metadata",
        _pre_print_attach_tool_trace,
    )


@agent_app.query(framework="agentscope")
async def query_func(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    session_id = request.session_id
    user_id = request.user_id

    memory = await get_short_term_memory(user_id, session_id)
    long_term_memory = get_long_term_memory("知识助手", user_id)

    smartassistant = get_smartassistant_agent(memory, long_term_memory)
    await agent_app.state.session.load_session_state(
        session_id=session_id,
        user_id=user_id,
        agent=smartassistant,
    )
    register_tool_trace_pre_print(smartassistant)

    async for msg, last in stream_printing_messages(
        agents=[smartassistant],
        coroutine_task=smartassistant(msgs),
    ):
        yield msg, last

    await agent_app.state.session.save_session_state(
        session_id=session_id,
        user_id=user_id,
        agent=smartassistant,
    )

# 启动服务（监听8090端口）
agent_app.run(host="0.0.0.0", port=8090, web_ui=False)

# 如果希望同时启用内置的 Web 对话界面，可设置 web_ui=True
# agent_app.run(host="0.0.0.0", port=8090, web_ui=True)
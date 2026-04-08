from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 优先从与 server.py 同级的 .env 加载（再回退到当前工作目录下的 .env）
load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()

from fastapi import FastAPI
from agentscope.pipeline import stream_printing_messages
from agentscope.session import RedisSession
from agentscope_runtime.engine import AgentApp
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope.agent import AgentBase
from agents.route_agent import get_router_agent

from agents.intentdetect import IntentDetectAgent
from agents.smartassistant import get_smartassistant_agent
from agents.docqa import get_docqa_agent
from agents.writing import get_writing_agent
from agents.chat import get_chat_agent
from memory.short_term_memory import get_short_term_memory
from memory.long_term_memory import get_long_term_memory
from adapters.agui_adapter import CustomAGUIAdapter
from agents.writing import WritingScenariosAgent
from agents.docqa import DocqaScenariosAgent
from agents.translate import TranslateScenariosAgent


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
    protocol_adapters=[
        CustomAGUIAdapter(),
    ],
)

print("✅ Agent App创建成功")

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

    
    agent = IntentDetectAgent()

    agent.register_agent(DocqaScenariosAgent(memory, long_term_memory))
    agent.register_agent(WritingScenariosAgent(memory, long_term_memory))
    agent.register_agent(TranslateScenariosAgent(memory, long_term_memory))
    agent.build_intent_detect_agent(memory, long_term_memory)

    # agent.route_and_reply(query=msgs, memory=memory, long_term_memory=long_term_memory)
    # smartassistant = get_smartassistant_agent(memory, long_term_memory)
    await agent_app.state.session.load_session_state(
        session_id=session_id,
        user_id=user_id,
        agent=agent.get_intent_detect_agent(),
    )

    async for msg, last in stream_printing_messages(
        agents=agent.get_all_agents(),
        coroutine_task=agent.route_and_reply(query=msgs),
    ):
        yield msg, last

    await agent_app.state.session.save_session_state(
        session_id=session_id,
        user_id=user_id,
        agent=agent.get_intent_detect_agent(),
    )

# 启动服务（监听8090端口）
agent_app.run(host="0.0.0.0", port=8090, web_ui=False)

# 如果希望同时启用内置的 Web 对话界面，可设置 web_ui=True
# agent_app.run(host="0.0.0.0", port=8090, web_ui=True)
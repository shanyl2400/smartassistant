import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.tool import Toolkit, execute_python_code
from agentscope.pipeline import stream_printing_messages
from agentscope.memory import InMemoryMemory
from agentscope.session import RedisSession

from agentscope_runtime.engine import AgentApp
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope_runtime.engine.deployers import LocalDeployManager

from tools.time import get_current_time
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from memory.long_term_memory import get_long_term_memory
from memory.short_term_memory import create_sqlite_short_term_memory
from sqlalchemy.ext.asyncio import create_async_engine
from agentscope.memory import (
    AsyncSQLAlchemyMemory,
)

# 缓存存储已创建的智能体实例
_agent_cache = {}

def get_smart_assistant_agent(user_id: str, session_id: str) -> ReActAgent:
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    # 生成缓存键
    cache_key = (user_id, session_id)
    
    # 检查缓存中是否已有实例
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]

    # 准备工具
    toolkit = Toolkit()
    toolkit.register_tool_function(execute_python_code)
    toolkit.register_tool_function(get_current_time)
    toolkit.register_tool_function(retrivers_block_content)
    toolkit.register_tool_function(zhipu_websearch)

    

    engine = create_async_engine("sqlite+aiosqlite:///./short_term_memory.db")

    # 然后使用该引擎创建记忆
    memory = AsyncSQLAlchemyMemory(
        engine_or_session=engine,
        # 可选传入指定user_id和session_id
        user_id=user_id,
        session_id=session_id,
    )

    smart_assistant = ReActAgent(
        name="知识助手",
        sys_prompt="你是一个知识助手，具有长期记忆功能, 你可以根据用户的问题，调用工具来回答问题。请优先查询召回文档，如果文档中没有相关答案，再调用网络搜索工具。",
        model=DashScopeChatModel(
            model_name="qwen-max",
            # api_key=os.environ["DASHSCOPE_API_KEY"],
            api_key=os.environ["DASHSCOPE_API_KEY"],
            stream=True,
            enable_thinking=False,
        ),
        # long_term_memory=get_long_term_memory("知识助手", user_id), # 获取长期记忆
        # long_term_memory_mode="both",  # 使用 static_control 模式
        formatter=DashScopeMultiAgentFormatter(),
        toolkit=toolkit,
        memory=memory,    # 创建短期记忆
    )
    
    # 将实例存入缓存
    _agent_cache[cache_key] = smart_assistant
    
    return smart_assistant
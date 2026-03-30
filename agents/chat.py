import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.tool import Toolkit, execute_python_code
from tools.time import get_current_time
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from agentscope.memory import MemoryBase
from agentscope.memory import LongTermMemoryBase
from .baseagent import create_base_agent

# 缓存存储已创建的智能体实例
_agent_cache = None
def get_chat_agent(
    memory: MemoryBase,
    long_term_memory: LongTermMemoryBase,
) -> ReActAgent:
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    global _agent_cache

    if _agent_cache is not None:
        return _agent_cache

    # 准备工具
    toolkit = Toolkit()
    toolkit.register_tool_function(execute_python_code)
    toolkit.register_tool_function(get_current_time)
    toolkit.register_tool_function(retrivers_block_content)
    toolkit.register_tool_function(zhipu_websearch)

    name="日常闲聊"
    sys_prompt='''你是一个日常闲聊的智能体，你可以回答用户的问题，也可以与用户进行简单的对话。'''
    chat_agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
    )

    _agent_cache = chat_agent
    
    return chat_agent

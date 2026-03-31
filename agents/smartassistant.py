import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.message import Msg
from agentscope.tool import Toolkit, execute_python_code, ToolResponse
from tools.time import get_current_time
from agentscope.memory import MemoryBase
from agentscope.token import CharTokenCounter
from .baseagent import create_base_agent
from agentscope.memory import LongTermMemoryBase
from .docqa import docqa
from .writing import writing
from .translate import translate
from tools.websearch import zhipu_websearch

# 缓存存储已创建的智能体实例
_agent_cache = None
def get_smartassistant_agent(
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
    ) -> ReActAgent:        
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    global _agent_cache

    # 只有在外部明确传入了记忆对象时才复用缓存，避免工具调用先行时“污染”缓存。
    if _agent_cache is not None:
        return _agent_cache

    # 准备工具
    toolkit = Toolkit()
    toolkit.register_tool_function(get_current_time)
    toolkit.register_tool_function(docqa)
    toolkit.register_tool_function(writing)
    toolkit.register_tool_function(translate)
    toolkit.register_tool_function(zhipu_websearch)
    
    name="知识助手"
    sys_prompt='''你是一个知识助手, 你有很多技能，当用户提问时，请尽量用技能来回答, 如果技能无法回答，再自己回答'''
    agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
    )
    _agent_cache = agent
    return agent

import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.message import Msg
from agentscope.plan import PlanNotebook
from tools.time import get_current_time
from agentscope.memory import MemoryBase
from agentscope.token import CharTokenCounter
from .baseagent import create_base_agent
from agentscope.memory import LongTermMemoryBase
from .docqa import docqa
from .writing import writing
from .translate import translate
from tools.websearch import zhipu_websearch
from agentscope.tool import (
    Toolkit,
    execute_shell_command,
    execute_python_code,
    view_text_file,
)
# 缓存存储已创建的智能体实例
# _agent_cache = None
def get_smartassistant_agent(
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
    ) -> ReActAgent:        
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    # global _agent_cache

    # 只有在外部明确传入了记忆对象时才复用缓存，避免工具调用先行时“污染”缓存。
    # if _agent_cache is not None:
    #     return _agent_cache
    
    # 准备工具
    toolkit = Toolkit()
    toolkit.register_tool_function(get_current_time)
    toolkit.register_tool_function(docqa)
    toolkit.register_tool_function(writing)
    toolkit.register_tool_function(translate)
    toolkit.register_tool_function(zhipu_websearch)
    toolkit.register_tool_function(execute_python_code)
    toolkit.register_tool_function(view_text_file)

    # toolkit.register_agent_skill("skills/A2UI_response_generator")

    
    name="知识助手"
    sys_prompt='''你是一个专业、严谨且具备极强执行力的全能知识助手。
    你精通信息检索、深度写作与精准翻译。
    若已得到回答，请不要重复调用工具。

    ## Rules & Constraints
    - 如果你发现自己陷入了重复调用同一个工具的循环，请立即中断，并检查是否已经可以交付结果。
    - **不要为了调用而调用**。工具是手段，交付（Final Answer）才是目的。
    **'''
    agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
        # plan_notebook=PlanNotebook(),
    )
    # _agent_cache = agent
    return agent

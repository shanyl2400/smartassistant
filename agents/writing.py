import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.message import Msg
from tools.time import get_current_time
from agentscope.memory import MemoryBase
from agentscope.plan import PlanNotebook
from agentscope.token import CharTokenCounter
from .baseagent import create_base_agent
from agentscope.memory import LongTermMemoryBase
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from agentscope.tool import (
    Toolkit,
    execute_shell_command,
    execute_python_code,
    view_text_file,
    ToolResponse,
)
# 缓存存储已创建的智能体实例
_agent_cache = None
def get_writing_agent(
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
    toolkit.register_tool_function(retrivers_block_content)
    toolkit.register_tool_function(zhipu_websearch)

    toolkit.register_tool_function(view_text_file)
    # toolkit.register_tool_function(execute_shell_command)
    toolkit.register_agent_skill("skills/continuation")
    toolkit.register_agent_skill("skills/expansion_summarization")
    toolkit.register_agent_skill("skills/generate_outline")
    toolkit.register_agent_skill("skills/section_based_writing")

    name="帮我写作"
    sys_prompt='''你是一名专业、资深、高审美、懂传播的金牌文案策划师，擅长撰写各类场景下的优质文案，
    你有一些「写作技能（Agent Skills）」可以辅助你完成文档创作
    # 工具调用格式
    每个 Action 必须有明确的目的。
    - **Thought**: 我已经完成了写作任务，当前内容已完整。
    - **Final Answer**: [此处输出最终内容，不再包含任何 Action 指令]
'''
    writing_agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
        # plan_notebook=PlanNotebook(),
    )
    _agent_cache = writing_agent
    return writing_agent


async def writing(
    query: str,
) -> ToolResponse:
    """写作工具：根据用户需求生成文案。

    该工具会调用内部的“帮我写作”子智能体，并直接输出生成结果（不额外解释）。

    Args:
        query (str): 用户提出的写作需求/主题/风格/场景等要求。

    Returns:
        ToolResponse: 返回结果中 `content` 为文本内容块（`text`）。
    """
    agent = get_writing_agent()
    res = await agent(Msg("user", query, "user"))
    return ToolResponse(content=res.get_content_blocks("text"))
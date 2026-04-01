import os

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.tool import ToolResponse, Toolkit, execute_python_code
from tools.time import get_current_time
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from agentscope.memory import MemoryBase
from agentscope.memory import LongTermMemoryBase
from .baseagent import create_base_agent
# 缓存存储已创建的智能体实例
_agent_cache = None
def get_docqa_agent(
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
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

    name="文档问答"
    sys_prompt='''你是一个专业的多文档问答Agent，
        擅长从多个召回的文档中提取关键信息、处理信息冲突、整合核心观点，最终生成基于原文的准确、连贯回答。
        你的回答必须严格锚定提供的文档内容，
        不加入任何文档外的知识或假设, 
        如果参考文档中包含图片地址，回答时需要保留相关引用段落内容中的图片地址。
        如果输出内容自行生成了类似于![](xxxxxx-xxxxx/xxxxx.xxx) 和![](/api/kc-mc/v2/xxxxxxx)格式的回答，说明你犯错了，请重新生成。
        请优先查询召回文档，如果文档中没有相关答案，再调用网络搜索工具。
        
    ## Rules & Constraints
    - 如果你发现自己陷入了重复调用同一个工具的循环，请立即中断，并检查是否已经可以交付结果。
    - **不要为了调用而调用**。工具是手段，交付（Final Answer）才是目的。
        '''
    docqa_agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
    )
    _agent_cache = docqa_agent
    return docqa_agent

async def docqa(
    query: str
) -> ToolResponse:
    """问答工具：基于召回文档 & 网络信息回答用户问题。

    该工具会使用内部的“文档问答”子智能体：
    1) 优先检索召回文档并从中提取关键信息；
    2) 如文档中缺少答案，再调用网络搜索补充信息；
    3) 回答内容必须严格锚定文档表述，不引入文档外的臆测；若文档包含图片/链接引用，需要在回答中保留对应引用内容。

    Args:
        query (str): 用户要咨询的问题/需求。

    Returns:
        ToolResponse: 返回结果中 `content` 为文本内容块（`text`）。
    """
    # 取出/创建子智能体实例

    agent = get_docqa_agent()
    # 让子智能体完成任务
    res = await agent(Msg("user", query, "user"))
    return ToolResponse(
        content=res.get_content_blocks("text"),
    )
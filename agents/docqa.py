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
def get_docqa_agent(
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

    name="文档问答"
    sys_prompt='''你是一个专业的多文档问答Agent，
        擅长从多个召回的文档中提取关键信息、处理信息冲突、整合核心观点，最终生成基于原文的准确、连贯回答。
        你的回答必须严格锚定提供的文档内容，
        不加入任何文档外的知识或假设, 
        如果参考文档中包含图片地址，回答时需要保留相关引用段落内容中的图片地址。
        如果输出内容自行生成了类似于![](xxxxxx-xxxxx/xxxxx.xxx) 和![](/api/kc-mc/v2/xxxxxxx)格式的回答，说明你犯错了，请重新生成。
        请优先查询召回文档，如果文档中没有相关答案，再调用网络搜索工具。'''
    docqa_agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
    )

    

    _agent_cache = docqa_agent
    
    return docqa_agent

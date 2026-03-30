import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.tool import Toolkit, execute_python_code
from tools.time import get_current_time
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from agentscope.memory import MemoryBase
from agentscope.token import CharTokenCounter

# 缓存存储已创建的智能体实例
_agent_cache = None
def get_chat_agent(memory: MemoryBase) -> ReActAgent:
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

    chat_agent = ReActAgent(
        name="日常闲聊",
        sys_prompt='''你是一个日常闲聊的智能体，你可以回答用户的问题，也可以与用户进行简单的对话。''',
        model=DashScopeChatModel(
            model_name="qwen-max",
            api_key=os.environ["DASHSCOPE_API_KEY"],
            stream=True,
            enable_thinking=False,
        ),
        formatter=DashScopeMultiAgentFormatter(),
        toolkit=toolkit,
        memory=memory,
        compression_config=ReActAgent.CompressionConfig(
            enable=True,
            agent_token_counter=CharTokenCounter(),  # 智能体的 token 计数器
            trigger_threshold=10000,  # 超过 10000 个 token 时触发压缩
            keep_recent=3,            # 保持最近 3 条消息不被压缩
        ),
    )
    chat_agent.set_console_output_enabled(True)

    _agent_cache = chat_agent
    
    return chat_agent

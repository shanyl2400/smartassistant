
import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.tool import Toolkit
from agentscope.memory import MemoryBase
from agentscope.token import CharTokenCounter
from agentscope.memory import LongTermMemoryBase
from agentscope.plan import PlanNotebook, Plan, SubTask

def create_base_agent(
    name: str, 
    sys_prompt: str, 
    toolkit:Toolkit | None = None, 
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
    ) -> ReActAgent:
    agent = ReActAgent(
        name=name,
        sys_prompt=sys_prompt,
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
        long_term_memory=long_term_memory,
        long_term_memory_mode="agent_control",  # 使用 agent_control 模式
        plan_notebook=PlanNotebook(),
    )
    agent.set_console_output_enabled(True)
    return agent
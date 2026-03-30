import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.tool import Toolkit, execute_python_code
from tools.time import get_current_time
from agentscope.memory import MemoryBase
from agentscope.token import CharTokenCounter
from .baseagent import create_base_agent
from agentscope.memory import LongTermMemoryBase

# 缓存存储已创建的智能体实例
_agent_cache = None
def get_writing_agent(
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
    
    name="帮我写作"
    sys_prompt='''你是一名专业、资深、高审美、懂传播的金牌文案策划师，擅长撰写各类场景下的优质文案，包括但不限于：朋友圈文案、短视频口播、海报标题、小红书笔记、产品宣传语、活动文案、品牌文案、节日祝福、电商详情文案等。
你的写作原则：
精准理解需求：严格按照用户指定的主题、场景、受众、风格、字数、结构进行创作，不偏离要求。
风格多样化：可驾驭温暖治愈、高级简约、幽默有趣、走心煽情、专业严谨、文艺清新、犀利吸睛、口语化口播等多种风格。
结构清晰有逻辑：标题抓人、开头吸睛、内容流畅、结尾有力量或引导性，符合对应平台传播逻辑。
语言自然高级：拒绝生硬套话、空洞口号，文字有质感、有温度、有记忆点，易读易传播。
多版本输出：用户需要多个备选时，提供差异化版本，标注清晰，方便选择。
直接交付成品：不啰嗦解释，不额外提问，一次性输出完整可用文案，必要时附带标题、话题标签、分段排版。
你始终保持专业、高效、贴心的服务态度，以写出让用户满意的优质文案为目标。'''
    writing_agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
    )

    _agent_cache = writing_agent
    
    return writing_agent
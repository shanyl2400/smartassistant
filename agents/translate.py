import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.message import Msg
from agentscope.tool import Toolkit, execute_python_code, ToolResponse
from tools.time import get_current_time
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from agentscope.memory import MemoryBase
from agentscope.memory import LongTermMemoryBase
from .baseagent import create_base_agent
# 缓存存储已创建的智能体实例
_agent_cache = None
def get_translate_agent(
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

    name="文档翻译"
    sys_prompt='''角色及适用场景
你是一名世界顶级的专业翻译官，你的核心使命是精准、流畅、自然地在任何语言之间传递信息和情感。你不仅翻译文字，更是在沟通文化和专业技术。你具备深厚的语言学知识、文化背景洞察力和深厚的行业领域技能。
翻译遵守铁的纪律：
  * 风格保持：绝对保留原文的风格、语气和节奏。技术文档需准确严谨，诗歌需注重韵律和意象，广告语需朗朗上口。
  * 文化适配：不是直译，而是意译。自动将习语、笑话、文化专有项转换为目标语言文化中易于理解的等价表达。例如，将 “It‘s raining cats and dogs” 译为 “大雨倾盆”，而非 “下猫和狗”。
  * 术语处理：内置专业术语库（如医学、法律、编程、人工智能、科学等领域），确保领域专业术语的准确性。对于无法确定的专有名词（如人名、品牌名），优先采用通用译名或选择音译，并可询问用户。
  * 结构保留：完美保留原文的排版、标点、换行符以及Markdown等格式。不翻译代码、URL、电子邮件、人名等内容。

如果用户指令和文档内容为空，则直接返回“抱歉，用户未提供文档或文档内容为空，请重新输入文档”。
如果用户指令和文档内容无意义/敏感/，则直接返回“抱歉，用户提供的内容无意义/敏感，请重新输入文档”。
若当前用户指令与历史对话上下文信息无关，则无需参考历史对话上下文 ，专注输出当前内容；若有关联，需结合历史对话上下文补充细节!

这个任务对我至关重要，让我们一步一步思考，请逐行、逐段翻译文档内容和严格检查，若发现问题及时纠正。
 1.深度输入分析 
    * 语言检测：自动精准识别输入内容的源语言。能处理混合语言文本，识别主体语言（如中文、英文、日文、法文等）。
    * 内容解析：分析文本的领域（如技术文档、文学诗歌、营销文案、日常对话）、语气（正式、随意、热情、严肃）和潜在文化元素（俚语、成语、典故）。
2. 目标语言判断：
    * 用户指令优先：严格遵守用户指定的任何目标语言（如“译成日语”、“翻译为西班牙语”）。
    * 若未指定目标语言，则遵循以下默认规则：
        * 若原文为中文，则翻译为英文；
        * 若原文为英文，则翻译为简体中文；
        * 若原文为其他语言，则默认翻译为简体中文。

  禁止输出翻译内容以外的任何信息，直接输出翻译后的内容！ '''
    translate_agent = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit, 
        memory=memory,
        long_term_memory=long_term_memory,
    )

    

    _agent_cache = translate_agent
    
    return translate_agent


async def translate(
    query: str,
) -> ToolResponse:
    """翻译工具：将用户给定文本/指令翻译成目标语言。

    该工具会调用内部的“文档翻译”子智能体，并直接输出翻译结果（不额外解释）。

    Args:
        query (str): 用户提出的翻译请求/待翻译内容。

    Returns:
        ToolResponse: 返回结果中 `content` 为文本内容块（`text`）。
    """
    agent = get_translate_agent()
    res = await agent(Msg("user", query, "user"))
    return ToolResponse(content=res.get_content_blocks("text"))

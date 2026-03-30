import os
from typing import Literal

from pydantic import BaseModel, Field

from agentscope.agent import ReActAgent
from agentscope.memory import MemoryBase
from .baseagent import create_base_agent
from agentscope.tool import Toolkit
from agentscope.memory import LongTermMemoryBase

# 缓存存储已创建的智能体实例
_agent_cache = None

def get_router_agent(
    memory: MemoryBase,
    long_term_memory: LongTermMemoryBase,
) -> ReActAgent:
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    global _agent_cache
    # 检查缓存中是否已有实例
    if _agent_cache is not None:
        return _agent_cache

    toolkit = Toolkit()
    name="Router"
    sys_prompt='''
        请根据用户输入判断用户意图
【意图定义】
意图1 【Writing】
    * 名称：帮我写作
    * 定义：用户请求生成全新的文本类创作内容，意图中必须包含短文、方案、报告，宣传资料，文章的核心创作方向，不包含生成知识类题目/问题。
    * 特征：陈述句，不包含疑问词，包含核心动作词（必须含）
         - 创作类：写、拟、起草、撰写、编制、整理、输出、生成
         - 优化类：修改、调整、完善、润色、补充，校对
    * 示例：“请帮我写一篇关于远程工作优势的博客文章，字数约500字。”
意图2 【DocumentQA】
    * 名称：文档问答
    * 定义：用户需要从文档中提取**具体信息** ，核心动作是“查询/提取已有文档中的信息”
    * 特征：  
      - 包含疑问词（什么/如何/为什么/何时/谁/多少/是否）  
      - 请求解释概念/步骤/数据（例："SSL证书安装步骤"）  
      - 要求直接答案而非整个文档
      - 询问AnyShare已知的产品信息
     * 示例：
      - 如何配置防火墙规则？
      - 员工手册里年假政策是什么？
意图3 【Translate】
    * 定义：用户要求将文本从一种语言准确流畅地转换为另一种语言，保持原文的意思、风格和语气，并符合目标语言的表达习惯。
    * 示例：“请将这段中文产品说明翻译成英文，确保技术术语准确且语言自然。”
意图4 【Others】
    * 名称：其他任务
    * 定义：用户请求其他任务，不包含写作、文档问答。
    * 特征：包含其他任务的描述，不包含写作、文档问答。
    * 示例：“你是谁？”
【输出规则】
1. 只输出意图名称
2. 不添加任何解释  
 输入内容：                               
只回答意图中选择一个，不要生成任何解释！
回答范例：DocumentQA
'''
    router = create_base_agent(
        name=name, 
        sys_prompt=sys_prompt, 
        toolkit=toolkit,
        memory=memory,
        long_term_memory=long_term_memory,
    )
    # 将实例存入缓存
    _agent_cache = router
    
    return router

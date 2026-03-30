import os
from typing import Literal

from pydantic import BaseModel, Field

from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter
from agentscope.memory import MemoryBase
from agentscope.model import DashScopeChatModel
from agentscope.token import CharTokenCounter

# 使用结构化输出指定路由任务
class RoutingChoice(BaseModel):
    your_choice: Literal[
        "Writing",   # 写作任务
        "Programming",  # 编程任务
        "DocumentQA",  # 问答召回&回答
        None,
    ] = Field(
        description="选择正确的后续任务，如果任务太简单或没有合适的任务，则选择 ``None``",
    )

# 缓存存储已创建的智能体实例
_agent_cache = None

def get_router_agent(
    memory: MemoryBase,
) -> ReActAgent:
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    global _agent_cache
    # 检查缓存中是否已有实例
    if _agent_cache is not None:
        return _agent_cache

    router = ReActAgent(
        name="Router",
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
意图3 【Others】
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
''',
        model=DashScopeChatModel(
            model_name="qwen-turbo",
            api_key=os.environ["DASHSCOPE_API_KEY"],
            stream=False,
        ),
        formatter=DashScopeChatFormatter(),
        toolkit=[],
        memory=memory,
        compression_config=ReActAgent.CompressionConfig(
            enable=True,
            agent_token_counter=CharTokenCounter(),  # 智能体的 token 计数器
            trigger_threshold=10000,  # 超过 10000 个 token 时触发压缩
            keep_recent=3,            # 保持最近 3 条消息不被压缩
        ),
    )

    router.set_console_output_enabled(True)
    # 将实例存入缓存
    _agent_cache = router
    
    return router

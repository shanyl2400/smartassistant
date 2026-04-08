import asyncio
from collections import OrderedDict
from typing import AsyncGenerator

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock, ToolUseBlock
from agentscope.pipeline import stream_printing_messages
from agentscope.tool import ToolResponse, Toolkit, execute_python_code
from tools.time import get_current_time
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from agentscope.memory import MemoryBase
from agentscope.memory import LongTermMemoryBase
from .baseagent import create_base_agent
from .intentdetect import ScenariosAgent

_DOCQA_SYS_PROMPT = """你是一个专业的多文档问答Agent（智能问答技能）。
        凡用户以提问、咨询、求证、追问等方式提出、且需要结合召回文档或对话中提供的材料来回答的需求，均由你处理；不要推给其他场景。
        擅长从多个召回的文档中提取关键信息、处理信息冲突、整合核心观点，最终生成基于原文的准确、连贯回答。
        你的回答必须严格锚定提供的文档内容，
        不加入任何文档外的知识或假设,
        如果参考文档中包含图片地址，回答时需要保留相关引用段落内容中的图片地址。
        如果输出内容自行生成了类似于![](xxxxxx-xxxxx/xxxxx.xxx) 和![](/api/kc-mc/v2/xxxxxxx)格式的回答，说明你犯错了，请重新生成。
        请优先查询召回文档，如果文档中没有相关答案，再调用网络搜索工具。

    ## Rules & Constraints
    - 如果你发现自己陷入了重复调用同一个工具的循环，请立即中断，并检查是否已经可以交付结果。
    - **不要为了调用而调用**。工具是手段，交付（Final Answer）才是目的。
        """


class DocqaScenariosAgent(ScenariosAgent):
    """文档问答场景：基于召回文档与可选网络检索回答问题。"""

    def __init__(self,
        memory: MemoryBase | None = None, 
        long_term_memory: LongTermMemoryBase | None = None) -> None:
        
        toolkit = Toolkit()
        toolkit.register_tool_function(execute_python_code)
        toolkit.register_tool_function(get_current_time)
        toolkit.register_tool_function(retrivers_block_content)
        toolkit.register_tool_function(zhipu_websearch)

        self._agent = create_base_agent(
            name=self.name,
            sys_prompt=_DOCQA_SYS_PROMPT,
            toolkit=toolkit,
            memory=memory,
            long_term_memory=long_term_memory,
        )

    @property
    def name(self) -> str:
        return "智能问答"

    @property
    def description(self) -> str:
        return (
            "凡涉及「用户在提问」（咨询、求证、问答、追问、让解释某事等），均选用本智能体："
            "结合召回文档或用户/对话中提供的材料作答，严格锚定原文、整合多段信息或处理冲突；"
            "文档无答案时可辅以网络搜索；需保留文档中的图片与引用格式。"
        )

    def get_agent(
        self,
    ) -> ReActAgent:
        return self._agent


docqa_scenario = DocqaScenariosAgent()

def get_docqa_agent(
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
) -> ReActAgent:
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    return docqa_scenario.get_agent()

def _sub_agent_prints_to_text_blocks(msgs: list[Msg]) -> list[TextBlock]:
    """将子智能体 print 出的消息转成可写入 tool_result 的文本块（含工具调用提示）。"""
    blocks: list[TextBlock] = []
    for m in msgs:
        for block in m.get_content_blocks():
            blocks.append(block)
    return blocks


async def docqa(
    query: str
) -> AsyncGenerator[ToolResponse, None]:
    """问答工具：基于召回文档 & 网络信息回答用户问题。

    该工具会使用内部的“文档问答”子智能体：
    1) 优先检索召回文档并从中提取关键信息；
    2) 如文档中缺少答案，再调用网络搜索补充信息；
    3) 回答内容必须严格锚定文档表述，不引入文档外的臆测；若文档包含图片/链接引用，需要在回答中保留对应引用内容。

    流式说明：子智能体推理过程中的 print 会多次 yield ToolResponse，由外层 ReActAgent 推送到会话流；
    最后一帧仅含子智能体最终答复文本，供父模型记忆与续聊。

    Args:
        query (str): 用户要咨询的问题/需求。

    Yields:
        ToolResponse: 中间块 is_last=False；最后一帧 is_last=True，content 为最终文本块。
    """
    agent = get_docqa_agent()

    msgs_by_id: OrderedDict[str, Msg] = OrderedDict()
    final_holder: list[Msg] = []

    async def run_sub() -> None:
        msg_res = await agent(Msg("user", query, "user"))
        final_holder.append(msg_res)

    async for msg, _ in stream_printing_messages(
        agents=[agent],
        coroutine_task=run_sub(),
    ):
        msgs_by_id[msg.id] = msg
        if msg.metadata and msg.metadata.get("_is_interrupted", False):
            yield ToolResponse(
                content=_sub_agent_prints_to_text_blocks(list(msgs_by_id.values())),
                stream=True,
                is_last=True,
                is_interrupted=True,
            )
            raise asyncio.CancelledError()

        yield ToolResponse(
            content=_sub_agent_prints_to_text_blocks(list(msgs_by_id.values())),
            stream=True,
            is_last=False,
        )

    if not final_holder:
        yield ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="<system-info>文档问答子智能体未返回结果。</system-info>",
                ),
            ],
            stream=True,
            is_last=True,
        )
        return

    final_msg = final_holder[0]
    final_text = list(final_msg.get_content_blocks("text"))
    if not final_text:
        final_text = _sub_agent_prints_to_text_blocks(list(msgs_by_id.values()))
    yield ToolResponse(
        content=final_text,
        stream=True,
        is_last=True,
    )
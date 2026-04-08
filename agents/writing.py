import os
import asyncio
from agentscope.agent import ReActAgent
from collections import OrderedDict
from typing import AsyncGenerator
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeMultiAgentFormatter
from agentscope.message import Msg, TextBlock
from tools.time import get_current_time
from agentscope.memory import MemoryBase
from agentscope.plan import PlanNotebook
from agentscope.token import CharTokenCounter
from .baseagent import create_base_agent
from agentscope.memory import LongTermMemoryBase
from tools.retrievers_block_content import retrivers_block_content
from tools.websearch import zhipu_websearch
from agentscope.pipeline import stream_printing_messages
from agentscope.tool import (
    Toolkit,
    execute_shell_command,
    execute_python_code,
    view_text_file,
    ToolResponse,
)

from .intentdetect import ScenariosAgent


_WRITING_SYS_PROMPT = """你是一名专业、资深、高审美、懂传播的金牌文案策划师，擅长撰写各类场景下的优质文案，
    你有一些「写作技能（Agent Skills）」可以辅助你完成文档创作
    # 工具调用格式
    每个 Action 必须有明确的目的。
    - **Thought**: 我已经完成了写作任务，当前内容已完整。
    - **Final Answer**: [此处输出最终内容，不再包含任何 Action 指令]
"""


class WritingScenariosAgent(ScenariosAgent):
    """写作场景：文案创作、润色、扩写及基于技能的大纲与分段写作。"""

    def __init__(self,
        memory: MemoryBase | None = None, 
        long_term_memory: LongTermMemoryBase | None = None) -> None:
        
        super().__init__()
        toolkit = Toolkit()
        toolkit.register_tool_function(get_current_time)
        toolkit.register_tool_function(retrivers_block_content)
        toolkit.register_tool_function(zhipu_websearch)
        toolkit.register_tool_function(view_text_file)
        toolkit.register_agent_skill("skills/continuation")
        toolkit.register_agent_skill("skills/expansion_summarization")
        toolkit.register_agent_skill("skills/generate_outline")
        toolkit.register_agent_skill("skills/section_based_writing")

        self._agent = create_base_agent(
            name=self.name,
            sys_prompt=_WRITING_SYS_PROMPT,
            toolkit=toolkit,
            memory=memory,
            long_term_memory=long_term_memory,
        )

    @property
    def name(self) -> str:
        return "帮我写作"

    @property
    def description(self) -> str:
        return (
            "用户需要撰写、改写、润色各类文案；按主题或风格创作内容；"
            "生成大纲、续写、扩写/缩写、分段写作等文档创作类需求。"
        )

    def get_agent(
        self,
    ) -> ReActAgent:
        return self._agent


writing_scenario = WritingScenariosAgent()


def get_writing_agent(
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
) -> ReActAgent:
    """创建一个 ReAct 智能体并运行一个简单任务。"""
    return writing_scenario.get_agent()

def _sub_agent_prints_to_text_blocks(msgs: list[Msg]) -> list[TextBlock]:
    """将子智能体 print 出的消息转成可写入 tool_result 的文本块（含工具调用提示）。"""
    blocks: list[TextBlock] = []
    for m in msgs:
        for block in m.get_content_blocks():
            if block["type"] == "text":
                blocks.append(block)
            elif block["type"] == "tool_use":
                blocks.append(
                    TextBlock(
                        type="text",
                        text=f"Calling tool {block['name']} ...",
                    ),
                )
    return blocks

async def writing(
    query: str,
) -> AsyncGenerator[ToolResponse, None]:
    """写作工具：根据用户需求生成文案。

    该工具会调用内部的“帮我写作”子智能体，并直接输出生成结果（不额外解释）。

    Args:
        query (str): 用户提出的写作需求/主题/风格/场景等要求。

    Returns:
        ToolResponse: 返回结果中 `content` 为文本内容块（`text`）。
    """
    agent = get_writing_agent()
    # res = await agent(Msg("user", query, "user"))
    # return ToolResponse(content=res.get_content_blocks("text"))
    # agent = get_docqa_agent()

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
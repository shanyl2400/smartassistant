
import os

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel, OpenAIChatModel
from agentscope.formatter import (
    DashScopeMultiAgentFormatter,
    DashScopeChatFormatter,
    DeepSeekChatFormatter,
)
from agentscope.tool import Toolkit
from agentscope.memory import MemoryBase
from agentscope.token import CharTokenCounter
from agentscope.memory import LongTermMemoryBase
from agentscope.plan import PlanNotebook, Plan, SubTask

from pydantic import BaseModel, Field

class CustomSummary(BaseModel):
    main_topic: str = Field(
        description="对话的主题"
    )
    key_points: str = Field(
        description="讨论的重要观点"
    )
    pending_tasks: str = Field(
        description="待完成的任务"
    )

def create_base_agent(
    name: str, 
    sys_prompt: str, 
    toolkit:Toolkit | None = None, 
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
    plan_notebook: PlanNotebook | None = None,
    ) -> ReActAgent:
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # 优先直连 DeepSeek（OpenAI 兼容接口）；未配置则回退到 DashScope。
    model = (
        OpenAIChatModel(
            model_name=deepseek_model,
            api_key=deepseek_api_key,
            stream=True,
            client_kwargs={"base_url": deepseek_base_url},
        )
        if deepseek_api_key
        else DashScopeChatModel(
            model_name=os.getenv("DASHSCOPE_MODEL", "deepseek-r1"),
            api_key=os.environ["DASHSCOPE_API_KEY"],
            stream=True,
            enable_thinking=False,
        )
    )

    formatter = DeepSeekChatFormatter() if deepseek_api_key else DashScopeChatFormatter()

    agent = ReActAgent(
        name=name,
        sys_prompt=sys_prompt,
        model=model,
        formatter=formatter,
        toolkit=toolkit,
        memory=memory,
        compression_config=ReActAgent.CompressionConfig(
            enable=True,
            agent_token_counter=CharTokenCounter(),
            trigger_threshold=10000,
            keep_recent=3,
            summary_schema=CustomSummary,
            compression_prompt=(
                "<system-hint>请总结上述对话，"
                "重点关注主题、关键讨论点和待完成任务。"
                "每个字段尽量简洁，不要啰嗦。</system-hint>"
            ),
            summary_template=(
                "<system-info>对话摘要：\n"
                "主题：{main_topic}\n\n"
                "关键观点：\n{key_points}\n\n"
                "待完成任务：\n{pending_tasks}"
                "</system-info>"
            ),
        ),
        long_term_memory=long_term_memory,
        long_term_memory_mode="agent_control",  # 使用 agent_control 模式
        plan_notebook=plan_notebook,
    )
    agent.set_console_output_enabled(True)
    return agent
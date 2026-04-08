from __future__ import annotations

from abc import ABC, abstractmethod

from agentscope.agent import ReActAgent
from agentscope.memory import LongTermMemoryBase, MemoryBase
from agentscope.message import Msg

from .baseagent import create_base_agent

_INTENT_AGENT_NAME = "意图识别"


def _build_intent_sys_prompt(scenarios: list[ScenariosAgent]) -> str:
    lines = [
        "你是意图识别助手。根据用户当前输入，判断最匹配的下述场景之一。",
        "",
        "可选场景：",
        "",
    ]
    for i, s in enumerate(scenarios, start=1):
        lines.append(f"{i}. 【{s.name}】")
        lines.append(f"   {s.description}")
        lines.append("")
    lines.extend(
        [
            "规则：",
            "- 只输出一个场景名称，且必须与上方【】内的名称完全一致，不要加引号或其它说明。",
            "- 若用户输入与所有场景均明显不符，输出：无法识别",
        ]
    )
    return "\n".join(lines)


def _message_text(msg: Msg) -> str:
    parts: list[str] = []
    for block in msg.get_content_blocks("text"):
        if isinstance(block, dict):
            parts.append(str(block.get("text", "")))
        else:
            parts.append(str(getattr(block, "text", "")))
    return "".join(parts).strip()


def _coerce_user_query(query: str | Msg | list[Msg] | tuple[Msg, ...]) -> str:
    """将 runtime 传入的 str / 单条 Msg / 消息列表转为本轮用户文本（列表时优先最后一条 user 消息）。"""
    if isinstance(query, str):
        return query.strip()
    if isinstance(query, Msg):
        return _message_text(query)
    if isinstance(query, (list, tuple)):
        if not query:
            return ""
        for m in reversed(query):
            if isinstance(m, Msg) and getattr(m, "role", None) == "user":
                return _message_text(m)
        last = query[-1]
        return _message_text(last) if isinstance(last, Msg) else str(last).strip()
    return str(query).strip()


def _normalize_intent_label(label: str) -> str:
    s = label.strip()
    for q in ('"', "'", "「", "」", "【", "】"):
        s = s.replace(q, "")
    return s.strip()


def _resolve_scenario(
    label: str,
    scenarios: list[ScenariosAgent],
) -> ScenariosAgent | None:
    raw = _normalize_intent_label(label)
    if not raw or "无法识别" in raw:
        return None
    for s in scenarios:
        if s.name == raw:
            return s
    for s in sorted(scenarios, key=lambda x: len(x.name), reverse=True):
        if s.name in raw:
            return s
    return None


class ScenariosAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """场景唯一标识名称，用于意图输出与路由。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """场景能力说明，供意图模型区分边界。"""

    @abstractmethod
    def get_agent(
        self,
    ) -> ReActAgent:
        """返回该场景对应的 ReAct 子智能体。"""


class IntentDetectAgent:
    def __init__(self) -> None:
        self._scenarios: list[ScenariosAgent] = []
        self._agent: ReActAgent | None = None

    def register_agent(self, agent: ScenariosAgent) -> None:
        n = agent.name
        if any(s.name == n for s in self._scenarios):
            raise ValueError(f"场景名称已注册: {n!r}")
        self._scenarios.append(agent)

    def get_all_agents(self) -> list[ReActAgent]:
        """参与一次路由对话中可能产生输出的所有 ReActAgent（意图 + 各场景）。"""
        return [self.get_intent_detect_agent(), *[s.get_agent() for s in self._scenarios]]

    def build_intent_detect_agent(
        self,
        memory: MemoryBase | None = None,
        long_term_memory: LongTermMemoryBase | None = None,
    ) -> ReActAgent:
        if not self._scenarios:
            raise ValueError("尚未注册任何场景，请先调用 register_agent")
        sys_prompt = _build_intent_sys_prompt(self._scenarios)
        self._agent = create_base_agent(
            name=_INTENT_AGENT_NAME,
            sys_prompt=sys_prompt,
            toolkit=None,
            memory=memory,
            long_term_memory=long_term_memory,
        )

    def get_intent_detect_agent(self) -> ReActAgent:
        if self._agent is None:
            raise ValueError("请先调用 build_intent_detect_agent")
        return self._agent

    async def route_and_reply(
        self,
        query: str | Msg | list[Msg] | tuple[Msg, ...],
        memory: MemoryBase | None = None,
        long_term_memory: LongTermMemoryBase | None = None,
    ) -> Msg:
        """先用意图识别 agent 判断场景，再用对应子 agent 处理同一轮用户文本，返回子 agent 的最终 Msg。

        ``query`` 可为字符串、单条 ``Msg``，或与 runtime 一致的 ``msgs`` 列表（取最后一条 user 的文本）。
        """
        user_text = _coerce_user_query(query)
        if not user_text:
            raise ValueError("query 不能为空")
        intent_msg = await self._agent(Msg("user", user_text, "user"))
        print(intent_msg)
        label = _message_text(intent_msg)
        scenario = _resolve_scenario(label, self._scenarios)
        if scenario is None:
            scenario = self._scenarios[0]
            # raise ValueError(f"意图无法识别或无法路由，模型输出: {label!r}")
        sub_agent = scenario.get_agent()
        return await sub_agent(Msg("user", user_text, "user"))


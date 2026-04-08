import json
import traceback
from typing import Any, List

from ag_ui.core.events import (
    EventType as AGUIEventType,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    RunErrorEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from fastapi import Request
from fastapi.responses import StreamingResponse

from agentscope_runtime.engine.deployers.adapter.agui import (
    AGUIAdapterUtils,
    FlexibleRunAgentInput,
)
from agentscope_runtime.engine.deployers.adapter.agui.agui_adapter_utils import (
    AGUIEvent,
)
from agentscope_runtime.engine.deployers.adapter.protocol_adapter import (
    ProtocolAdapter,
)
from agentscope_runtime.engine.schemas.agent_schemas import (
    Message,
    MessageType,
    RunStatus,
)


class CustomAGUIAdapter(ProtocolAdapter):
    """AG-UI 适配：把 runtime 的 reasoning 文本流映射为 REASONING_MESSAGE_* 事件。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # 按请求隔离：每个 ag-ui 请求会 new 一个 AGUIAdapterUtils，用 id 作键
        self._reasoning_message_ids_by_adapter: dict[int, set[str]] = {}

    def _reasoning_ids(self, adapter_utils: AGUIAdapterUtils) -> set[str]:
        k = id(adapter_utils)
        if k not in self._reasoning_message_ids_by_adapter:
            self._reasoning_message_ids_by_adapter[k] = set()
        return self._reasoning_message_ids_by_adapter[k]

    @staticmethod
    def _as_sse_data(event) -> str:
        data = event.model_dump(
            mode="json",
            exclude_none=True,
            by_alias=True,
        )
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _rewrite_reasoning_agui_events(
        self,
        adapter_utils: AGUIAdapterUtils,
        events: List[AGUIEvent],
    ) -> List[AGUIEvent]:
        """官方把 reasoning 的 TextContent 也映射成 TextMessage*，这里改成 ReasoningMessage*。"""
        active = self._reasoning_ids(adapter_utils)
        if not active:
            return events
        out: List[AGUIEvent] = []
        for ev in events:
            mid = getattr(ev, "message_id", None)
            if mid is None or mid not in active:
                out.append(ev)
                continue
            if isinstance(ev, TextMessageStartEvent):
                out.append(
                    ReasoningMessageStartEvent(message_id=mid, role="reasoning"),
                )
            elif isinstance(ev, TextMessageContentEvent):
                out.append(
                    ReasoningMessageContentEvent(message_id=mid, delta=ev.delta),
                )
            elif isinstance(ev, TextMessageEndEvent):
                out.append(ReasoningMessageEndEvent(message_id=mid))
            else:
                out.append(ev)
        return out

    def convert_agent_event_to_agui_events(
        self,
        adapter_utils: AGUIAdapterUtils,
        agent_event: Any,
    ) -> List[AGUIEvent]:
        """
        先走官方映射；对 reasoning 通道把 TextMessage* 替换为 REASONING_MESSAGE_*。
        """
        reasoning_ids = self._reasoning_ids(adapter_utils)
        completed_reasoning_id: str | None = None
        if isinstance(agent_event, Message):
            if agent_event.type == MessageType.REASONING:
                if agent_event.status == RunStatus.InProgress:
                    reasoning_ids.add(agent_event.id)
                elif agent_event.status == RunStatus.Completed:
                    completed_reasoning_id = agent_event.id

        official = list(
            adapter_utils.convert_agent_event_to_agui_events(agent_event),
        )
        official = self._rewrite_reasoning_agui_events(adapter_utils, official)

        if completed_reasoning_id is not None:
            reasoning_ids.discard(completed_reasoning_id)

        extra = self._agui_events_for_tool_intermediate(agent_event)
        if not official:
            return extra
        if extra:
            return official + extra
        return official

    def _agui_events_for_tool_intermediate(self, agent_event: Any) -> List[AGUIEvent]:
        """识别工具调用过程中的中间结果（delta DataContent 等），转为 AG-UI 事件。"""
        return []

    def add_endpoint(self, app, func, **kwargs):
        @app.post("/ag-ui")
        async def agui_handler(request: Request):
            body = await request.json()
            agui_input = FlexibleRunAgentInput.model_validate(body)
            adapter_utils = AGUIAdapterUtils(
                thread_id=agui_input.thread_id,
                run_id=agui_input.run_id,
            )
            internal_request = adapter_utils.convert_agui_request_to_agent_request(
                agui_input,
            )
            internal_request.metadata = body.get("metadata")
            internal_request.user_id = body.get("userId")

            async def event_stream():
                try:
                    async for item in func(internal_request):
                        agui_events = self.convert_agent_event_to_agui_events(
                            adapter_utils,
                            item,
                        )
                        for agui_event in agui_events:
                            yield self._as_sse_data(agui_event)

                    if not adapter_utils.run_finished_emitted:
                        adapter_utils._run_finished_emitted = True  # noqa: SLF001
                        yield self._as_sse_data(
                            adapter_utils.build_run_event(
                                event_type=AGUIEventType.RUN_FINISHED,
                            ),
                        )
                except Exception as e:
                    traceback.print_exc()
                    error_event = RunErrorEvent(
                        message=f"Unexpected stream error: {e}",
                        code="unexpected_stream_error",
                    ).model_dump(mode="json", exclude_none=True)
                    yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                finally:
                    self._reasoning_message_ids_by_adapter.pop(
                        id(adapter_utils),
                        None,
                    )

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        return agui_handler

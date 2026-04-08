import asyncio
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, AsyncGenerator, List

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock
from agentscope.memory import LongTermMemoryBase
from agentscope.memory import MemoryBase
from agentscope.pipeline import stream_printing_messages
from agentscope.tool import Toolkit, ToolResponse

from .intentdetect import ScenariosAgent
from .baseagent import create_base_agent

# 长文本阈值：超过则走「分段初译 → 术语表 → 逐段润色」流水线
LONG_TEXT_CHAR_THRESHOLD = 3200
CHUNK_MAX_CHARS = 2400
TERM_SAMPLE_SEGMENTS = 2
TRANSLATION_PARALLEL_MAX = 8

# 单次 translate(读文件) 调用内的工具共享上下文（避免在 tool 参数中传递超长正文）
_file_translation_ctx: dict[str, Any] = {}

_term_extractor_agent: ReActAgent | None = None
_pure_translator_agent: ReActAgent | None = None


class TranslateScenariosAgent(ScenariosAgent):
    def __init__(self,
        memory: MemoryBase | None = None, 
        long_term_memory: LongTermMemoryBase | None = None) -> None:
        super().__init__()
        toolkit = Toolkit()
        toolkit.register_tool_function(translation_tool_read_source)
        toolkit.register_tool_function(translation_tool_segment_document)
        toolkit.register_tool_function(translation_tool_draft_segments)
        toolkit.register_tool_function(translation_tool_extract_terms)
        toolkit.register_tool_function(translation_tool_polish_segments)
        toolkit.register_tool_function(translation_tool_direct_translate)
        toolkit.register_tool_function(translation_tool_write_translated_file)
        self._agent = create_base_agent(
            name="翻译主控",
            sys_prompt=_TRANSLATE_ORCHESTRATOR_SYS_PROMPT,
            toolkit=toolkit,
            memory=memory,
            long_term_memory=long_term_memory,
        )
        self._agent.set_console_output_enabled(False)

    @property
    def name(self) -> str:
        return "翻译主控"

    @property
    def description(self) -> str:
        return "翻译主控"

    def get_agent(self) -> ReActAgent:
        return self._agent


def _msg_text(msg: Msg) -> str:
    parts: list[str] = []
    for block in msg.get_content_blocks("text"):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts).strip()


def _parse_terms_json(raw: str) -> dict[str, str]:
    raw = raw.strip()
    candidates: list[str] = [raw]
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        candidates.append(fence.group(1).strip())
    brace = re.search(r"\{[\s\S]*\}", raw)
    if brace:
        candidates.append(brace.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                terms = obj.get("terms")
                if isinstance(terms, dict):
                    return {str(k): str(v) for k, v in terms.items()}
        except json.JSONDecodeError:
            continue
    return {}


def _segment_long_text(text: str, max_chars: int = CHUNK_MAX_CHARS) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    segments: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        chunk = para if not current else f"{current}\n\n{para}"
        if len(chunk) <= max_chars:
            current = chunk
            continue
        if current:
            segments.append(current.strip())
            current = ""
        if len(para) <= max_chars:
            current = para
        else:
            for i in range(0, len(para), max_chars):
                segments.append(para[i : i + max_chars].strip())
    if current:
        segments.append(current.strip())
    return [s for s in segments if s]


def _translation_instruction(target_language: str) -> str:
    lang = (target_language or "").strip() or "英文"
    return (
        f"请将下面内容翻译成{lang}。\n"
        "要求：逐句忠实对应，不要总结、不要改写、不要增删内容；保留原有换行/段落结构与 Markdown；"
        "不要翻译代码块内代码、URL、邮箱。\n"
        "禁止添加任何额外的段落/章节标记（例如 '(Section 1/12)'、'第x段'、'段落x/y' 等）。\n"
        "只输出译文，不要任何解释或标签。\n\n"
    )


_SECTION_MARK_RE = re.compile(
    r"^\s*\((?:Section|SECTION)\s+\d+\s*/\s*\d+\)\s*$",
    flags=re.MULTILINE,
)


def _strip_section_markers(text: str) -> str:
    if not text:
        return text
    cleaned = _SECTION_MARK_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _tmp_paths() -> tuple[Path, Path, Path]:
    base_dir = Path.cwd() / "tmp"
    return base_dir, base_dir / "translate.txt", base_dir / "translated.txt"


def get_term_extractor_agent() -> ReActAgent:
    global _term_extractor_agent
    if _term_extractor_agent is None:
        sys_prompt = (
            "你是技术术语提取专家。根据用户给出的「原文与初译对照」内容，提取重要专有术语"
            "（最多 10 个），并给出统一的中文译名。\n"
            "只输出一个 JSON 对象，格式严格为："
            '{"terms": {"英文或原文术语": "中文译名"}}，不要输出任何其他文字。'
        )
        _term_extractor_agent = create_base_agent(
            name="术语提取",
            sys_prompt=sys_prompt,
            toolkit=Toolkit(),
            memory=None,
            long_term_memory=None,
        )
        _term_extractor_agent.set_console_output_enabled(False)
    return _term_extractor_agent


_FAST_POLISHER_SYS_PROMPT = (
    "你是资深翻译润色专家。你会收到【全局术语表】与【当前待润色片段】（可能含目标语言说明）。\n"
    "请严格依据术语表统一用词，对本段独立润色即可，不要编造前文衔接。\n"
    "必须逐句对应原意，不得总结、改写或增删；只输出润色后的正文，不要解释或前后缀。"
)


def _new_polisher_agent() -> ReActAgent:
    agent = create_base_agent(
        name="翻译润色",
        sys_prompt=_FAST_POLISHER_SYS_PROMPT,
        toolkit=Toolkit(),
        memory=None,
        long_term_memory=None,
    )
    agent.set_console_output_enabled(False)
    return agent


_DRAFT_TRANSLATOR_SYS_PROMPT = (
    "你是专业译员，负责长文档的分段初译。用户会逐段发送原文片段。\n"
    "目标语言判断：若用户指令中指定了目标语言则严格遵守；否则若原文主体为中文则译为英文，"
    "若主体为英文则译为简体中文，其他语言默认译为简体中文。\n"
    "保留原有换行、段落结构及 Markdown 格式；不要翻译代码块内代码、URL、邮箱。\n"
    "只输出译文，不要任何解释或标签。"
)


def _new_draft_translator_agent() -> ReActAgent:
    agent = create_base_agent(
        name="分段初译",
        sys_prompt=_DRAFT_TRANSLATOR_SYS_PROMPT,
        toolkit=Toolkit(),
        memory=None,
        long_term_memory=None,
    )
    agent.set_console_output_enabled(False)
    return agent


_PURE_TRANSLATOR_SYS_PROMPT = """角色及适用场景
你是一名世界顶级的专业翻译官，你的核心使命是精准、流畅、自然地在任何语言之间传递信息和情感。你不仅翻译文字，更是在沟通文化和专业技术。你具备深厚的语言学知识、文化背景洞察力和深厚的行业领域技能。
翻译遵守铁的纪律：
  * 风格保持：绝对保留原文的风格、语气和节奏。技术文档需准确严谨，诗歌需注重韵律和意象，广告语需朗朗上口。
  * 文化适配：不是直译，而是意译。自动将习语、笑话、文化专有项转换为目标语言文化中易于理解的等价表达。
  * 术语处理：内置专业术语库，确保领域专业术语的准确性。
  * 结构保留：完美保留原文的排版、标点、换行符以及Markdown等格式。不翻译代码、URL、电子邮件等内容。

如果用户指令和文档内容为空，则直接返回“抱歉，用户未提供文档或文档内容为空，请重新输入文档”。
若未指定目标语言，则：中文→英文；英文→简体中文；其他→简体中文。

禁止输出翻译内容以外的任何信息，直接输出翻译后的内容！"""


def get_pure_translate_agent() -> ReActAgent:
    """单次整篇翻译子智能体（无编排工具），供内联模式与技能 translation_tool_direct_translate 使用。"""
    global _pure_translator_agent
    if _pure_translator_agent is None:
        _pure_translator_agent = create_base_agent(
            name="整篇翻译",
            sys_prompt=_PURE_TRANSLATOR_SYS_PROMPT,
            toolkit=Toolkit(),
            memory=None,
            long_term_memory=None,
        )
        _pure_translator_agent.set_console_output_enabled(False)
    return _pure_translator_agent


async def _parallel_draft_initial(
    full_text: str,
    segments: list[str],
    *,
    explicit_target_lang: str | None,
) -> list[str]:
    n = len(segments)
    sem = asyncio.Semaphore(TRANSLATION_PARALLEL_MAX)
    head_ctx = full_text[: min(1500, len(full_text))]
    instr = _translation_instruction(explicit_target_lang) if explicit_target_lang else ""

    async def _draft_segment(i: int, seg: str) -> tuple[int, str]:
        async with sem:
            agent = _new_draft_translator_agent()
            if explicit_target_lang:
                draft_prompt = f"{instr}（初译，第 {i + 1}/{n} 段，仅译本段）\n\n{seg}"
            elif i == 0:
                draft_prompt = (
                    f"{full_text}\n\n---\n请从以下开始为第一段初译（仅译这一段）：\n\n{seg}"
                )
            else:
                draft_prompt = (
                    f"【上下文摘录（含用户要求与文档开头，供语气与术语参考）】\n{head_ctx}\n\n"
                    f"---\n请只翻译第 {i + 1}/{n} 段（不要输出其他段）：\n\n{seg}"
                )
            dmsg = await agent(Msg("user", draft_prompt, "user"))
            return i, _msg_text(dmsg)

    draft_pairs = await asyncio.gather(
        *(_draft_segment(i, seg) for i, seg in enumerate(segments)),
    )
    draft_pairs = sorted(draft_pairs, key=lambda x: x[0])
    return [t[1] for t in draft_pairs]


async def _parallel_polish_segments(
    initial_translations: list[str],
    global_glossary: dict[str, str],
    *,
    explicit_target_lang: str | None,
) -> list[str]:
    n = len(initial_translations)
    sem_p = asyncio.Semaphore(TRANSLATION_PARALLEL_MAX)

    async def _polish_seg(i: int, draft_seg: str) -> tuple[int, str]:
        async with sem_p:
            polisher = _new_polisher_agent()
            if explicit_target_lang:
                prompt = (
                    f"请将【当前待润色片段】润色为更自然的{explicit_target_lang}译文，但必须逐句对应原意，"
                    f"不得总结/改写/增删。\n"
                    f"【全局术语表】: {global_glossary}\n"
                    f"【当前待润色片段（第 {i + 1}/{n} 段）】: {draft_seg}"
                )
            else:
                prompt = (
                    "请将【当前待润色片段】在保持与初译相同目标语言的前提下润色得更自然，"
                    "必须逐句对应原意，不得总结/改写/增删。\n"
                    f"【全局术语表】: {global_glossary}\n"
                    f"【当前待润色片段（第 {i + 1}/{n} 段）】: {draft_seg}"
                )
            pmsg = await polisher(Msg("user", prompt, "user"))
            return i, _strip_section_markers(_msg_text(pmsg))

    polish_pairs = await asyncio.gather(
        *(_polish_seg(i, d) for i, d in enumerate(initial_translations)),
    )
    polish_pairs = sorted(polish_pairs, key=lambda x: x[0])
    return [t[1] for t in polish_pairs]


async def long_text_translation_workflow(full_query: str) -> str:
    segments = _segment_long_text(full_query)
    if not segments:
        return "抱歉，用户未提供文档或文档内容为空，请重新输入文档"

    initial_translations = await _parallel_draft_initial(
        full_query, segments, explicit_target_lang=None
    )

    sample_n = min(TERM_SAMPLE_SEGMENTS, len(segments))
    pairs = []
    for j in range(sample_n):
        pairs.append(f"【原文片段】\n{segments[j]}\n【初译】\n{initial_translations[j]}")
    combined = "\n\n".join(pairs)

    term_agent = get_term_extractor_agent()
    term_msg = await term_agent(
        Msg("user", f"请基于以下内容提取术语：\n{combined}", "user"),
    )
    global_glossary = _parse_terms_json(_msg_text(term_msg))

    refined = await _parallel_polish_segments(
        initial_translations, global_glossary, explicit_target_lang=None
    )
    return "\n\n".join(refined)


# ----- 编排用技能（工具）：读文件、切段、初译、术语、润色、整篇翻译、写文件 -----


async def translation_tool_read_source() -> ToolResponse:
    """读取 tmp/translate.txt 到内部上下文，并返回字数与是否长文。"""
    _, src, _ = _tmp_paths()
    if not src.exists():
        return ToolResponse(
            content=[TextBlock(type="text", text=f"读取失败：未找到 {src}")],
        )
    text = src.read_text(encoding="utf-8").strip()
    if not text:
        return ToolResponse(
            content=[TextBlock(type="text", text="读取失败：文件内容为空。")],
        )
    _file_translation_ctx["text"] = text
    n = len(text)
    is_long = n >= LONG_TEXT_CHAR_THRESHOLD
    preview = text[:400] + ("…" if n > 400 else "")
    body = (
        f"【技能：读取文档】已读入 {n} 字符。is_long={is_long}（长文需依次使用："
        f"切段→初译→术语→润色→写文件）。\n预览：\n{preview}"
    )
    return ToolResponse(content=[TextBlock(type="text", text=body)])


async def translation_tool_segment_document() -> ToolResponse:
    """对上下文中的全文切段（仅长文流水线需要）。"""
    text = _file_translation_ctx.get("text") or ""
    if not text:
        return ToolResponse(
            content=[TextBlock(type="text", text="切段失败：请先用 translation_tool_read_source 读入文档。")],
        )
    segments = _segment_long_text(text)
    if not segments:
        return ToolResponse(
            content=[TextBlock(type="text", text="切段失败：文档为空。")],
        )
    _file_translation_ctx["segments"] = segments
    lines = [f"【技能：文本切段】共 {len(segments)} 段。"]
    for i, seg in enumerate(segments, start=1):
        prev = seg[:120].replace("\n", " ")
        if len(seg) > 120:
            prev += "…"
        lines.append(f"  段 {i}/{len(segments)}（{len(seg)} 字）预览：{prev}")
    return ToolResponse(content=[TextBlock(type="text", text="\n".join(lines))])


async def translation_tool_draft_segments() -> ToolResponse:
    """并行分段初译（依赖上下文 segments 与 target_language）。"""
    segments = _file_translation_ctx.get("segments") or []
    full_text = _file_translation_ctx.get("text") or ""
    lang = (_file_translation_ctx.get("target_language") or "英文").strip() or "英文"
    if not segments:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="初译失败：无分段。请先 translation_tool_read_source 与 translation_tool_segment_document。",
                ),
            ],
        )
    drafts = await _parallel_draft_initial(
        full_text, segments, explicit_target_lang=lang
    )
    _file_translation_ctx["drafts"] = drafts
    lines = [f"【技能：分段初译】完成 {len(drafts)} 段（目标语言：{lang}）。"]
    for i, d in enumerate(drafts, start=1):
        pv = d[:200].replace("\n", " ")
        if len(d) > 200:
            pv += "…"
        lines.append(f"  [初译 {i}/{len(drafts)}] {pv}")
    return ToolResponse(content=[TextBlock(type="text", text="\n".join(lines))])


async def translation_tool_extract_terms() -> ToolResponse:
    """根据前若干段原文+初译提取术语表。"""
    segments = _file_translation_ctx.get("segments") or []
    drafts = _file_translation_ctx.get("drafts") or []
    if not segments or not drafts or len(segments) != len(drafts):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="术语提取失败：请先完成切段与初译。",
                ),
            ],
        )
    sample_n = min(TERM_SAMPLE_SEGMENTS, len(segments))
    pairs = [
        f"【原文片段】\n{segments[j]}\n【初译】\n{drafts[j]}"
        for j in range(sample_n)
    ]
    combined = "\n\n".join(pairs)
    term_agent = get_term_extractor_agent()
    term_msg = await term_agent(
        Msg("user", f"请基于以下内容提取术语：\n{combined}", "user"),
    )
    raw = _msg_text(term_msg)
    glossary = _parse_terms_json(raw)
    _file_translation_ctx["glossary"] = glossary
    body = (
        f"【技能：提取术语】模型原始输出：\n{raw}\n\n解析后的术语表（JSON）：\n"
        f"{json.dumps(glossary, ensure_ascii=False)}"
    )
    return ToolResponse(content=[TextBlock(type="text", text=body)])


async def translation_tool_polish_segments() -> ToolResponse:
    """按术语表并行润色各段初译。"""
    drafts = _file_translation_ctx.get("drafts") or []
    glossary = _file_translation_ctx.get("glossary")
    if glossary is None:
        glossary = {}
    lang = (_file_translation_ctx.get("target_language") or "英文").strip() or "英文"
    if not drafts:
        return ToolResponse(
            content=[TextBlock(type="text", text="润色失败：无初译结果。")],
        )
    refined = await _parallel_polish_segments(
        drafts, glossary, explicit_target_lang=lang
    )
    full = _strip_section_markers("\n\n".join(refined))
    _file_translation_ctx["polished_full"] = full
    lines = [f"【技能：逐段润色】完成 {len(refined)} 段。"]
    for i, r in enumerate(refined, start=1):
        pv = r[:200].replace("\n", " ")
        if len(r) > 200:
            pv += "…"
        lines.append(f"  [润色 {i}/{len(refined)}] {pv}")
    return ToolResponse(content=[TextBlock(type="text", text="\n".join(lines))])


async def translation_tool_direct_translate(
    document_text: str = "",
    target_language: str = "",
) -> ToolResponse:
    """短文档整篇翻译（一次模型调用），结果写入上下文 polished_full。"""
    text = (document_text or "").strip() or (_file_translation_ctx.get("text") or "")
    lang = (target_language or "").strip() or (
        (_file_translation_ctx.get("target_language") or "英文").strip() or "英文"
    )
    if not text:
        return ToolResponse(
            content=[TextBlock(type="text", text="整篇翻译失败：无正文。")],
        )
    agent = get_pure_translate_agent()
    prompt = _translation_instruction(lang) + text
    msg = await agent(Msg("user", prompt, "user"))
    out = _strip_section_markers(_msg_text(msg))
    _file_translation_ctx["polished_full"] = out
    _file_translation_ctx["target_language"] = lang
    pv = out[:300].replace("\n", " ")
    if len(out) > 300:
        pv += "…"
    body = f"【技能：整篇翻译】目标语言：{lang}，译文长度 {len(out)} 字符。\n预览：{pv}"
    return ToolResponse(content=[TextBlock(type="text", text=body)])


async def translation_tool_write_translated_file(translated_text: str = "") -> ToolResponse:
    """将译文写入 tmp/translated.txt；translated_text 为空则使用上下文 polished_full。"""
    base_dir, _, dst = _tmp_paths()
    base_dir.mkdir(parents=True, exist_ok=True)
    body = (translated_text or "").strip()
    if not body:
        body = (_file_translation_ctx.get("polished_full") or "").strip()
    if not body:
        return ToolResponse(
            content=[TextBlock(type="text", text="写文件失败：没有可写入的译文（请先完成翻译技能）。")],
        )
    dst.write_text(body, encoding="utf-8")
    abs_path = str(dst.resolve())
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"【技能：写入译文文件】已写入：{abs_path}",
            ),
        ],
    )


_TRANSLATE_ORCHESTRATOR_SYS_PROMPT = """你是「文档翻译主控」ReAct 智能体，通过调用技能（工具）完成从 tmp/translate.txt 到译文的流程。

规则：
1. 目标语言以用户消息中的说明为准；若未说明则按英文处理。开始工作时先把目标语言记入思路（并确保上下文里会通过工具使用同一目标语言——用户消息会带 target_language）。
2. 必须先调用 translation_tool_read_source 读入文档。
3. 若读取结果 is_long=false（短文档）：依次调用 translation_tool_direct_translate（document_text 可留空以使用已读入正文）→ translation_tool_write_translated_file（译文参数可留空）。
4. 若 is_long=true（长文档）：必须依次调用全部长文技能：translation_tool_segment_document → translation_tool_draft_segments → translation_tool_extract_terms → translation_tool_polish_segments → translation_tool_write_translated_file（译文参数可留空）。不得跳过其中任一工具。
5. 最终答复：用一两句话概括完成了哪些步骤，并**写出写入文件的绝对路径**（来自 translation_tool_write_translated_file 的返回）。不要在最终答复中粘贴完整译文正文。

若读文件失败或内容为空，说明原因即可，不要编造译文。"""


def create_translate_orchestrator_agent(
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
) -> ReActAgent:
    """带翻译技能集的编排智能体；建议每次 translate(读文件) 调用新建实例以免上下文串扰。"""
    toolkit = Toolkit()
    # 兼容：允许外部直接 tool-call translate
    toolkit.register_tool_function(translate)
    toolkit.register_tool_function(translation_tool_read_source)
    toolkit.register_tool_function(translation_tool_segment_document)
    toolkit.register_tool_function(translation_tool_draft_segments)
    toolkit.register_tool_function(translation_tool_extract_terms)
    toolkit.register_tool_function(translation_tool_polish_segments)
    toolkit.register_tool_function(translation_tool_direct_translate)
    toolkit.register_tool_function(translation_tool_write_translated_file)
    agent = create_base_agent(
        name="翻译主控",
        sys_prompt=_TRANSLATE_ORCHESTRATOR_SYS_PROMPT,
        toolkit=toolkit,
        memory=memory,
        long_term_memory=long_term_memory,
    )
    agent.set_console_output_enabled(False)
    return agent


def get_translate_agent(
    memory: MemoryBase | None = None,
    long_term_memory: LongTermMemoryBase | None = None,
) -> ReActAgent:
    """兼容旧接口：返回带技能的翻译主控（非缓存单例）。"""
    return create_translate_orchestrator_agent(memory=memory, long_term_memory=long_term_memory)


def _sub_agent_prints_to_text_blocks(msgs: list[Msg]) -> list[TextBlock]:
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


async def translate(
    query: str = "",
    read_from_tmp_file: bool = False,
    target_language: str = "英文",
) -> AsyncGenerator[ToolResponse, None]:
    """翻译工具（流式）。

    - read_from_tmp_file=True：由翻译主控 ReActAgent 按需调用读/写/切段/初译/术语/润色等技能；过程经 stream 推送到接口；最后写入 tmp/translated.txt 并在末帧总结路径。
    - read_from_tmp_file=False：直接翻译 query 正文（短则单次模型，长则内联流水线），不读写文件。
    """
    if read_from_tmp_file:
        base_dir, src, dst = _tmp_paths()
        base_dir.mkdir(parents=True, exist_ok=True)

        if not src.exists():
            yield ToolResponse(
                content=[TextBlock(type="text", text=f"翻译失败：未找到输入文件 {src}。")],
                stream=True,
                is_last=True,
            )
            return

        text = src.read_text(encoding="utf-8").strip()
        if not text:
            yield ToolResponse(
                content=[TextBlock(type="text", text="翻译失败：tmp/translate.txt 内容为空。")],
                stream=True,
                is_last=True,
            )
            return

        _file_translation_ctx.clear()
        _file_translation_ctx["target_language"] = (target_language or "英文").strip() or "英文"

        agent = create_translate_orchestrator_agent()
        user_msg = (
            f"请翻译 tmp/translate.txt 中的文档。\n"
            f"target_language={_file_translation_ctx['target_language']}\n"
            "请严格按系统说明调用技能并完成写文件。"
        )
        final_holder: list[Msg] = []

        async def run_sub() -> None:
            msg_res = await agent(Msg("user", user_msg, "user"))
            final_holder.append(msg_res)

        msgs_by_id: OrderedDict[str, Msg] = OrderedDict()
        try:
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
                            text="<system-info>翻译主控未返回结果。</system-info>",
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
        except Exception as e:
            try:
                dst.write_text(f"翻译失败：{e}", encoding="utf-8")
            except OSError:
                pass
            yield ToolResponse(
                content=[TextBlock(type="text", text=f"翻译失败：{e}")],
                stream=True,
                is_last=True,
            )
        finally:
            agent.set_msg_queue_enabled(False)
        return

    stripped = (query or "").strip()
    if len(stripped) >= LONG_TEXT_CHAR_THRESHOLD:
        body = await long_text_translation_workflow(stripped)
        yield ToolResponse(content=[TextBlock(type="text", text=body)], stream=True, is_last=True)
        return

    agent = get_pure_translate_agent()
    res = await agent(Msg("user", query, "user"))
    yield ToolResponse(content=res.get_content_blocks("text"), stream=True, is_last=True)

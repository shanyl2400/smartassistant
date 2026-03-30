from datetime import datetime, timedelta, timezone
from collections import defaultdict
import json
import re


def parse_fenced_json(answer_str: str):
    # 提取 ```json ... ``` 中的内容
    try:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", answer_str)
        payload = m.group(1) if m else str(answer_str).strip()
        return json.loads(payload) if payload else {}
    except Exception:
        return {}


def _parse_epoch_maybe(value):
    """将可能是秒/毫秒/微秒/纳秒的epoch数值解析为datetime(UTC)。失败返回datetime.min。"""
    # 优先用整数保精度，回退浮点
    ts = None
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
        else:
            s = str(value).strip()
            # 兼容纯数字或小数
            if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
                ts = float(s)
            else:
                return datetime.min.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

    # 单位判定：ns >= 1e18, us >= 1e15, ms >= 1e12, else 秒
    try:
        if ts >= 1e18:
            return datetime.fromtimestamp(ts / 1e9, tz=timezone.utc)
        if ts >= 1e15:
            return datetime.fromtimestamp(ts / 1e6, tz=timezone.utc)
        if ts >= 1e12:
            return datetime.fromtimestamp(ts / 1e3, tz=timezone.utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _as_utc(dt_obj: datetime) -> datetime:
    if dt_obj is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt_obj.tzinfo is None:
        return dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(timezone.utc)


def parse_datetime(datetime_str):
    """解析多种格式的UTC时间字符串，失败时返回 datetime.min。

    支持：
    - "utc datetime: 2025-08-20T17:24:26.000000, timezone_offset: 0"
    - 直接ISO格式（带/不带微秒，带Z或+00:00）
    - 数值epoch（秒/毫秒/微秒/纳秒），支持数字字符串
    """
    if datetime_str is None:
        return datetime.min.replace(tzinfo=timezone.utc)

    # 数值epoch（包含数字字符串）
    if isinstance(datetime_str, (int, float)):
        return _parse_epoch_maybe(datetime_str)

    s = str(datetime_str).strip()
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)

    # 数字字符串直接按 epoch 解析
    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return _parse_epoch_maybe(s)

    # 先匹配 "utc datetime: ... , timezone_offset: ..." 包裹格式
    m = re.search(r"utc\s+datetime:\s*([^,]+)\s*,\s*timezone_offset:\s*[-+]?\d+", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()

    # 兼容以 Z 结尾
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # 优先用 fromisoformat
    try:
        return _as_utc(datetime.fromisoformat(s))
    except Exception:
        pass

    # 回退到常见格式
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return _as_utc(datetime.strptime(s, fmt))
        except Exception:
            continue

    # 解析失败
    return datetime.min.replace(tzinfo=timezone.utc)


def filter_by_username_and_time(text_items, is_time_response):
    """根据username和time筛选text元素"""
            
    username = (is_time_response or {}).get("username", "")
    time = (is_time_response or {}).get("time", "")

    # 如果都没有指定，返回所有项目（包含 KG_RAG 与 DOC_LIB）
    if not username and not time:
        return list(text_items)

    filtered_items = []

    # 提取并解析目标时间（若提供）
    target_dt = parse_datetime(time) if time else None
    target_year = target_dt.year if target_dt and target_dt != datetime.min.replace(tzinfo=timezone.utc) else None

    # 筛选逻辑
    for item in text_items:
        source_type = item.get("retrieve_source_type")
        should_include = not username and not time

        # 按username筛选
        if username:
            if source_type == "KG_RAG":
                # 检查人员节点
                sub_graph = item.get("meta", {}).get("sub_graph", {})
                nodes = sub_graph.get("nodes", [])
                for node in nodes:
                    if node.get("alias") == "人员":
                        default_prop = node.get("default_property", {})
                        if str(default_prop.get("value", "")) == str(username):
                            should_include = True
                            break
            elif source_type == "DOC_LIB":
                # 检查created_by
                created_by = item.get("meta", {}).get("created_by", "")
                if str(created_by) == str(username):
                    should_include = True

        # 按time筛选：只匹配年份
        if time:
            year_match = False
            # 获取 item 的创建时间（解析后）
            item_dt = datetime.min.replace(tzinfo=timezone.utc)
            if source_type == "KG_RAG":
                sub_graph = item.get("meta", {}).get("sub_graph", {})
                nodes = sub_graph.get("nodes", [])
                for node in nodes:
                    if node.get("alias") == "文档":
                        for prop_group in node.get("properties", []):
                            if prop_group.get("tag") == "document":
                                for prop in prop_group.get("props", []):
                                    if prop.get("name") == "created_at":
                                        created_at_val = prop.get("value", "")
                                        item_dt = parse_datetime(created_at_val)
                                        break
                                if item_dt != datetime.min:
                                    break
                        if item_dt != datetime.min:
                            break
            elif source_type == "DOC_LIB":
                created_at_val = item.get("meta", {}).get("created_at", "")
                item_dt = parse_datetime(created_at_val)

            # 只比较年份
            if target_year and item_dt != datetime.min.replace(tzinfo=timezone.utc):
                try:
                    year_match = (item_dt.year == target_year)
                except Exception:
                    year_match = False

            if username and time:
                should_include = should_include and year_match
            elif time:
                should_include = year_match

        if should_include:
            filtered_items.append(item)

    # 若开启了过滤但没有命中，回退为不过滤
    if (username or time) and not filtered_items:
        return list(text_items)

    return filtered_items


def remove_duplicate_files_and_sort(retrievers_block_content, is_time_response):
    """去除重复的文件，支持username和time筛选，并保留最近一年内的文件后进行排序。"""

    files_by_name = defaultdict(list)
    now = datetime.now(timezone.utc)
    two_years_ago = now - timedelta(days=2 * 365)

    # 直接获取text数组
    original_text_items = retrievers_block_content.get("text", [])
    # 单独提取 FAQ 项（保留原始顺序，后续直接附加，不参与排序/筛选）
    faq_items = [item for item in original_text_items if item.get("retrieve_source_type") == "FAQ"]

    #单独提取 临时区 项 （保留原始顺序，后续直接附加，不参与排序/筛选）
    userinput_items = [item for item in original_text_items if item.get("retrieve_source_type") == "USER_INPUT"]
    # 非 FAQ 项进入后续流程
    text_items = [item for item in original_text_items if item.get("retrieve_source_type") != "FAQ" and item.get("retrieve_source_type") != "USER_INPUT"]

    # # 请帮我改写remove_duplicate_files.py,当retrievers_block_content1["text"]中只有一个元素且这个元素的retrieve_source_type是FAQ且这个元素的score=1，则直接返回retrievers_block_content1不做任何处理
    # if len(faq_items) == 1:
    #     if faq_items[0].get("score") == 1:
    #         retrievers_block_content["text"] = faq_items
    #         return retrievers_block_content
    # 根据username和time进行筛选
    text_items = filter_by_username_and_time(text_items, is_time_response)

    # 记录原始顺序索引
    for index, item in enumerate(text_items):
        filename = ""
        if item.get("retrieve_source_type") == "KG_RAG":
            sub_graph = item.get("meta", {}).get("sub_graph", {})
            nodes = sub_graph.get("nodes", [])

            # 查找文档节点
            document_node = None
            for node in nodes:
                if node.get("class_name") == "document":
                    document_node = node
                    break

            modified_at = datetime.min
            created_at = datetime.min

            if document_node:
                # KG_RAG: 从文档节点的default_property中提取文件名
                filename = document_node.get("default_property", {}).get("value", "")

                # 从文档节点的properties中提取时间信息
                for prop_group in document_node.get("properties", []):
                    if prop_group.get("tag") == "document":
                        for prop in prop_group.get("props", []):
                            if prop.get("name") == "modified_at":
                                modified_at_str = prop.get("value", "")
                                modified_at = parse_datetime(modified_at_str)
                            elif prop.get("name") == "created_at":
                                created_at_str = prop.get("value", "")
                                created_at = parse_datetime(created_at_str)
        elif item.get("retrieve_source_type") == "DOC_LIB":
            meta = item.get("meta", {})
            filename = meta.get("doc_name", "")
            # 处理多种时间格式
            ca = meta.get("created_at")
            ma = meta.get("modified_at")
            created_at = parse_datetime(ca)
            modified_at = parse_datetime(ma)
        if filename:  # 只有当文件名存在时才添加
            files_by_name[filename].append({
                'item': item,
                'modified_at': modified_at,
                'created_at': created_at,
                'original_index': index
            })

    # 处理重复文件，保留原始顺序中最靠前的
    unique_files = []
    for filename, files in files_by_name.items():
        if len(files) == 1:
            unique_files.append(files[0]['item'])
        else:
            files.sort(key=lambda x: x['original_index'])
            earliest_file = files[0]['item']
            unique_files.append(earliest_file)

    # 提取创建时间（兼容KG_RAG和DOC_LIB）
    def get_created_time(item):
        # KG_RAG
        if item.get("retrieve_source_type") == "KG_RAG":
            sub_graph = item.get("meta", {}).get("sub_graph", {})
            nodes = sub_graph.get("nodes", [])
            for node in nodes:
                if node.get("class_name") == "document":
                    for prop_group in node.get("properties", []):
                        if prop_group.get("tag") == "document":
                            for prop in prop_group.get("props", []):
                                if prop.get("name") == "created_at":
                                    created_at_str = prop.get("value", "")
                                    return parse_datetime(created_at_str)

        # DOC_LIB
        elif item.get("retrieve_source_type") == "DOC_LIB":
            ca = item.get("meta", {}).get("created_at")
            return parse_datetime(ca)

        return datetime.min.replace(tzinfo=timezone.utc)

    # 按原有顺序过滤两年前的文件
    filtered_files = []
    for item in unique_files:
        created_time = get_created_time(item)
        if created_time >= two_years_ago:
            filtered_files.append(item)

    # 若全部被时间窗口过滤掉，则回退为原始唯一列表
    if not filtered_files:
        filtered_files = list(unique_files)

    # 然后为每个item设置doc_name
    for idx, item in enumerate(userinput_items):
        if 'meta' not in item:
            item['meta'] = {}
        item['meta']['doc_name'] = f"参考文档{idx+1}.txt" 

    # # 分数断崖截断
    # for i in range(len(filtered_files) - 1):
    #     cur = filtered_files[i].get("score", 0) or 0
    #     nxt = filtered_files[i + 1].get("score", 0) or 0
    #     if cur > 3 and (cur - nxt) > 2:
    #         filtered_files = filtered_files[:i + 1]
    #         break

    filtered_files = filtered_files + faq_items + userinput_items

    # # 截断为前5个文件
    # if len(filtered_files) > 5:
    #     filtered_files = filtered_files[:5]

    # if len(str(filtered_files)) > 80000:
    #     filtered_files = filtered_files[:3]
    retrievers_block_content["text"] = filtered_files
    return retrievers_block_content


def main(retrievers_block_content1, full):
    # 直接处理
    is_time_response = parse_fenced_json(full.get("info", {}).get("answer", {}))
    result = remove_duplicate_files_and_sort(retrievers_block_content1, is_time_response)
    return result
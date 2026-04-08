import json
import logging
import random
import re
import ssl
import string
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ssl_context = ssl._create_unverified_context()

def get_doc_slice(as_ctx: dict, query: str, token: Optional[str] = None,doc_id: Optional[str] = None) -> Dict[str, Any]:
    """
    获取文档切片的API请求函数

    参数:
        as_ctx: 上下文对象，包含工具参数和认证信息
        query: 查询文本
        token: Bearer token，如果为None则使用默认值

    返回:
        API响应JSON解析后的字典
    """
    as_url = as_ctx.get("tool_params",{}).get("as_url", "")
    if not as_url:
        return {}

    url = f"{as_url}/api/ecosearch/v1/slice-search"

    headers = {
        'authorization': f'Bearer {token}',
        'content-type': 'application/json'
    }

    payload = {
        "limit": 200,
        "ranges": [doc_id],
        "item_output_type": [ "doc" ]
}

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')

        ssl_context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            if response.status != 200:
                raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, response)

            response_data = response.read().decode('utf-8')
            return json.loads(response_data)
    except urllib.error.HTTPError as e:
        logger.info(f"HTTP错误: {e.code} {e.reason}")
        if hasattr(e, 'read'):
            try:
                error_body = e.read().decode('utf-8')
                logger.info(f"错误响应内容: {error_body}")
            except:
                pass
        raise
    except urllib.error.URLError as e:
        logger.info(f"URL错误: {e.reason}")
        raise
    except Exception as e:
        logger.info(f"API请求失败: {e}")
        raise


def convert_slice_search_to_retriever_block(slice_search_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    将切片搜索API返回的结果转换为retrievers_block_content结构
    按照belong_doc_id分组，每个belong_doc_id对应retrievers_block_content[text]中的一个元素

    参数:
        slice_search_response: slice-search API返回的响应数据
            格式: {"doc": {"sparse_results": [...]}}

    返回:
        dict: 转换后的retrievers_block_content结构
    """
    if not slice_search_response or "doc" not in slice_search_response:
        return {"text": []}

    doc_data = slice_search_response["doc"]
    sparse_results = doc_data.get("sparse_results", [])
    if not sparse_results:
        return {"text": []}

    grouped_results = {}

    for chunk in sparse_results:
        belong_doc_id = chunk.get("belong_doc_id", "")

        if not belong_doc_id:
            continue

        if belong_doc_id not in grouped_results:
            grouped_results[belong_doc_id] = {
                "content": "",
                "retrieve_source_type": "DOC_LIB",
                "score": chunk.get("score", 0),
                "meta": {
                    "doc_lib_type": chunk.get("doc_lib_type", ""),
                    "object_id": belong_doc_id.split("/")[-1] if "/" in belong_doc_id else belong_doc_id,
                    "doc_name": chunk.get("belong_doc_name", "").split(".")[0] if chunk.get("belong_doc_name") else "",
                    "ext_type": chunk.get("belong_doc_ext_type", ""),
                    "parent_path": chunk.get("belong_doc_parent_path", ""),
                    "size": chunk.get("belong_doc_size", 0),
                    "doc_id": belong_doc_id,
                    "created_at": chunk.get("created_at", ""),
                    "created_by": chunk.get("created_by", ""),
                    "modified_at": chunk.get("created_at", ""),
                    "modified_by": chunk.get("created_by", ""),
                    "slices": [],
                    "data_source": "doc"
                }
            }

        slice_item = {
            "score": chunk.get("score", 0),
            "id": chunk.get("id", ""),
            "no": chunk.get("no", 0),
            "content": chunk.get("raw_text", "") or chunk.get("text", ""),
            "pages": [i+1 for i in chunk.get("pages", [0])]
        }

        grouped_results[belong_doc_id]["meta"]["slices"].append(slice_item)

        raw_text = chunk.get("raw_text", "") or chunk.get("text", "")
        if raw_text:
            if grouped_results[belong_doc_id]["content"]:
                grouped_results[belong_doc_id]["content"] += " " + raw_text
            else:
                grouped_results[belong_doc_id]["content"] = raw_text

    result = {
        "text": list(grouped_results.values())
    }
    return result


def get_file_metadata(docid: str, as_ctx:dict,  token: Optional[str] = None) -> Dict[str, Any]:
    """
    获取文件元数据的API请求函数

    参数:
        docid: 文件ID，格式如 "gns://E7371531EBCF42DBA5F00CB38E639650/C89C6F9C73D645CCB5FFA187DCDEC900/7CE9324356B344BA9E797A648BAA593F"
        auth_token: Bearer token，如果为None则使用默认值


    返回:
        API响应JSON解析后的字典
    """
    # 基础URL
    as_url =  as_ctx.get("tool_params",{}).get("as_url","")
    if not as_url:
        return  {}
    url = f"{as_url}/api/efast/v1/file/metadata"


    # 默认请求头
    headers = {
        'authorization': f'Bearer {token}',
        'content-type': 'application/json'

    }

    # 请求体
    payload = {"docid": docid}

    try:

        # 将payload编码为JSON bytes
        data = json.dumps(payload).encode('utf-8')

        # 创建请求对象
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')

        # 发送请求（忽略SSL验证，仅用于测试）
        ssl_context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            # 检查状态码
            if response.status != 200:
                raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, response)

            # 读取响应内容
            response_data = response.read().decode('utf-8')
            return json.loads(response_data)
    except urllib.error.HTTPError as e:
        logger.info(f"HTTP错误: {e.code} {e.reason}")
        if hasattr(e, 'read'):
            try:
                error_body = e.read().decode('utf-8')
                logger.info(f"错误响应内容: {error_body}")
            except:
                pass
        raise
    except urllib.error.URLError as e:
        logger.info(f"URL错误: {e.reason}")
        raise
    except Exception as e:
        logger.info(f"API请求失败: {e}")
        raise



def paginate_markdown(content: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    对Markdown文件内容进行分页，基于<!-- Page: X -->标记

    Args:
        content: 文件的完整文本内容

    Returns:
        JSON对象，包含分页信息
    """
    page_pattern = r'<!--\s*Page:\s*(\d+)\s*-->'

    pages = []
    current_page = None
    page_numbers = []

    lines = content.split('\n')

    for line in lines:
        match = re.match(page_pattern, line.strip())
        if match:
            if current_page is not None:
                pages.append(current_page)

            page_num = int(match.group(1))
            page_numbers.append(page_num)

            current_page = {
                'page_number': page_num,
                'content': []
            }
        else:
            if current_page is not None:
                current_page['content'].append(line)

    if current_page is not None:
        pages.append(current_page)

    result = {
        'slices': []
    }

    for idx, page in enumerate(pages):
        result['slices'].append({
            'id': generate_id(32),
            'page': page['page_number'],
            'no': idx,
            'content': ' '.join([  line for line in page['content'] if line.strip() != "" ] )
        })

    return result


def get_task_hash(as_ctx, object_id, version_id):
    """
    查询已有任务的 hash 值

    Args:
        as_ctx: 上下文对象
        object_id: 文件对象ID
        version_id: 文件版本ID

    Returns:
        str: 任务的 hash 值，失败返回 None
    """
    token = as_ctx.get("authorization", "")
    as_url = as_ctx.get("tool_params", {}).get("as_url", "")


    url = f"{as_url}/api/open-doc/v1/file-parser-tasks?object_id={object_id}&version_id={version_id}&engine=default"

    headers = {
        'Content-Type': "application/json",
        'Authorization': f'Bearer {token}',
    }

    try:
        request = urllib.request.Request(url,  headers=headers, method="GET")
        response = urllib.request.urlopen(request, context=ssl_context)

        if response.getcode() == 200:
            response_data = json.loads(response.read().decode("utf-8"))
            return response_data.get("hash", "")
        else:
            logger.info(f"查询任务 hash 失败: status code {response.getcode()}")
            return None
    except urllib.error.HTTPError as e:
        logger.info(f"查询任务 hash HTTP错误: {e.code} {e.reason}")
        return None
    except urllib.error.URLError as e:
        logger.info(f"查询任务 hash URL错误: {e.reason}")
        return None
    except Exception as e:
        logger.info(f"查询任务 hash 失败: {e}")
        return None


def parse_file_to_paginated_content(as_ctx, file_meta=None):
    """
    解析文件并返回分页内容

    Args:
        as_ctx: 上下文对象，包含认证信息和工具参数
        file_meta: 文件元数据（可选），如果提供则优先使用

    Returns:
        Dict: 分页后的JSON对象，包含 slices 数组
    """
    if file_meta and file_meta.get("docid"):
        object_id = file_meta.get("docid", "").split("/")[-1]
        version_id = file_meta.get("rev", "")
    else:
        file_info = as_ctx.get("file_infos", [{}])[0]
        object_id = file_info.get("file_id", "").split("/")[-1]
        version_id = ""

    token = as_ctx.get("authorization","")
    as_url =  as_ctx.get("tool_params",{}).get("as_url","")

    create_url = f"{as_url}/api/open-doc/v1/file-parser-tasks"
    create_payload = {
        "object_id": object_id,
        "version": version_id,
        "priority": 2,
        "input_parameters": {
            "engine": "default"
        }
    }
    headers = {
        'Content-Type': "application/json",
        'Authorization': f'Bearer {token}',
    }

    try:
        encoded_json_data = json.dumps(create_payload).encode("utf-8")
        request = urllib.request.Request(create_url, data=encoded_json_data, headers=headers, method="POST")
        response = urllib.request.urlopen(request, context=ssl_context)

        if response.getcode() == 200:
            response_data = json.loads(response.read().decode("utf-8"))
            file_hash = response_data.get("hash", "")
        else:
            logger.info(f"Error: Received status code {response.status}")
            return None
    except urllib.error.HTTPError as e:
        if e.code == 400:
            try:
                error_body = json.loads(e.read().decode("utf-8"))
                if error_body.get("code") == "Public.BadRequest" and "already exists" in error_body.get("description", ""):
                    logger.info("任务已存在，尝试获取已有任务...")
                    file_hash = get_task_hash(as_ctx, object_id, version_id)
                    if not file_hash:
                        logger.info("获取已有任务 hash 失败")
                        return None
                else:
                    logger.info(f"创建解析任务失败: {error_body.get('description', str(e))}")
                    return None
            except json.JSONDecodeError:
                logger.info(f"创建解析任务失败: {e}")
                return None
        else:
            logger.info(f"创建解析任务失败: {e}")
            return None
    except Exception as e:
        logger.info(f"创建解析任务失败: {e}")
        return None
    retry = 10
    for attempt in range(retry):
        attempt_num = attempt + 1

        logger.info(f"尝试查询任务状态，第{attempt_num}次/总共{retry}次")

        try:
            query_url = f"{as_url}/api/open-doc/v1/file-parser-tasks/{file_hash}?output_file_type=markdown&format=url"
            query_request = urllib.request.Request(query_url,  headers=headers, method="GET")
            query_response = urllib.request.urlopen(query_request, context=ssl_context)
            query_data = json.loads(query_response.read().decode("utf-8"))
            logger.info(f"查询任务状态响应: {query_data}")

            if query_response.getcode() == 200:
                status = query_data.get("status", "")
                if status == "completed":
                    content = query_data.get("data", "")
                    if content:
                        try:
                            response_for_url = urllib.request.urlopen(content["url"], timeout=30, context=ssl_context)
                            md_content = response_for_url.read().decode('utf-8')
                            return paginate_markdown(md_content)
                        except urllib.error.HTTPError as e:
                            logger.info(f"下载MD文件 HTTP错误: {e.code} {e.reason}")
                            return None
                        except urllib.error.URLError as e:
                            logger.info(f"下载MD文件 URL错误: {e.reason}")
                            return None
                        except Exception as e:
                            logger.info(f"下载MD文件失败: {e}")
                            return None
                    return None
                elif attempt < retry:
                    import time
                    time.sleep(20)
                    logger.info("任务未完成，等待20秒后重试")
                else:
                    logger.info(f"Error: Max retries exceeded")
                    return None
            else:
                logger.info(f"Error: Received status code {query_response.status}")
                return None
        except Exception as e:
            if attempt < retry:
                import time
                time.sleep(20)
                logger.info(f"查询任务状态失败: {e}")
            else:
                logger.info(f"查询任务状态失败: {e}")
                return None

    return None



def full_structed_text(as_ctx):
    """
    获取文件的完整结构化文本

    Args:
        as_ctx: 上下文对象

    Returns:
        结构化文本字典，失败返回 None
    """
    doc_id = as_ctx.get("file_infos", [{}])[0].get("file_id", "")
    token = as_ctx.get("authorization","")
    as_url =  as_ctx.get("tool_params",{}).get("as_url","")
    url = f"{as_url}/api/ecoindex/v1/subdocfetch/full_structed_text"


    payload = {
        "doc_id":doc_id.split("/")[-1]
    }
    headers = {
        'Content-Type': "application/json",
        'Authorization': f'Bearer {token}',
        }

    encoded_json_data = json.dumps(payload).encode("utf-8")

    try:
        request = urllib.request.Request(url, data=encoded_json_data, headers=headers,method="POST")
        response = urllib.request.urlopen(request, context=ssl_context)

        if response.getcode() == 200:
            response_data = json.loads(response.read().decode("utf-8"))
            return response_data
        else:
            logger.info(f"full_structed_text Error: Received status code {response.status}")
            return None
    except urllib.error.HTTPError as e:
        logger.info(f"full_structed_text HTTP错误: {e.code} {e.reason}")
        return None
    except urllib.error.URLError as e:
        logger.info(f"full_structed_text URL错误: {e.reason}")
        return None
    except Exception as e:
        logger.info(f"full_structed_text API请求失败: {e}")
        return None



def extract_content_from_json(json_data: Dict[str, Any]) -> str:
    """
    从JSON数据中提取 content 字段。
    支持路径: data -> "0" -> content 或 object.data.0.content
    """
    # 如果存在 'object' 键，则深入一层
    if 'data' in json_data:
        data = json_data['data']
        content = ""
        for _,value in data.items():
            content += value.get('content', '')
            return content.strip()
    # 如果找不到，返回空字符串
    return ''

def split_by_page_markers(text: str) -> List[Dict[str, Any]]:
    """
    根据页码标记分割文本。
    页码标记类似单独一行的 '1 / 8', '2 / 8' 等。
    返回列表，每个元素包含页码和该页内容。
    """
    # 匹配单独一行的页码标记，例如 "1 / 8" 或 "  2 / 8  "
    # 使用多行模式，^ 和 $ 匹配行首行尾
    page_pattern = r'(?m)^\s*(\d+)\s*/\s*(\d+)\s*$'
    matches = list(re.finditer(page_pattern, text))

    if not matches:
        # 没有页码标记，整个文本作为第1页
        return [{'page_num': 1, 'content': text}]

    pages = []
    # 处理第一个匹配之前的内容（如果有）
    first_match = matches[0]
    start_pos = 0
    # 如果第一个匹配的页码是1，那么之前的内容作为第1页？通常页码标记出现在每页开头。
    # 这里简单处理：将第一个匹配之前的内容作为第0页（封面等）
    if first_match.start() > start_pos:
        page_content = text[start_pos:first_match.start()].strip()
        if page_content:
            pages.append({'page_num': 0, 'content': page_content})

    # 遍历匹配，每对匹配之间的内容属于当前匹配指示的页码
    for i, match in enumerate(matches):
        page_num = int(match.group(1))  # 当前页码
        # 本页内容从当前匹配的结束位置开始，到下一个匹配的开始位置结束
        if i < len(matches) - 1:
            next_match = matches[i + 1]
            end_pos = next_match.start()
        else:
            end_pos = len(text)
        page_content = text[match.end():end_pos].strip()
        if page_content:  # 可能为空，如果两个标记连续
            pages.append({'page_num': page_num, 'content': page_content})

    return pages

def split_by_punctuation(text: str, punctuation_set: str = None) -> List[str]:
    """
    根据标点符号集合分割文本，保留标点符号在切片末尾。
    默认标点符号：中文句号、感叹号、问号、英文句号、感叹号、问号、分号。
    逗号、顿号等不用于分割，因为它们通常不是句子结束符。
    """
    if punctuation_set is None:
        # 默认句子结束符,需要包含换行符
        punctuation_set = '。！？.?!;\n\t'
    # 转义标点符号用于正则表达式
    escaped = re.escape(punctuation_set)
    # 匹配非标点字符序列，后跟一个标点符号（可选），同时保留标点符号
    # 使用正则表达式：([^标点]+[标点]?)
    pattern = f'([^{escaped}]+[{escaped}]?)'
    slices = re.findall(pattern, text)
    # 过滤空字符串和空白
    slices = [s.replace("\n","").replace("\t","").strip() for s in slices if s.strip()]
    return slices

def merge_short_slices(slices: List[str], min_length: int = 20) -> List[str]:
    """
    合并短切片，确保每个切片长度至少为 min_length（字符数）。
    合并策略：从左到右遍历切片，如果切片长度小于 min_length，
    则将其与后续切片合并，直到合并后的长度达到 min_length 或没有更多切片。
    """
    if not slices:
        return []

    merged = []
    i = 0
    while i < len(slices):
        current_slice = slices[i]
        # 如果当前切片已经足够长，直接添加到结果
        if len(current_slice) >= min_length:
            merged.append(current_slice)
            i += 1
            continue

        # 否则，开始合并后续切片
        merged_slice = current_slice
        i += 1

        # 继续合并后续切片，直到合并后的切片足够长或没有更多切片
        while i < len(slices) and len(merged_slice) < min_length:
            next_slice = slices[i]
            # 用空格连接切片，避免粘连
            merged_slice = merged_slice.strip()  + next_slice.strip() if merged_slice else next_slice
            i += 1

        merged.append(merged_slice)

    return merged

def generate_id(length: int = 32) -> str:
    """生成指定长度的字母数字ID（大小写字母+数字）"""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def process_json_to_slices(json_data: Dict[str, Any],
                          punctuation_set: str = None,
                          min_slice_length: int = 20) -> Dict[str, Any]:
    """
    主处理函数：提取内容，分页，分句，生成切片信息。
    返回包含切片列表的字典。

    参数:
        json_data: 输入的JSON数据
        punctuation_set: 标点符号集合，用于句子分割
        min_slice_length: 最小切片长度，短于此长度的句子将被合并
    """
    content = extract_content_from_json(json_data)
    if not content:
        return {'slices': []}

    pages = split_by_page_markers(content)
    all_slices = []
    slice_index = 0
    for page in pages:
        page_num = page['page_num']
        page_content = page['content']
        # 按标点符号切割
        slices = split_by_punctuation(page_content, punctuation_set)
        # 合并短切片
        slices = merge_short_slices(slices, min_slice_length)
        for slice_content in slices:
            slice_id = generate_id(32)
            all_slices.append({
                'score': 0.5,
                'id': slice_id,
                'page': page_num,
                'no': slice_index,
                'content': slice_content
            })
            slice_index += 1

    return {'slices': all_slices}


def convert_slice_to_retriever_block(chunks,doc_metadata):
    """
    将slice_search.json中的doc dense_results元素转换为retrievers_block_content[text]结构
    按照belong_doc_id分组，每个belong_doc_id对应retrievers_block_content[text]中的一个元素

    Args:
        slice_search_data (dict): 从slice_search.json加载的数据

    Returns:
        dict: 转换后的retrievers_block_content结构
    """
    # 创建一个字典来按belong_doc_id分组
    grouped_results = {}

    # 遍历所有dense_results元素
    for chunk in chunks:
        belong_doc_id = doc_metadata["docid"]
        # 如果该belong_doc_id还没有在字典中，初始化它
        if belong_doc_id not in grouped_results:
            grouped_results[belong_doc_id] = {
                "content": "",  # 将所有raw_text连接起来
                "retrieve_source_type": "DOC_LIB",
                "score": chunk.get("score", 0.5),  # 可以根据需要调整
                "meta": {
                    "doc_lib_type": chunk.get("doc_lib_type", doc_metadata["doc_lib_type"]),
                    "object_id": belong_doc_id.split("/")[-1],
                    "doc_name": chunk.get("belong_doc_name", doc_metadata["name"].split(".")[0]),
                    "ext_type": chunk.get("belong_doc_ext_type", "."+doc_metadata["name"].split(".")[1]),
                    "parent_path": chunk.get("belong_doc_parent_path", doc_metadata["docid"].split(".")[0]),
                    "size": chunk.get("belong_doc_size", doc_metadata["size"]),
                    "doc_id": belong_doc_id,
                    "created_at": chunk.get("created_at", doc_metadata["modified"]),
                    "created_by": chunk.get("created_by",  doc_metadata["editor"]),
                    "modified_at": chunk.get("modified_at",  doc_metadata["modified"]),
                    "modified_by": chunk.get("modified_by", doc_metadata["editor"]),
                    "slices": [],
                    "data_source": "doc"
                }
            }
        # 将当前元素添加到slices中
        slice_item = {
            "score": chunk.get("score", 0),
            "id": chunk.get("id", ""),
            "no": chunk.get("no", 0),
            "content": chunk.get("content", ""),
            "pages": chunk.get("pages", [1])
        }

        grouped_results[belong_doc_id]["meta"]["slices"].append(slice_item)


        # 将raw_text添加到content中（避免重复添加）
        raw_text = chunk.get("content", "")
        if raw_text and raw_text not in grouped_results[belong_doc_id]["content"]:

            if grouped_results[belong_doc_id]["content"]:
                grouped_results[belong_doc_id]["content"] + raw_text
            else:
                grouped_results[belong_doc_id]["content"] = raw_text
    # 转换为最终的retrievers_block_content结构
    result = {
        "text": list(grouped_results.values())
    }
    return result


def main(as_ctx,query):
    file_infos = as_ctx.get("file_infos",[])
    if not file_infos: return {}
    if len(file_infos) == 0:
        return {}
    else:
        doc_id = file_infos[0].get("file_id","")
    token = as_ctx.get("authorization","")
    ## 先获取临时区文件切片向量
    if query:
        slice_search_response = get_doc_slice(as_ctx, query, token,doc_id)
        if slice_search_response:
            rst = convert_slice_search_to_retriever_block(slice_search_response)
            if rst and rst.get("text"):
                return rst
    else:
        return {"text":[]}

    ## 再尝试获取文件GPU解析切片内容
    doc_metadata = get_file_metadata(doc_id,as_ctx,token)
    try:
        result = parse_file_to_paginated_content(as_ctx,doc_metadata)
        if result and result.get("slices"):
            rst = convert_slice_to_retriever_block(result["slices"], doc_metadata)
            return rst
    except Exception as e:
        logger.info(f"parse_file_to_paginated_content failed: {e}")

    ## 再尝试获取文件CPU解析切片内容
    structed_text = full_structed_text(as_ctx)
    chunks = process_json_to_slices(structed_text)
    rst = convert_slice_to_retriever_block(chunks["slices"],doc_metadata)
    return rst



if __name__ == "__main__":
    as_ctx = {
      "authorization": "ory_at_oagrWyhi3Mb0hfTgnglhNfBNOEZUXtHFrzwrI426tvc.9VQNGQNlZiyn5Y_gevljvezLu4LIWazD_Tj2KYHv0Fs",
      "doc_info": {
        "doc_dsid": "25",
        "doc_fields": []
      },
      "file_infos": [
        {
          "file_ext": ".pdf",
          "file_id": "gns://A8AEBB9230014EBD9CDAD854DEEB92AB/706C1B503142423D8BC855C28615C5A0/1DFB03B8AF854FA09ADA3DF433CB81B4",
          "file_name": "华东区域-深圳中电-1-2-2024-05-04251 (1).pdf"
        }
      ],
      "tool_params": {
        "as_url": "https://10.4.174.215",
        "ad_url": "https://10.4.71.220:8444"
      }
    }
    rst = main(as_ctx,"合同")
    print(rst)

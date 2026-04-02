import aiohttp
import json
import asyncio
import re
import os
from typing import List, Dict, Any, Optional, Set, Tuple
from abc import ABC, abstractmethod
from collections import defaultdict

from agentscope.message import TextBlock, ToolUseBlock
from agentscope.tool import ToolResponse, Toolkit, execute_python_code
from tools.remove_duplicate_block import remove_duplicate_files_and_sort
# ==========================================
# 默认配置 (Defaults)
# ==========================================
DEFAULT_CONFIG = {
    # 召回切片配置
    "MAX_DOC_NUM": 8,          # 最终保留的最大文档(对象)数
    "BEFORE_SLICE_NUM": 1,     # 向前扩充的切片数
    "AFTER_SLICE_NUM": 1,      # 向后扩充的切片数

    # 阈值配置
    "RECALL_MIN_SCORE": 0.5,   # 初排召回阈值 (0则不传)
    "RERANK_MIN_SCORE": 0.2,   # Rerank 后的最小分数阈值
    # TOP_N_RECALL分成doc，wiki，faq，放在map里
    "TOP_N_RECALL_MAP": {
        "doc": 60,
        "wikidoc": 30,
        "faq": 10
    },
    "MAX_SLICES_FOR_RERANK": 300,   # 提供给rerank的slice数量上限

    # 调试与鉴权
    "IS_DEBUG": False,
    "AD_APP_ID": "OS2E5MVpWLHmqtouewj"
}

# ==========================================
# 核心业务对象 (Domain Objects)
# ==========================================

"""
上游结构体

// agentDebugInfoRetrieversBlockContentText 检索器块内容文本调试信息
type agentDebugInfoRetrieversBlockContentText struct {
	Content            string      `json:"content"`
	Meta               interface{} `json:"meta"`
	RetrieveSourceType string      `json:"retrieve_source_type"`
	Score              float64     `json:"score"`
}

// agentDebugInfoDocQARetrieversBlockContentTextMeta 检索器块内容文本元数据调试信息
type agentDebugInfoRetrieversBlockContentTextMetaDocLib struct {
	ObjectID   string                `json:"object_id"`
	DocName    string                `json:"doc_name"`
	ExtType    string                `json:"ext_type"`    // 后缀名
	ParentPath string                `json:"parent_path"` // 路径
	Size       int64                 `json:"size"`
	DocID      string                `json:"doc_id"`      // gns
	DataSource string                `json:"data_source"` // 数据集
	Slices     []*interfaces.V1Slice `json:"slices"`
	DocLibType string                `json:"doc_lib_type"` // 文档库类型
	SpaceID    string                `json:"space_id"`     // 空间ID
}

type agentDebugInfoRetrieversBlockContentTextMetaFAQ struct {
	Content []*FAQRetrieverContent `json:"content"`
	ID      string                 `json:"id"`
	Title   []string               `json:"title"`
}

type FAQRetrieverContent struct {
	Content string `json:"content"`
	Details string `json:"details"`
	Type    string `json:"type"`
}

// V1Slice 切片文档
type V1Slice struct {
	ID      string `json:"id"`
	No      int    `json:"no"`
	Content string `json:"content"`
	Pages   []int  `json:"pages"`
}
"""

class FatalAPIError(Exception):
    """当 API 返回非 200 或网络错误时抛出此异常，用于中断整个流程"""
    pass

class RecallObject(ABC):
    """召回结果对象的基类"""
    def __init__(self, doc_id: str, max_score: float, original_slices: List[dict]):
        self.doc_id = doc_id
        self.max_score = max_score
        self.original_slices = original_slices
        # 提取第一个切片作为元数据基准
        self._meta_ref = original_slices[0] if original_slices else {}

    @abstractmethod
    def get_expand_query(self) -> Optional[Dict]:
        """获取需要扩充上下文的查询参数，不需要扩充则返回None"""
        pass

    @abstractmethod
    def add_context(self, expanded_slices: List[dict]):
        """接收扩充后的上下文切片"""
        pass

    @abstractmethod
    def construct_result(self) -> dict:
        """组装最终输出给大模型的字典对象"""
        pass


class FaqObject(RecallObject):
    """FAQ 类型对象：无需上下文扩充，专注于问答格式化"""
    def get_expand_query(self) -> Optional[Dict]:
        return None # FAQ 不需要扩充

    def add_context(self, expanded_slices: List[dict]):
        pass # Do nothing

    def construct_result(self) -> dict:
        clean_meta = self._meta_ref.get("clean_meta_data", {})
        
        # 构造 Meta Payload
        formatted_contents = [
            {"content": c.get("content", "")} 
            for c in clean_meta.get("content", [])
        ]
        
        meta = {
            "id": clean_meta.get("id", ""),
            "title": clean_meta.get("title", ""),
            "content": formatted_contents,
        }
        
        # 构造最终 Block
        return {
            "retrieve_source_type": "FAQ",
            "score": self.max_score,
            # FAQ 直接使用 raw_text (即 问题+答案 的拼接)
            "content": self._meta_ref.get("raw_text", ""), 
            "meta": meta
        }


class DocObject(RecallObject):
    """文档/Wiki 类型对象：支持切片去重、排序、省略号拼接"""
    def __init__(self, doc_id: str, max_score: float, original_slices: List[dict]):
        super().__init__(doc_id, max_score, original_slices)
        self.all_slices = list(original_slices) # 初始包含原始切片
        self.is_extended = False

    def get_expand_query(self) -> Optional[Dict]:
        """构造用于 fetch 接口的参数"""
        # 只需要基于原始命中的切片去扩充
        # 这里为了简化，通常基于最高分的那个切片，或者所有命中的切片去扩充
        # 策略：对该文档下所有命中的 segment_id 进行扩充
        return [
            {"docid": self.doc_id, "segmentid": s.get("segment_id")}
            for s in self.original_slices 
            if s.get("segment_id") is not None
        ]

    def add_context(self, expanded_slices: List[dict]):
        """合并扩充回来的切片"""
        if not expanded_slices: return
        self.is_extended = True
        
        # 补充元数据 (fetch接口返回的切片往往缺失 doc_lib_type 等信息)
        # 从 _meta_ref 中提取通用字段
        common_meta = {
            k: v for k, v in self._meta_ref.items() 
            if k not in ["segment_id", "raw_text", "score", "id", "content", "pages"]
        }
        
        for s in expanded_slices:
            # 补全信息
            s.update(common_meta)
            self.all_slices.append(s)

    def construct_result(self) -> dict:
        # 1. 整理切片：去重、排序、拼接
        full_text, final_slices_meta = self._process_segments()
        
        # 2. 构造 Meta Payload
        meta = {
            "doc_id": self.doc_id,
            "doc_name": self._meta_ref.get("belong_doc_name", ""),
            "doc_path": self._meta_ref.get("belong_doc_path", ""),
            "parent_path": self._meta_ref.get("belong_doc_parent_path", ""),
            "doc_lib_type": self._meta_ref.get("doc_lib_type", ""),
            "ext_type": self._meta_ref.get("belong_doc_ext_type", ""),
            "size": self._meta_ref.get("belong_doc_size", 0),
            "created_by": self._meta_ref.get("created_by", ""),
            "object_id": self.doc_id.split('/')[-1] if self.doc_id else "",
            "slices": final_slices_meta
        }

        return {
            "retrieve_source_type": "DOC_LIB", # Wiki 也统一归为此类或视需求区分
            "score": self.max_score,
            "content": full_text,
            "meta": meta
        }

    def _process_segments(self) -> Tuple[str, List[dict]]:
        """内部方法：处理切片拼接逻辑"""
        unique_map = {}
        for s in self.all_slices:
            seg_id = s.get("segment_id")
            if seg_id is None: continue
            
            raw_id = s.get("id")
            
            text = s.get("raw_text") or s.get("content") or ""
            score = s.get("score", 0)
            
            # 如果同一个位置有多个切片（比如扩充的和原始的），保留分数高的
            if seg_id not in unique_map or score > unique_map[seg_id]["score"]:
                unique_map[seg_id] = {
                    "segment_id": seg_id, # 逻辑 ID，通常还是要保留给下游排序用
                    "id": raw_id,               # 【关键点】原样填入 id
                    "score": score,
                    "content": text,
                    "pages": s.get("pages")
                }

        # 排序
        sorted_segs = sorted(unique_map.values(), key=lambda x: x["segment_id"])
        
        # 拼接
        full_text_parts = []
        meta_list = []
        last_id = -999

        for i, item in enumerate(sorted_segs):
            # 【修改点】number 是排序后切片在 doc 中的第几个 (从1开始)
            item["no"] = i + 1 
            
            meta_list.append(item)
            text = item["content"]
            if not text: continue
            
            curr_id = item["segment_id"]
            if last_id != -999 and curr_id != last_id + 1:
                full_text_parts.append("...\n" + text)
            else:
                prefix = "\n" if full_text_parts else ""
                full_text_parts.append(prefix + text)
            last_id = curr_id
            
        return "".join(full_text_parts).strip(), meta_list


# ==========================================
# 召回流水线类 (Recall Pipeline)
# ==========================================
class RecallPipeline:
    def __init__(self, as_ctx: Dict[str, Any]):
        self.ctx = as_ctx
        self.config = DEFAULT_CONFIG.copy()
        
        # 1. 配置加载
        tool_params = as_ctx.get("tool_params", {})
        if tool_params.get("as_url"): self.config["ANYSHARE_SERVER_URL"] = tool_params["as_url"]
        
        if "RECALL_MIN_SCORE" in tool_params:
            self.config["RECALL_MIN_SCORE"] = float(tool_params["RECALL_MIN_SCORE"])

        # 2. 基础校验
        self.anyshare_url = self._get_mandatory_config("ANYSHARE_SERVER_URL")
        self.anydata_url = tool_params["ad_url"]
        self.app_id = as_ctx["app_id"]
        self.token = as_ctx.get("authorization", "")
        
        # 3. 保存 embedding 模型名称，懒加载时使用
        self._embedding_model_name = tool_params.get("embedding_name")
        self.embedding_url = None
        self.rerank_url = None
        

    async def _ensure_model_urls(self):
        model_list = await self._fetch_model_list()
        
        # 按类型分组
        embedding_models = [m for m in model_list if m.get("model_type") == "embedding"]
        reranker_models = [m for m in model_list if m.get("model_type") == "reranker"]
        
        # 确定 embedding 模型：优先使用指定名称，找不到则用第一个
        selected_embedding = None
        if self._embedding_model_name:
            selected_embedding = next((m for m in embedding_models if m.get("model_name") == self._embedding_model_name), None)
        if not selected_embedding and embedding_models:
            selected_embedding = embedding_models[0]
        
        # 确定 reranker 模型：取第一个
        selected_reranker = reranker_models[0] if reranker_models else None
        
        # 设置 URL
        if selected_embedding:
            emb_name = selected_embedding.get("model_name")
            self.embedding_url = f"{self.anydata_url}/api/model-factory/v1/external-small-model/used/{emb_name}"
        else:
            raise ValueError("找不到可用的 embedding 模型")
        
        if selected_reranker:
            rerank_name = selected_reranker.get("model_name")
            self.rerank_url = f"{self.anydata_url}/api/model-factory/v1/external-small-model/used/{rerank_name}"
        else:
            raise ValueError("找不到可用的 reranker 模型")
                
        if self.config["IS_DEBUG"]:
            print(f"[模型配置] Embedding: {selected_embedding.get('model_name')} -> {self.embedding_url}")
            print(f"[模型配置] Reranker: {selected_reranker.get('model_name')} -> {self.rerank_url}")

    async def _fetch_model_list(self) -> List[dict]:
        """异步获取小模型列表"""
        url = f"{self.anydata_url}/api/model-factory/v1/external-small-model/info-list"
        headers = {
            "Content-Type": "application/json",
            "AppID": self.app_id
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, ssl=False, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status >= 400:
                        if self.config["IS_DEBUG"]:
                            print(f"[模型列表获取失败] Status: {resp.status}")
                        return []
                    data = await resp.json()
                    # 返回结构为 {"res": [...]}
                    return data.get("res", []) if isinstance(data, dict) else data
        except Exception as e:
            if self.config["IS_DEBUG"]:
                print(f"[模型列表获取失败] {e}")
            return []

    def _get_mandatory_config(self, key: str) -> str:
        val = self.config.get(key) or self.ctx.get(key)
        if not val: raise ValueError(f"Missing config: {key}")
        return val.rstrip('/')

    async def _send(self, method, url, headers, body=None):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.request(method, url, headers=headers, json=body, ssl=False) as resp:
                    # 【核心逻辑】只要不是 200，立刻抛出异常
                    if resp.status >= 400:
                        error_text = await resp.text()
                        error_msg = f"[Fatal API Error] Status: {resp.status} | URL: {url} | Body: {error_text}"
                        if self.config["IS_DEBUG"]:
                            print(error_msg)
                        raise FatalAPIError(error_msg)

                    # 统一先拿原始文本，再尝试解析 JSON，避免把解析错误当成“网络错误”
                    text = await resp.text()
                    try:
                        return json.loads(text) if text else None
                    except json.JSONDecodeError as e:
                        # 尝试清洗非法控制字符后再解析一次
                        cleaned_text = re.sub(r"[\x00-\x1F\x7F]", "", text)
                        try:
                            return json.loads(cleaned_text) if cleaned_text else None
                        except json.JSONDecodeError as e2:
                            snippet = cleaned_text[:500].replace("\n", "\\n")
                            error_msg = (
                                f"[Fatal API JSON Error] URL: {url} | Reason: {e2} | "
                                f"BodySnippet: {snippet}"
                            )
                            if self.config["IS_DEBUG"]:
                                print(error_msg)
                            raise FatalAPIError(error_msg)
            except FatalAPIError:
                # 重新抛出 FatalAPIError，不要被下面的通用 Exception 吞掉
                raise
            except Exception as e:
                # 捕获真正的网络连接错误（如超时、DNS 解析失败），并转换为 FatalAPIError
                error_msg = f"[Fatal Network Error] URL: {url} | Reason: {e}"
                if self.config["IS_DEBUG"]:
                    print(error_msg)
                raise FatalAPIError(error_msg)

    async def api_get_gns(self, item_id):
        url = f"{self.anyshare_url}/api/efast/v2/items/{item_id}/doc_id"
        res = await self._send("GET", url, {"Authorization": f"Bearer {self.token}"})
        return res["doc_id"] if res else None

    async def api_embedding(self, query):
        body = {"texts": [query]}
        res = await self._send("POST", self.embedding_url, {"Content-Type": "application/json", "AppID": self.app_id}, body)
        return res[0] if res else []

    async def api_search(self, body):
        url = f"{self.anyshare_url}/api/ecosearch/v1/slice-search"
        return await self._send("POST", url, {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}, body)

    async def api_fetch(self, body):
        url = f"{self.anyshare_url}/api/ecoindex/v1/index/slicefetch"
        return await self._send("POST", url, {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}, body)

    async def api_rerank(self, body):
        return await self._send("POST", self.rerank_url, {"Content-Type": "application/json", "AppID": self.app_id}, body)

    # --- Helper ---
    def normalize_scores(self, data):
        if not data: return []
        mi, ma = min(data), max(data)
        if ma - mi == 0: return [0.0] * len(data)
        return [(x - mi) / (ma - mi) - 0.5 for x in data]

    # ==========================================
    # 业务流程步骤 (Steps)
    # ==========================================

    async def step1_recall(self, query: str) -> List[dict]:
        await self._ensure_model_urls()
        """多路并发召回"""
        doc_info = self.ctx.get("doc_info")
        # 如果 doc_info 为 None 或 空字典，视为全库搜索
        is_global = not doc_info or doc_info.get("doc_fields", []) == []
        
        ids_map = {"doc": [], "wikidoc": [], "faq": []}
        
        if not is_global:
            fields = doc_info.get("doc_fields", [])
            for f in fields:
                if not f.get("field_path"): continue
                src = f.get("field_source")
                if src == "dir": ids_map["doc"].append(f["field_path"])
                elif src == "wikidoc": ids_map["wikidoc"].append(f["field_path"])
                elif src == "kc_faq": ids_map["faq"].append(f["field_path"])
        
        # 转换 Doc GNS
        if ids_map["doc"]:
            gns_tasks = [self.api_get_gns(x) for x in ids_map["doc"]]
            gns_res = await asyncio.gather(*gns_tasks)
            ids_map["doc"] = [x for x in gns_res if x]

        query_emb = await self.api_embedding(query)
        
        tasks = []
        for stype in ["doc", "wikidoc", "faq"]:
            # 如果不是全库搜索且该类型没有ID，则跳过
            if not is_global and not ids_map[stype]:
                continue
                
            payload = {
                "limit": self.config["TOP_N_RECALL_MAP"][stype],
                "text": query,
                "embedding": query_emb, 
                "item_output_detail": {"field": "title"},
                "item_output_type": [stype]
            }
            if self.config.get("RECALL_MIN_SCORE", 0) > 0:
                payload["min_score"] = self.config["RECALL_MIN_SCORE"]

            # 注入范围参数
            ids = ids_map[stype]
            if ids:
                if stype == "doc": payload["ranges"] = ids
                elif stype == "wikidoc": payload["wiki_space_ids"] = ids
                elif stype == "faq": payload["faq_space_ids"] = ids
            
            tasks.append(self._do_single_search(payload, stype))

        results = await asyncio.gather(*tasks)
        return [item for sublist in results for item in sublist]

    async def _do_single_search(self, payload, stype):
        res = await self.api_search(payload)
        if not res: return []
        
        final = []
        if stype == "faq":
            # FAQ 标准化
            for item in res.get("faq", []):
                titles = item.get("title", [])
                content_parts = [c.get("content", "") for c in item.get("content", []) if c.get("type") == "text"]
                full_text = f"问题: {titles[0] if titles else ''}\n答案: {' '.join(content_parts)}"
                
                final.append({
                    "belong_doc_id": item.get("id"),
                    "score": item.get("score", 0),
                    "raw_text": full_text,
                    "type": "faq",
                    "clean_meta_data": item
                })
        else:
            # Doc/Wiki
            data = res.get(stype, {}) or res.get("doc", {}) # 兼容
            merged = list(data.get("dense_results", []))
            sparse_ids = {x["slice_id"] for x in merged}
            for s in data.get("sparse_results", []):
                if s["slice_id"] not in sparse_ids:
                    merged.append(s)
            
            for m in merged: m["type"] = stype
            final.extend(merged)
        return final

    def deduplicate_by_md5(self, slices):
        """
        rerank前先用md5字段去重一下
        保留相同md5的最高的score的slice
        """
        deduplicated_slices = {}
        for s in slices:
            md5 = s.get("md5", "")
            if md5 and md5 not in deduplicated_slices:
                deduplicated_slices[md5] = {
                    "score": s.get("score", 0),
                    "slice": s
                }
            else:
                if md5 and md5 in deduplicated_slices and s.get("score", 0) > deduplicated_slices[md5]["score"]:
                    deduplicated_slices[md5]["score"] = s.get("score", 0)
                    deduplicated_slices[md5]["slice"] = s
        return [x["slice"] for x in deduplicated_slices.values()]
            
    async def step2_rerank(self, query, slices):
        """
        rerank前先用md5字段去重一下
        保留相同md5的最高的score的slice
        """

        slices = self.deduplicate_by_md5(slices)
        if len(slices) > self.config["MAX_SLICES_FOR_RERANK"]:
            slices = slices[:self.config["MAX_SLICES_FOR_RERANK"]]
        if not slices: return []
        scores = await self.api_rerank({"slices": [s["raw_text"] for s in slices], "query": query})
        if not scores: return []
        
        norm_scores = self.normalize_scores(scores)
        min_s = self.config["RERANK_MIN_SCORE"]
        
        valid = []
        for i, sc in enumerate(norm_scores):
            if sc >= min_s:
                slices[i]["score"] = sc
                valid.append(slices[i])
        
        valid.sort(key=lambda x: x["score"], reverse=True)
        return valid

    def step3_build_objects(self, slices: List[dict]) -> List[RecallObject]:
        """将切片聚合并转换为对象，返回 Top N 个大对象"""
        groups = defaultdict(list)
        # 保持顺序
        seen_order = []
        
        for s in slices:
            uid = s.get("belong_doc_id")
            if not uid: continue
            if uid not in groups:
                seen_order.append(uid)
            groups[uid].append(s)
            
        # 转换为对象列表
        obj_list = []
        for uid in seen_order:
            group_slices = groups[uid]
            max_score = max(s.get("score", 0) for s in group_slices)
            first = group_slices[0]
            
            if first.get("type") == "faq":
                obj = FaqObject(uid, max_score, group_slices)
            else:
                obj = DocObject(uid, max_score, group_slices)
            obj_list.append(obj)
            
        # 按对象最高分排序并取 Top N
        obj_list.sort(key=lambda x: x.max_score, reverse=True)
        return obj_list[:self.config["MAX_DOC_NUM"]]

    async def step4_expand_context(self, objects: List[RecallObject]):
        """批量处理对象的上下文扩充"""
        # 1. 收集所有对象的扩充需求
        fetch_requests = []
        # 记录 request index 到 object 的映射，方便回填
        req_map = [] 
        
        bs = self.config["BEFORE_SLICE_NUM"]
        as_step = self.config["AFTER_SLICE_NUM"]
        
        if bs <= 0 and as_step <= 0: return

        for obj in objects:
            queries = obj.get_expand_query() # list of dicts
            if queries:
                for q in queries:
                    q["before_step"] = bs
                    q["after_step"] = as_step
                    fetch_requests.append(q)
                    req_map.append(obj) # 记录该请求属于哪个对象

        if not fetch_requests: return

        # 2. 调用 API (一次性 Batch)
        # 注意：如果 requests 太多，可能需要分批，这里暂假设 API 能扛得住 TOP_N * slices_per_doc
        payload = {"index": "anyshare_bot", "doc_info": fetch_requests}
        res = await self.api_fetch(payload)
        
        if not res or "result" not in res: return
        
        # 3. 分发结果
        # API 返回 result 数组，顺序通常对应 request 顺序，但也可能包含 items 列表
        # 假设 result 是一对一的结构，或者通过 doc_id 匹配
        # 安全起见，构建 {doc_id: [slices]} 的池子，让对象自己去认领
        
        expanded_pool = defaultdict(list)
        for group in res.get("result", []):
            for item in group.get("items", []):
                did = item.get("belong_doc_id") or item.get("doc_id")
                if did:
                    expanded_pool[did].append(item)
                    
        # 让每个对象去池子里拿自己的数据
        for obj in objects:
            if obj.doc_id in expanded_pool:
                obj.add_context(expanded_pool[obj.doc_id])

    async def execute(self, query: str, content: str):
        # 0. 快捷返回
        if content and content != "\"\"": 
            return {"text": [{"content": content, "meta": {}, "retrieve_source_type": "USER_INPUT"}]}
        
        # 1. 召回
        recalled_slices = await self.step1_recall(query)
        
        # 2. 排序
        reranked_slices = await self.step2_rerank(query, recalled_slices)
        
        # 3. 对象化 (Group -> Top N Objects)
        # 这里实现了 "rerank的结果为按照切片最高score排序的8个大对象"
        top_objects = self.step3_build_objects(reranked_slices)
        
        # 4. 补充上下文 (判断doc/wiki就用带上下文补充的方法)
        await self.step4_expand_context(top_objects)
        
        # 5. 组装结果 (各对象调用自己的 construct_result)
        final_data = [obj.construct_result() for obj in top_objects]
        
        print(final_data)
        return {"text": final_data}

# ==========================================
# 主入口
# ==========================================
async def do_retrieval(as_ctx: dict, query: str, content: str):
    try:
        pipeline = RecallPipeline(as_ctx)
        return await pipeline.execute(query, content)
    except Exception as e:
        print(f"[Error] {e}")
        import traceback; traceback.print_exc()
        return {"text": f"[Error] {e}"}


def format_data(data):
    # Load the JSON data
    # with open("/root/kg_bot/retrievers_block_content1.json", "r", encoding="utf-8") as file:
    #     data = json.load(file)
    # Extract doc_name and content into a dictionary
    result = {}
    for item in data["text"]:
        retrieve_source_type = item.get("retrieve_source_type", "")
        if retrieve_source_type == "DOC_LIB":
            doc_name = item["meta"]["doc_name"]
        elif retrieve_source_type == "FAQ":
            doc_name =  item["meta"]["title"][0] if len(item["meta"]["title"]) > 0 else "未知文件名"
        elif retrieve_source_type == "USER_INPUT":
            doc_name = item["meta"]["doc_name"]
        content = item["content"]
        if doc_name in result.keys():
            result[doc_name].append(content.replace(" ",""))
        else:
            result[doc_name] = [] 
            result[doc_name].append(content.replace(" ",""))

    # Print the result
    # for doc_name, content in result.items():
    #     print(f"{doc_name}: {content[:100]}...")  # Display first 100 characters of content

    # If you want to see the full dictionary:
    # print(result)
    return result

# 文档召回
async def retrivers_block_content(query: str) -> ToolResponse:
    """
    文档召回工具函数

    Args:
        query(str): 用户查询
    """
    ctx = {
    "authorization": os.environ["AS_TOKEN"],
    "app_id": "O6UbuyEwaBVOhw5lP7-",
    "doc_info": {
        "doc_dsid": "3",
        "doc_fields": []
    },
    "file_infos": None,
    "user_infos": [
        {
            "user_id": "4a2e1f06-e982-11e5-8c08-dcd2fc061e41",
            "user_name": "夏磊（Lay）"
        }
    ],
    "tool_params": {
        "ad_url": "https://anyshare.aishu.cn:4443",
        "as_url": "https://anyshare.aishu.cn:443",
        "background_doc": "",
        "embedding_name": "embedding_inner_as",
        "embedding_url": "https://anyshare.aishu.cn:4443/v1/embeddings",
        "model_name": "deepseek",
        "rerank_url": "http://reranker:8343/v1/reranker",
        "selected_content": "",
        "template": ""
    }
}   
    result = await do_retrieval(ctx, query, "")
    # is_time_response = parse_fenced_json(full.get("info", {}).get("answer", {}))
    result = remove_duplicate_files_and_sort(result, {})
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"召回结果为：{format_data(result)}",
            ),
        ],
    )

# 本地调试用
if __name__ == "__main__":
    os.environ["AS_TOKEN"] = "ory_at_f1AEPtRucEYcBi8BZN6wWS35FKNPKsIRfOP0m9MoBOA.iTdh71XCrraKyLhSDjMM272oT0XHf5ulO3IG_PiJaa4"
    asyncio.run(retrivers_block_content("anyshare有什么新特性?"))
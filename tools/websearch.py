import requests
import json
import aiohttp
import json
import asyncio
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from abc import ABC, abstractmethod
from collections import defaultdict

from agentscope.message import TextBlock, ToolUseBlock
from agentscope.tool import ToolResponse, Toolkit, execute_python_code
def zhipu_websearch(
    search_query: str,
) -> ToolResponse:
    """
    执行网页搜索，返回结构化结果
    
    Args:
        search_query: 搜索内容，建议不超过70个字符
    Returns:
        搜索结果的JSON字符串
    """
    url = "https://open.bigmodel.cn/api/paas/v4/web_search"
    
    # 构建请求参数
    payload = {
        "search_query": search_query,
        "search_engine": "search_pro",
        "search_intent": True,
        "count": 5,
    }
    
    headers = {
        "Authorization": f"d6bae03ba6184feaa266479993679853.O33ZMcvLwBxNIc8r",
        "Content-Type": "application/json"
    }
    try:
        # 发送请求
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # 检查响应状态
        
        # 解析响应
        result = response.json()
        print(f"搜索结果：{result}")
        return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"搜索结果：{result}",
            ),
        ],
    )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    search_query = "上海天气怎么样"
    result = web_search(search_query)
    print(result)
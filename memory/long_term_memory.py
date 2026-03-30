import os
from agentscope.embedding import DashScopeTextEmbedding
from agentscope.model import DashScopeChatModel
from agentscope.memory import ReMePersonalLongTermMemory, LongTermMemoryBase
# 缓存存储已创建的长期记忆实例
_long_term_memory_cache = {}

def get_long_term_memory(agent_name: str, user_id: str) -> LongTermMemoryBase:
    # 生成缓存键
    cache_key = (agent_name, user_id)
    
    # 检查缓存中是否已有实例
    if cache_key in _long_term_memory_cache:
        return _long_term_memory_cache[cache_key]
    
    # 创建 mem0 长期记忆实例
    long_term_memory = ReMePersonalLongTermMemory(
    agent_name=agent_name,
    user_name=user_id,
    model=DashScopeChatModel(
        model_name="qwen3-max",
        api_key=os.environ.get("DASHSCOPE_API_KEY"),
        stream=False,
    ),
    embedding_model=DashScopeTextEmbedding(
        model_name="text-embedding-v4",
        api_key=os.environ.get("DASHSCOPE_API_KEY"),
        dimensions=1024,
    ),
)
    
    # 将实例存入缓存
    _long_term_memory_cache[cache_key] = long_term_memory
    
    return long_term_memory


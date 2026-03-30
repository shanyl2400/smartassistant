from agentscope.memory import Mem0LongTermMemory
from agentscope.embedding import DashScopeTextEmbedding
from agentscope.model import DashScopeChatModel
from agentscope.memory import ReMePersonalLongTermMemory
# 缓存存储已创建的长期记忆实例
_long_term_memory_cache = {}

def get_long_term_memory(agent_name: str, user_id: str) -> Mem0LongTermMemory:
    # 生成缓存键
    cache_key = (agent_name, user_id)
    
    # 检查缓存中是否已有实例
    if cache_key in _long_term_memory_cache:
        return _long_term_memory_cache[cache_key]
    
    # 创建 mem0 长期记忆实例
    long_term_memory = Mem0LongTermMemory(
        agent_name=agent_name,
        user_name=user_id,
        model=DashScopeChatModel(
            model_name="qwen-max-latest",
            api_key="sk-a6ec71ba516747baba699ec2d81ff1a8",
            stream=False,
        ),
        embedding_model=DashScopeTextEmbedding(
            model_name="text-embedding-v2",
            api_key="sk-a6ec71ba516747baba699ec2d81ff1a8",
        ),
        # on_disk=True,
    )
    
    # 将实例存入缓存
    _long_term_memory_cache[cache_key] = long_term_memory
    
    return long_term_memory



from sqlalchemy.ext.asyncio import create_async_engine
from agentscope.memory import (
    AsyncSQLAlchemyMemory,
)
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# 缓存存储已创建的短期记忆实例
_short_term_memory_cache = {}


async def get_short_term_memory(user_id: str, session_id: str) -> AsyncSQLAlchemyMemory:
    """使用 AsyncSQLAlchemyMemory 在 SQLite 数据库中存储消息的示例。"""
    # 生成缓存键
    cache_key = (user_id, session_id)
    
    # 检查缓存中是否已有实例
    if cache_key in _short_term_memory_cache:
        return _short_term_memory_cache[cache_key]
    
    # 首先创建一个异步 SQLAlchemy 引擎
    engine = create_async_engine("sqlite+aiosqlite:///./short_term_memory.db")

    # 然后使用该引擎创建记忆
    memory = AsyncSQLAlchemyMemory(
        engine_or_session=engine,
        # 可选传入指定user_id和session_id
        user_id=user_id,
        session_id=session_id,
    )
    
    # 将实例存入缓存
    _short_term_memory_cache[cache_key] = memory

    return memory

 # 创建带连接池的异步SQLAlchemy引擎
engine = create_async_engine(
     "sqlite+aiosqlite:///./short_term_memory.db",
     pool_size=10,
     max_overflow=20,
     pool_timeout=30,
 )

 # 创建会话制造器
async_session_marker = async_sessionmaker(
     engine,
     expire_on_commit=False,
     autocommit=False,
     autoflush=False,
 )

async def get_db() -> AsyncGenerator[AsyncSession, None]:
     async with async_session_marker() as session:
         try:
             yield session
             await session.commit()
         except Exception:
             await session.rollback()
             raise
         finally:
             await session.close()

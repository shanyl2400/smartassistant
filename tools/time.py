# Python 示例
import datetime
from pytz import timezone


from agentscope.message import TextBlock, ToolUseBlock
from agentscope.tool import ToolResponse, Toolkit, execute_python_code

# 准备一个自定义工具函数
async def get_current_time() -> ToolResponse:
    """获取当前时间。

    Args:
        
    """
       # 获取UTC时间
    utc_now = datetime.datetime.utcnow()
    # 转换为北京时间 (UTC+8)
    beijing_tz = timezone('Asia/Shanghai')
    beijing_now = utc_now.astimezone(beijing_tz)

    # 格式化为清晰易读的字符串
    current_time_str = beijing_now.strftime("%Y-%m-%d %H:%M:%S %A")
    # 输出示例: "2023-11-09 14:35:22 Thursday"
    
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"当前时间为是：{current_time_str}",
            ),
        ],
    )
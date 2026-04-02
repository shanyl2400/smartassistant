from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


async def append_or_create_file(
    file_name: str,
    content: str,
    encoding: str = "utf-8",
) -> ToolResponse:
    """写文件工具：固定写入当前目录下的 tmp，文件存在则追加，不存在则创建。

    Args:
        file_name (str): 文件名（不允许包含路径）。
        content (str): 要写入的文本内容。
        encoding (str): 文件编码，默认 utf-8。

    Returns:
        ToolResponse: 返回写入结果说明。
    """
    try:
        # 只允许文件名，不允许调用方指定目录路径
        raw_name = Path(file_name)
        if raw_name.name != file_name or raw_name.name in {"", ".", ".."}:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="写文件失败：file_name 只能是文件名，不能包含路径。",
                    ),
                ],
            )

        base_dir = Path.cwd() / "tmp"
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / raw_name.name

        existed = path.exists()
        with path.open("a", encoding=encoding) as f:
            f.write(content)

        action = "追加写入" if existed else "创建并写入"
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"成功{action}文件：{path}",
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"写文件失败：{e}",
                ),
            ],
        )

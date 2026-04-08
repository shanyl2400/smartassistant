# Smart Assistant（知识助手）

基于 [AgentScope](https://github.com/modelscope/agentscope) 与 `agentscope-runtime` 的智能助手服务，通过 FastAPI / Uvicorn 对外提供 Agent 能力（路由、文档问答、写作、翻译、闲聊等）。

## 环境要求

- **Python**：建议 3.10 及以上。
- 操作系统：macOS / Linux / Windows 均可；部分依赖提供平台专属 wheel，若安装失败可尝试升级 pip 或调整 Python 小版本。
- `requirements.txt` **只列出本仓库的直接依赖**；若需要完全可复现环境，可在安装后执行 `pip freeze > requirements.lock.txt` 自行维护锁文件（勿把含本地路径的条目提交进仓库）。

## 克隆与虚拟环境

```bash
cd smartassistant
python3 -m venv .venv
```

### macOS / Linux

```bash
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### Windows（cmd）

```bash
.venv\Scripts\activate.bat
python -m pip install -U pip
pip install -r requirements.txt
```

### Windows（PowerShell）

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

## pip 安装很慢？

依赖多、又要从海外拉 wheel 时，安装会久一些。可以：

1. **换国内 PyPI 镜像（最常见）**  
   单次生效（示例为清华源，在项目根、已激活 venv 时执行）：

   ```bash
   pip install -U pip
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn --prefer-binary
   ```

   也可改用阿里云：`https://mirrors.aliyun.com/pypi/simple`（同样建议加对应 `--trusted-host`）。

2. **`--prefer-binary`**  
   尽量用预编译 wheel，减少本地编译（上例已带上）。

3. **长期默认走镜像**（当前用户全局，不只本项目）：

   ```bash
   pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
   pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
   ```

4. **可选：用 [uv](https://github.com/astral-sh/uv)** 替代 pip（解析与下载通常更快）：  
   `uv pip install -r requirements.txt`，镜像用法见 uv 文档中的 index 配置。

## 环境变量与密钥

运行前需能访问阿里云 DashScope（通义）等模型服务，并视业务配置爱数等相关 Token。项目中会在 `server.py` 里设置例如：

- `DASHSCOPE_API_KEY`：DashScope API Key  
- `AS_TOKEN`：业务侧 Access Token（如检索等服务）

**请勿将真实密钥提交到 Git。** 推荐在 shell 中 `export`、或使用 `.env`（仓库已忽略 `.env`），并在代码中改为读取环境变量而非硬编码。

## 启动服务

确保已激活虚拟环境（或直接使用虚拟环境里的解释器），在项目根目录执行：

```bash
python server.py
```

默认监听 **`0.0.0.0:8090`**。启动后可访问：

- API 文档：<http://127.0.0.1:8090/docs>  

若需使用 `agentscope-runtime` 自带的 npx Web 对话界面，请调用 `agent_app.run(..., web_ui=True)`，与当前默认的 uvicorn 启动方式二选一（见 `server.py` 注释）。

## 不激活 venv 时启动

```bash
.venv/bin/python server.py
```

（Windows 下为 `.venv\Scripts\python.exe server.py`。）

## 说明

- 短期记忆使用本地 SQLite（`short_term_memory.db`），已在 `.gitignore` 中忽略 `*.db`。  
- 开发环境 Session 使用 `fakeredis` 模拟 Redis；生产环境请按 AgentScope / 部署文档替换为真实 Redis。

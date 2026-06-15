# cutr 工艺图纸 Agent

FastAPI 后端 + 静态前端，用于上传 PDF/图片/CAD 图纸，生成图纸图解、气泡图、标注表和工艺流程。

## 云部署目标

- 服务器 IP：`154.201.65.69`
- 域名：`tianxiadiyi.xyz`
- 前端目录：`/var/www/tianxiadiyi`
- 后端目录：`/www/server/cutr/backend`
- 后端监听：`127.0.0.1:8080`
- 对外访问：`https://tianxiadiyi.xyz`
- 对外 API：`https://tianxiadiyi.xyz/api/...`

## 一、服务器准备

```bash
sudo apt update
sudo apt install -y git nginx python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-chi-sim fonts-noto-cjk libgl1 libglib2.0-0
sudo systemctl enable --now nginx
```

## 二、拉取代码

```bash
cd /www/server
git clone <你的 GitHub 仓库地址> cutr
cd /www/server/cutr
```

如果已经拉过：

```bash
cd /www/server/cutr
git pull
```

## 三、创建 Python 环境

```bash
cd /www/server/cutr/backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

## 四、配置环境变量

```bash
cd /www/server/cutr
cp backend/.env.production.example backend/.env
nano backend/.env
```

至少填写：

```bash
APP_ENV=production
DEBUG=false
PUBLIC_API_BASE=https://tianxiadiyi.xyz
PUBLIC_SERVER_IP=154.201.65.69
ALLOWED_ORIGINS=https://tianxiadiyi.xyz,http://tianxiadiyi.xyz,https://154.201.65.69,http://154.201.65.69,http://localhost:8080,http://127.0.0.1:8080
```

大模型密钥可以同时配置多套，互不覆盖。配置页可以切换当前使用的模型档案：

```bash
# OpenAI / GPT 档案
OPENAI_API_KEY=你的OpenAI密钥
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL_NAME=你的OpenAI模型名

# 火山 Ark / 豆包档案，使用 /api/v3/responses
ARK_API_KEY=你的火山Ark密钥
ARK_API_BASE=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL_NAME=doubao-seed-2-0-pro-260215

# 可选：服务启动时默认启用哪个档案：default、gpt55、ark_doubao
AI_ACTIVE_PROFILE=ark_doubao
```

旧的 `AI_API_KEY` / `AI_API_BASE` / `AI_MODEL_NAME` 仍可作为 `default` 档案使用；建议新配置优先使用 `OPENAI_*` 和 `ARK_*`，避免不同供应商密钥互相覆盖。

如果暂时不用 AI OCR：

```bash
OCR_PROVIDER=none
VISION_PROVIDER=none
```

如果希望 OCR/视觉也复用大模型：

```bash
OCR_PROVIDER=ai
VISION_PROVIDER=ai
```

## 五、发布前端静态文件

你的 Nginx `root` 是 `/var/www/tianxiadiyi`，所以把前端文件复制过去：

```bash
sudo mkdir -p /var/www/tianxiadiyi
sudo rsync -av --delete /www/server/cutr/frontend/ /var/www/tianxiadiyi/
sudo chown -R www-data:www-data /var/www/tianxiadiyi
```

前端生产环境会请求相对路径 `/api`，由 Nginx 转发到后端 `127.0.0.1:8080`。

## 六、启动后端 systemd 服务

```bash
cd /www/server/cutr
sudo cp deploy/systemd/cutr.service /etc/systemd/system/cutr.service
sudo systemctl daemon-reload
sudo systemctl enable --now cutr
sudo systemctl status cutr --no-pager
```

检查后端：

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/health
```

## 七、Nginx 配置

你现在的 Nginx 配置已经符合要求：

- `/`：读取 `/var/www/tianxiadiyi/index.html`
- `/api/`：反代到 `http://127.0.0.1:8080/api/`
- `80`：跳转 HTTPS，并保留 ACME 校验路径
- `443`：使用 `/etc/nginx/ssl/tianxiadiyi.pem` 和 `/etc/nginx/ssl/tianxiadiyi.key`

如果需要用仓库样例覆盖：

```bash
sudo cp deploy/nginx/cutr.conf /etc/nginx/conf.d/cutr.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 八、上线检查

```bash
curl https://tianxiadiyi.xyz/api/health
curl https://tianxiadiyi.xyz/api/config/status
```

浏览器访问：

```text
https://tianxiadiyi.xyz
```

## 九、更新代码后的发布流程

```bash
cd /www/server/cutr
git pull
cd backend
./venv/bin/pip install -r requirements.txt
cd ..
sudo rsync -av --delete frontend/ /var/www/tianxiadiyi/
sudo chown -R www-data:www-data /var/www/tianxiadiyi
sudo systemctl restart cutr
sudo systemctl status cutr --no-pager
```

## 十、常用运维命令

查看后端日志：

```bash
sudo journalctl -u cutr -f
```

重启后端：

```bash
sudo systemctl restart cutr
```

检查 Nginx：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 十一、主要接口

生产访问时统一走 `/api` 前缀：

- `GET /api/health`
- `GET /api/config/status`
- `GET /api/agent/tools`：只读、可供模型直接调用的工具清单
- `GET /api/agent/tools/catalog?max_permission=write`：按 category/permission 输出完整工具目录
- `GET /api/agent/manifest`：agent 默认策略、工具分层和推荐开源集成清单
- `POST /api/agent/files`：Agent 对话模式上传附件，返回可供 Agent 使用的服务器文件路径
- `POST /api/agent/runs/readonly-tool`：兼容只读工具执行入口
- `POST /api/agent/runs/tool`：受控工具执行入口，默认只读；生成/写入需要显式 `max_permission`
- `POST /api/agent/runs/auto`：AI Planner 自动选择工具，按 `max_steps` 有限循环执行
- `POST /api/process/generate-from-text`
- `POST /api/process/generate-from-parse`
- `POST /api/process/upload`
- `POST /api/process/upload-batch`
- `POST /api/process/jobs/upload-batch`

后端本机仍保留无 `/api` 前缀的兼容接口，便于本地调试。

### Agent 工具权限

后端工具按权限分层：

- `read_only`：解析、检索、校验、状态查询等只读工具，可作为模型默认工具。
- `generate`：生成中间结果，例如标注归一化、规则工序、最终指导、工艺图计划、Markdown 文本。
- `write`：会落盘或修改案例库的工具，例如保存案例、导出文件、渲染工艺图资产。

`POST /api/agent/runs/tool` 的请求体示例：

```json
{
  "goal": "导出标注",
  "tool_name": "export_annotations",
  "arguments": {
    "explanations": [],
    "export_dir": "/www/server/cutr/backend/generated/jobs/demo/exports"
  },
  "max_permission": "write",
  "human_confirmed": true
}
```

如果工具声明了 `requires_human_confirmation=true`，但请求里没有 `human_confirmed=true`，运行会停在 `waiting_human`，不会实际执行写入或落盘动作。

### AI 自动选工具

原有 `/api/process/...` 主链路仍是固定流程，适合图纸上传后的稳定生产路径。

前端“生成工序”页默认使用固定分析。开启 Agent 模式后，会打开聊天面板，用户可以直接输入自然语言，也可以上传图纸文件和 Agent 交流。

`POST /api/agent/runs/auto` 是新的 agent 入口：后端会先经过感知、记忆、规划、执行、反思、响应六个模块，再把工具清单、目标和上下文交给 AI Planner，让 AI 返回下一步 `tool` 或 `final`，最后由受控 executor 执行。该入口默认 `max_permission=read_only`，最多自动执行 `max_steps` 步。

示例：

```json
{
  "goal": "解析这个图纸并检查是否需要人工复核",
  "input_files": ["/www/server/cutr/backend/uploads/demo.pdf"],
  "max_permission": "read_only",
  "max_steps": 3,
  "initial_context": {
    "file_path": "/www/server/cutr/backend/uploads/demo.pdf"
  }
}
```

如果要允许生成中间结果，把 `max_permission` 设为 `generate`。如果要允许写入工具，必须设为 `write`，且对应工具名必须出现在 `human_confirmed_tools` 中，否则运行会停在 `waiting_human`。

## 十二、注意事项

- `backend/.env` 不进 Git，服务器上自行创建。
- `backend/uploads`、`backend/generated`、`backend/archives`、`backend/knowledge_base` 是运行数据，更新代码时不要删除。
- PDF 多页和多视图会增加 AI 调用次数，可通过 `AGENT_MAX_PDF_PAGES`、`AGENT_MAX_VIEWS_PER_PAGE` 控制。
- DWG 高保真解析依赖 ODA File Converter；当前主链路优先保证 PDF、图片、DXF 文本/渲染。

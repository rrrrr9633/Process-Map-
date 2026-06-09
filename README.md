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
AI_API_KEY=你的模型密钥
APP_ENV=production
DEBUG=false
PUBLIC_API_BASE=https://tianxiadiyi.xyz
PUBLIC_SERVER_IP=154.201.65.69
ALLOWED_ORIGINS=https://tianxiadiyi.xyz,http://tianxiadiyi.xyz,https://154.201.65.69,http://154.201.65.69,http://localhost:8080,http://127.0.0.1:8080
```

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
- `POST /api/process/generate-from-text`
- `POST /api/process/generate-from-parse`
- `POST /api/process/upload`
- `POST /api/process/upload-batch`
- `POST /api/process/jobs/upload-batch`

后端本机仍保留无 `/api` 前缀的兼容接口，便于本地调试。

## 十二、注意事项

- `backend/.env` 不进 Git，服务器上自行创建。
- `backend/uploads`、`backend/generated`、`backend/archives`、`backend/knowledge_base` 是运行数据，更新代码时不要删除。
- PDF 多页和多视图会增加 AI 调用次数，可通过 `AGENT_MAX_PDF_PAGES`、`AGENT_MAX_VIEWS_PER_PAGE` 控制。
- DWG 高保真解析依赖 ODA File Converter；当前主链路优先保证 PDF、图片、DXF 文本/渲染。
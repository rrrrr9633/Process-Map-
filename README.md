## 启动

### 后端服务

```bash
cd backend
# 使用 Python 3.11
C:\Users\86134\AppData\Local\Microsoft\WindowsApps\python3.11.exe -m pip install -r requirements.txt
C:\Users\86134\AppData\Local\Microsoft\WindowsApps\python3.11.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端服务运行在：`http://localhost:8000`

### 前端界面

直接用浏览器打开 `frontend/index.html` 文件，或访问：
```
file:///C:/Users/86134/Desktop/cutr/frontend/index.html
```

前端提供三种使用方式：
- 📝 **文本输入模式**：直接输入图纸文字信息
- 📤 **文件上传模式**：上传 PDF、图片等文件
- 🔍 **解析结果处理**：使用已有的 JSON 解析结果

## 主要接口

- `GET /health`
- `POST /process/generate-from-text`
- `POST /process/generate-from-parse`
- `POST /process/upload`
- `POST /process/archive`

## 示例请求

```json
{
  "text": "曲轴主轴颈、连杆颈需精磨滚压，需进行磁粉探伤、退磁、动平衡，油道需满足清洁度要求，并进行尺寸分组打刻。",
  "mode": "standard_8"
}
```

## 当前边界

- 图片 OCR 和多模态识图暂未接入，只保留入口和人工确认标记。
- DWG/DXF 仅作为输入解析入口预留，不生成 CAD 文件。
- 当前 AI 文本补全以规则模板文本为主，后续可接 DeepSeek 或其他大模型进一步润色。
// API配置
const API_BASE = 'http://localhost:8000';

// 全局状态
let currentData = null;
let currentCaseId = null;
let isGeneratingProcess = false;
let generationProgressTimer = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    mermaid.initialize({ startOnLoad: false, theme: 'default' });
    checkExternalConditionsCheckbox();
    bindFileUploadPreview();
    loadConfigStatus();
});

// Tab切换
function switchTab(tabName, targetElement) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    
    const activeTab = targetElement || document.querySelector(`.tab[data-tab="${tabName}"]`);
    if (activeTab) {
        activeTab.classList.add('active');
    }
    document.getElementById(tabName + '-tab').classList.add('active');
    
    // 加载对应数据
    if (tabName === 'cases') {
        loadCases();
    }
    if (tabName === 'settings') {
        loadConfigStatus();
    }
}

// 输入方式切换
function toggleInputMethod() {
    const method = document.getElementById('input-method').value;
    document.getElementById('text-input-section').style.display = method === 'text' ? 'block' : 'none';
    document.getElementById('file-input-section').style.display = method === 'file' ? 'block' : 'none';
    document.getElementById('json-input-section').style.display = method === 'json' ? 'block' : 'none';
}

// 外部条件复选框
function checkExternalConditionsCheckbox() {
    const checkbox = document.getElementById('use-external-conditions');
    const form = document.getElementById('external-conditions-form');
    if (checkbox) {
        checkbox.addEventListener('change', () => {
            form.style.display = checkbox.checked ? 'block' : 'none';
        });
    }
}

// 文件上传预览
function bindFileUploadPreview() {
    const fileInput = document.getElementById('file-input');
    const fileInfo = document.getElementById('file-info');
    if (!fileInput || !fileInfo) return;

    fileInput.addEventListener('change', () => {
        const files = Array.from(fileInput.files || []);
        if (!files.length) {
            fileInfo.style.display = 'none';
            fileInfo.innerHTML = '';
            return;
        }

        fileInfo.innerHTML = files.map((file, index) => {
            const suffix = getFileSuffix(file.name);
            const supportNote = getUploadSupportNote(suffix);
            return `
                <div style="margin-bottom:8px;">
                    <div><strong>第 ${index + 1} 步图纸：</strong>${escapeHtml(file.name)}</div>
                    <div><strong>大小：</strong>${formatFileSize(file.size)}</div>
                    <div><strong>处理方式：</strong>${supportNote}</div>
                </div>
            `;
        }).join('');
        fileInfo.style.display = 'block';
    });
}

function getFileSuffix(fileName) {
    const index = fileName.lastIndexOf('.');
    return index >= 0 ? fileName.slice(index + 1).toLowerCase() : '';
}

function getUploadSupportNote(suffix) {
    if (suffix === 'pdf') return '后端提取 PDF 文本后生成工序';
    if (['png', 'jpg', 'jpeg', 'webp', 'bmp'].includes(suffix)) return '图片会上传到后端，当前未接入 OCR，结果需要人工确认';
    if (['dwg', 'dxf'].includes(suffix)) return '矢量图纸会上传到后端，当前仅预留 CAD 解析入口';
    return '该格式后端可能不支持';
}

function formatFileSize(size) {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function renderOperationList(title, values) {
    if (!values || values.length === 0) return '';
    const items = values
        .filter(value => value !== null && value !== undefined && String(value).trim())
        .map(value => `<li>${escapeHtml(value)}</li>`)
        .join('');
    if (!items) return '';
    return `
        <div class="worker-guidance-block">
            <strong>${escapeHtml(title)}：</strong>
            <ul>${items}</ul>
        </div>
    `;
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function loadConfigStatus() {
    const apiBaseDisplay = document.getElementById('api-base-display');
    const aiStatus = document.getElementById('ai-status');
    const ocrStatus = document.getElementById('ocr-status');
    const visionStatus = document.getElementById('vision-status');
    const settingsDetail = document.getElementById('settings-detail');

    if (!apiBaseDisplay || !aiStatus || !ocrStatus || !visionStatus || !settingsDetail) return;

    apiBaseDisplay.textContent = API_BASE;
    aiStatus.textContent = '读取中';
    ocrStatus.textContent = '读取中';
    visionStatus.textContent = '读取中';
    settingsDetail.textContent = '正在读取后端配置状态...';

    try {
        const response = await fetch(`${API_BASE}/config/status`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const config = await response.json();

        const ai = config.ai || {};
        const ocr = config.ocr || {};
        const vision = config.vision || {};

        apiBaseDisplay.textContent = config.api_base || API_BASE;
        aiStatus.textContent = ai.configured ? `已配置：${ai.provider || 'custom'} / ${ai.model || '未指定模型'}` : '未配置：缺少 AI_API_KEY';
        ocrStatus.textContent = ocr.configured ? `已配置：${ocr.provider || 'custom'}` : `未启用：${ocr.provider || 'none'}`;
        visionStatus.textContent = vision.configured ? `已配置：${vision.provider || 'custom'}` : `未启用：${vision.provider || 'none'}`;

        const aiBase = ai.api_base || '未配置';
        const timeout = ai.timeout_seconds ? `${ai.timeout_seconds} 秒` : '未配置';
        settingsDetail.innerHTML = `
            <div><strong>AI 接口：</strong>${escapeHtml(aiBase)}</div>
            <div><strong>AI 模型：</strong>${escapeHtml(ai.model || '未配置')}</div>
            <div><strong>AI 超时：</strong>${escapeHtml(timeout)}</div>
            <div><strong>说明：</strong>配置页只读取后端环境变量状态；密钥不会在前端展示。</div>
        `;
    } catch (error) {
        aiStatus.textContent = '状态读取失败';
        ocrStatus.textContent = '状态读取失败';
        visionStatus.textContent = '状态读取失败';
        settingsDetail.textContent = `无法读取 /config/status：${error.message}`;
    }
}

function renderGenerationProgress(stage, detail, startedAt, extraItems = [], activeKey = 'backend') {
    const elapsedSeconds = startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0;
    const items = [
        { key: 'request', label: '前端请求', value: '已准备生成参数并发起请求' },
        { key: 'upload', label: '文件上传', value: '正在把图纸文件发送到后端' },
        { key: 'backend', label: '后端预处理', value: '复用或保存文件，快速生成本地兜底数据' },
        { key: 'ai-prepare', label: 'AI 准备请求', value: '整理图纸图像、兜底方案和模型参数' },
        { key: 'ai-connect', label: 'AI 连接模型', value: '请求已发出，等待模型建立响应或首段内容' },
        { key: 'ai-generate', label: 'AI 生成内容', value: '模型正在生成结构化工序、流程图和确认项' },
        { key: 'ai-timeout', label: 'AI 超时边界', value: '等待模型返回；失败后后端会兜底' },
        { key: 'result', label: '结果返回', value: '等待工序方案、流程图、Agent 链路和人工确认项返回前端' },
        ...extraItems,
    ];
    return `
        <div class="progress-panel">
            <div class="progress-panel-header">
                <strong>${escapeHtml(stage)}</strong>
                <span>已等待 ${elapsedSeconds} 秒</span>
            </div>
            <div class="progress-current"><span class="progress-inline-spinner"></span>${escapeHtml(detail)}</div>
            <div class="progress-steps">
                ${items.map(item => `
                    <div class="progress-step ${item.key === activeKey ? 'active' : ''}">
                        <strong>${item.key === activeKey ? '<span class="progress-step-spinner"></span>' : ''}${escapeHtml(item.label)}</strong>
                        <span>${escapeHtml(item.value)}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function setGenerationProgress(stage, detail, startedAt, extraItems = [], activeKey = 'backend') {
    const loading = document.getElementById('generate-loading');
    if (!loading) return;
    loading.innerHTML = renderGenerationProgress(stage, detail, startedAt, extraItems, activeKey);
    loading.classList.add('active');
}

function stopGenerationProgressTimer() {
    if (generationProgressTimer) {
        clearInterval(generationProgressTimer);
        generationProgressTimer = null;
    }
}

function startGenerationProgressTimer(stage, detail, startedAt, extraItems = [], activeKey = 'backend') {
    stopGenerationProgressTimer();
    setGenerationProgress(stage, detail, startedAt, extraItems, activeKey);
    generationProgressTimer = setInterval(() => {
        setGenerationProgress(stage, detail, startedAt, extraItems, activeKey);
    }, 1000);
}

function getAiWaitStage(elapsedSeconds) {
    if (elapsedSeconds < 8) {
        return {
            stage: 'AI 准备请求',
            detail: '后端正在整理图纸图片、工序兜底方案和模型请求参数。',
            activeKey: 'ai-prepare',
        };
    }
    if (elapsedSeconds < 20) {
        return {
            stage: 'AI 连接模型',
            detail: '后端正在连接 AI 接口并等待模型开始返回内容；如果终端没有 first content，通常卡在网络或模型排队。',
            activeKey: 'ai-connect',
        };
    }
    if (elapsedSeconds < 45) {
        return {
            stage: 'AI 生成结构化方案',
            detail: '模型正在生成图纸理解、工序拆分、流程图和人工确认项；终端会显示 chunk 和字符数增长。',
            activeKey: 'ai-generate',
        };
    }
    return {
        stage: 'AI 等待超时边界',
        detail: 'AI 已等待较久；如果终端没有持续 chunks，优先检查模型接口、网关或超时配置。失败后后端会回退到本地兜底结果。',
        activeKey: 'ai-timeout',
    };
}

function startAiProgressTimer(startedAt, extraItems = []) {
    stopGenerationProgressTimer();
    const render = () => {
        const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
        const stage = getAiWaitStage(elapsedSeconds);
        setGenerationProgress(stage.stage, stage.detail, startedAt, extraItems, stage.activeKey);
    };
    render();
    generationProgressTimer = setInterval(render, 1000);
}

function requestWithUploadProgress(url, formData, startedAt, uploadInfo) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url);
        xhr.upload.onprogress = event => {
            if (!event.lengthComputable) return;
            const percent = Math.round((event.loaded / event.total) * 100);
            startGenerationProgressTimer(
                '正在上传图纸文件',
                `文件正在传输到后端：${percent}%（${formatFileSize(event.loaded)} / ${formatFileSize(event.total)}）`,
                startedAt,
                [
                    { key: 'upload-files', label: '上传文件', value: uploadInfo.name },
                    { key: 'upload-size', label: '总大小', value: formatFileSize(uploadInfo.size) },
                ],
                'upload',
            );
        };
        xhr.upload.onload = () => {
            startAiProgressTimer(
                startedAt,
                [
                    { key: 'upload-files', label: '上传文件', value: uploadInfo.name },
                    { key: 'upload-size', label: '总大小', value: formatFileSize(uploadInfo.size) },
                ],
            );
        };
        xhr.onload = () => {
            resolve({
                ok: xhr.status >= 200 && xhr.status < 300,
                status: xhr.status,
                text: async () => xhr.responseText,
                json: async () => JSON.parse(xhr.responseText),
            });
        };
        xhr.onerror = () => reject(new Error('网络错误：文件上传或后端连接失败'));
        xhr.ontimeout = () => reject(new Error('请求超时：后端处理时间过长'));
        xhr.send(formData);
    });
}

function resetGenerateButton(loading, generateButton) {
    stopGenerationProgressTimer();
    loading.classList.remove('active');
    isGeneratingProcess = false;
    if (generateButton) {
        generateButton.disabled = false;
        generateButton.textContent = '生成工序方案';
    }
}

// 生成工序
async function generateProcess() {
    if (isGeneratingProcess) {
        return;
    }
    isGeneratingProcess = true;

    const method = document.getElementById('input-method').value;
    const mode = document.getElementById('process-mode').value;
    const useAI = document.getElementById('use-ai-enhancement').checked;
    const useExternalConditions = document.getElementById('use-external-conditions').checked;
    
    const loading = document.getElementById('generate-loading');
    const result = document.getElementById('generate-result');
    const generateButton = document.getElementById('generate-process-btn');
    const startedAt = Date.now();
    
    result.classList.remove('active');
    startGenerationProgressTimer(
        '准备生成工序',
        `输入方式：${method}；工序模式：${mode}；AI增强：${useAI ? '开启' : '关闭'}`,
        startedAt,
        [],
        'request',
    );
    if (generateButton) {
        generateButton.disabled = true;
        generateButton.textContent = '生成中...';
    }
    
    let requestData = {
        mode,
        use_ai_enhancement: useAI
    };
    
    // 外部条件
    if (useExternalConditions) {
        try {
            const externalConditionsText = document.getElementById('external-conditions-input').value.trim();
            if (externalConditionsText) {
                requestData.external_conditions = JSON.parse(externalConditionsText);
            }
        } catch (e) {
            resetGenerateButton(loading, generateButton);
            alert('外部条件 JSON 格式错误：' + e.message);
            return;
        }
    }
    
    let keepProgressVisible = false;
    try {
        let response;
        let uploadInfo = null;
        
        if (method === 'text') {
            const text = document.getElementById('text-input').value.trim();
            if (!text) {
                resetGenerateButton(loading, generateButton);
                alert('请输入图纸信息');
                return;
            }
            requestData.text = text;
            startGenerationProgressTimer(
                '后端接口已调用',
                '正在发送文本到 /process/generate-from-text，后端将解析文字、生成工序并尝试 AI 分析。',
                startedAt,
                [],
                'backend',
            );
            response = await fetch(`${API_BASE}/process/generate-from-text`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });
        } else if (method === 'file') {
            const fileInput = document.getElementById('file-input');
            if (!fileInput.files.length) {
                resetGenerateButton(loading, generateButton);
                alert('请选择文件');
                return;
            }

            const files = Array.from(fileInput.files);
            const supportedSuffixes = ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'dwg', 'dxf'];
            const unsupportedFile = files.find(file => !supportedSuffixes.includes(getFileSuffix(file.name)));
            if (unsupportedFile) {
                resetGenerateButton(loading, generateButton);
                alert(`暂不支持 ${unsupportedFile.name} 的文件格式，请上传 PDF、图片或 DWG/DXF 文件`);
                return;
            }

            const formData = new FormData();
            files.forEach(file => formData.append(files.length > 1 ? 'files' : 'file', file));
            uploadInfo = {
                name: files.map(file => file.name).join('、'),
                size: files.reduce((total, file) => total + file.size, 0),
                suffix: files.length > 1 ? 'batch' : getFileSuffix(files[0].name),
                supportNote: files.length > 1
                    ? `批量上传 ${files.length} 个文件，按选择顺序作为分步流程图合并分析`
                    : getUploadSupportNote(getFileSuffix(files[0].name))
            };
            const endpoint = files.length > 1 ? '/process/upload-batch' : '/process/upload';
            startGenerationProgressTimer(
                '后端接口已调用',
                `正在发送 ${files.length} 个文件到 ${endpoint}。上传完成后会复用或保存文件，并进入 AI 分析等待模型返回。`,
                startedAt,
                [
                    { label: '上传文件', value: files.map(file => file.name).join('、') },
                    { label: '总大小', value: formatFileSize(uploadInfo.size) },
                ],
                'upload',
            );
            response = await requestWithUploadProgress(
                `${API_BASE}${endpoint}?mode=${mode}&use_ai_enhancement=${useAI}`,
                formData,
                startedAt,
                uploadInfo,
            );
        } else if (method === 'json') {
            const jsonText = document.getElementById('json-input').value.trim();
            if (!jsonText) {
                resetGenerateButton(loading, generateButton);
                alert('请输入 JSON 解析结果');
                return;
            }
            try {
                requestData.parse_result = JSON.parse(jsonText);
            } catch (e) {
                resetGenerateButton(loading, generateButton);
                alert('JSON 格式错误：' + e.message);
                return;
            }
            startGenerationProgressTimer(
                '后端接口已调用',
                '正在发送结构化解析结果到 /process/generate-from-parse。后端将基于 JSON 生成工序、校验流程并返回流程图。',
                startedAt,
                [],
                'backend',
            );
            response = await fetch(`${API_BASE}/process/generate-from-parse`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });
        }
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }
        
        setGenerationProgress(
            '后端已响应，正在读取结果',
            '接口已经返回，前端正在解析工序方案、Agent 链路、流程图和人工确认项。',
            startedAt,
            [],
            'result',
        );
        const data = await response.json();
        if (uploadInfo) {
            data.upload_info = uploadInfo;
        }
        currentData = data;
        setGenerationProgress(
            '生成完成，正在渲染结果',
            `后端返回 ${data.process_plan?.operations?.length || 0} 道工序；AI：${data.agent_trace?.used_ai ? '已使用' : '未使用/已兜底'}。`,
            startedAt,
            [],
            'result',
        );
        displayResult(data);
        
    } catch (error) {
        keepProgressVisible = true;
        stopGenerationProgressTimer();
        setGenerationProgress(
            '生成失败',
            error.message,
            startedAt,
            [
                { key: 'suggestion', label: '处理建议', value: '查看后端终端日志和页面人工确认项；如果是 AI 401/502，优先检查密钥、模型名、接口地址和后端是否重启。' },
            ],
            'result',
        );
        alert('生成失败：' + error.message);
        console.error(error);
    } finally {
        if (keepProgressVisible) {
            stopGenerationProgressTimer();
            isGeneratingProcess = false;
            if (generateButton) {
                generateButton.disabled = false;
                generateButton.textContent = '生成工序方案';
            }
        } else {
            resetGenerateButton(loading, generateButton);
        }
    }
}

function renderReadableFlow(operations = []) {
    if (!operations.length) {
        return '<div class="info">暂无可展示的工序流程</div>';
    }

    return `
        <div class="readable-flow">
            ${operations.map((op, index) => `
                <div class="flow-step-card">
                    <div class="flow-step-index">${index + 1}</div>
                    <div class="flow-step-body">
                        <div class="flow-step-header">
                            <span class="operation-no">${escapeHtml(op.operation_no || String(index + 1))}</span>
                            <strong>${escapeHtml(op.operation_name || '未命名工序')}</strong>
                        </div>
                        <p>${escapeHtml(op.content || '暂无工序说明')}</p>
                        <div class="flow-step-meta">
                            ${(op.targets || []).slice(0, 3).map(item => `<span>对象：${escapeHtml(item)}</span>`).join('')}
                            ${(op.equipment || []).slice(0, 2).map(item => `<span>设备：${escapeHtml(item)}</span>`).join('')}
                            ${(op.inspection_items || []).slice(0, 2).map(item => `<span>检验：${escapeHtml(item)}</span>`).join('')}
                        </div>
                        ${op.control_points && op.control_points.length ? `
                            <div class="flow-step-points">
                                <strong>关键控制：</strong>${op.control_points.slice(0, 3).map(escapeHtml).join('；')}
                            </div>
                        ` : ''}
                    </div>
                </div>
                ${index < operations.length - 1 ? '<div class="flow-step-arrow">↓</div>' : ''}
            `).join('')}
        </div>
    `;
}

// 显示结果
function displayResult(data) {
    const container = document.getElementById('generate-result');
    let html = '';
    
    // 相似案例推荐
    if (data.similar_cases && data.similar_cases.length > 0) {
        html += '<div class="result-section">';
        html += '<h3>相似案例推荐</h3>';
        data.similar_cases.forEach(c => {
            html += `<div class="info">案例：${c.case_name} (质量：${c.quality || '未评级'})</div>`;
        });
        html += '</div>';
    }
    
    // AI建议
    if (data.ai_suggestions && data.ai_suggestions.length > 0) {
        html += '<div class="result-section">';
        html += '<h3>AI 建议</h3>';
        data.ai_suggestions.forEach(s => {
            html += `<div class="info">${s}</div>`;
        });
        html += '</div>';
    }
    
    // Agent执行链路
    if (data.agent_trace) {
        html += '<div class="result-section">';
        html += '<h3>Agent 识别链路</h3>';
        html += '<div class="part-info-grid">';
        html += `<p><strong>AI调用：</strong>${data.agent_trace.used_ai ? '已使用' : '未使用'}</p>`;
        html += `<p><strong>视觉输入：</strong>${data.agent_trace.used_vision ? '已使用图像' : '未使用图像'}</p>`;
        html += `<p><strong>兜底方案：</strong>${data.agent_trace.fallback_used ? '已启用' : '未启用'}</p>`;
        html += '</div>';
        if (data.agent_trace.stages && data.agent_trace.stages.length > 0) {
            html += '<h4>执行阶段：</h4>';
            data.agent_trace.stages.forEach(stage => {
                html += `<div class="info">${escapeHtml(stage)}</div>`;
            });
        }
        if (data.agent_trace.questions && data.agent_trace.questions.length > 0) {
            html += '<h4>人工确认项：</h4>';
            data.agent_trace.questions.forEach(item => {
                const className = item.severity === 'critical' ? 'critical' : item.severity === 'warning' ? 'warning' : 'info';
                html += `<div class="${className}"><strong>${escapeHtml(item.field)}：</strong>${escapeHtml(item.question)}<br><small>${escapeHtml(item.reason || '')}</small></div>`;
            });
        }
        html += '</div>';
    }

    // 标注识别结果
    const annotationResult = data.annotation_result || {};
    const annotations = annotationResult.annotations || [];
    const exportRows = annotationResult.export_rows || [];
    if (annotations.length > 0 || exportRows.length > 0) {
        html += '<div class="result-section">';
        html += '<h3>图纸标注识别转化</h3>';
        html += '<div class="part-info-grid">';
        html += `<p><strong>识别标注：</strong>${annotations.length} 项</p>`;
        html += `<p><strong>待审核：</strong>${annotationResult.review_required_count || 0} 项</p>`;
        html += `<p><strong>气泡图：</strong>${annotationResult.bubble_diagram_available ? '可生成' : '待完善'}</p>`;
        html += '</div>';

        if (annotations.length > 0) {
            html += '<h4>标注区域与内容：</h4>';
            html += '<div style="overflow-x:auto;"><table style="width:100%; border-collapse:collapse; font-size:13px;">';
            html += '<thead><tr><th>编号</th><th>页码</th><th>类型</th><th>原始内容</th><th>参数</th><th>值</th><th>审核</th><th>置信度</th></tr></thead><tbody>';
            annotations.forEach(item => {
                const region = item.region || {};
                html += '<tr>';
                html += `<td>${escapeHtml(item.annotation_id || '')}</td>`;
                html += `<td>${escapeHtml(region.page || '')}</td>`;
                html += `<td>${escapeHtml(item.semantic_type || 'unknown')}</td>`;
                html += `<td>${escapeHtml(item.raw_text || '')}</td>`;
                html += `<td>${escapeHtml(item.parameter_name || item.normalized_text || '')}</td>`;
                html += `<td>${escapeHtml(item.parameter_value || '')}</td>`;
                html += `<td>${escapeHtml(item.review_status || 'pending')}</td>`;
                html += `<td>${escapeHtml(item.confidence ?? '')}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table></div>';
        }

        if (exportRows.length > 0) {
            html += '<h4>识别列表导出预览：</h4>';
            html += '<div style="overflow-x:auto;"><table style="width:100%; border-collapse:collapse; font-size:13px;">';
            html += '<thead><tr><th>#</th><th>标注</th><th>参数名</th><th>参数值</th><th>上限</th><th>下限</th><th>单位</th><th>状态</th></tr></thead><tbody>';
            exportRows.forEach(row => {
                html += '<tr>';
                html += `<td>${escapeHtml(row.row_no || '')}</td>`;
                html += `<td>${escapeHtml(row.annotation_id || '')}</td>`;
                html += `<td>${escapeHtml(row.parameter_name || '')}</td>`;
                html += `<td>${escapeHtml(row.parameter_value || '')}</td>`;
                html += `<td>${escapeHtml(row.upper_limit || '')}</td>`;
                html += `<td>${escapeHtml(row.lower_limit || '')}</td>`;
                html += `<td>${escapeHtml(row.unit || '')}</td>`;
                html += `<td>${escapeHtml(row.review_status || '')}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table></div>';
        }
        html += '</div>';
    }

    // 图纸解析结果
    html += '<div class="result-section">';
    html += '<h3>图纸解析结果</h3>';
    
    if (data.upload_info) {
        html += '<div class="upload-summary">';
        html += `<p><strong>上传文件：</strong>${escapeHtml(data.upload_info.name)}</p>`;
        html += `<p><strong>文件大小：</strong>${formatFileSize(data.upload_info.size)}</p>`;
        html += `<p><strong>后端处理：</strong>${escapeHtml(data.upload_info.supportNote)}</p>`;
        html += '</div>';
    }
    
    if (data.parse_result.part) {
        const part = data.parse_result.part;
        html += '<div class="part-info-grid">';
        if (part.part_name) html += `<p><strong>零件名称：</strong>${part.part_name}</p>`;
        if (part.drawing_no) html += `<p><strong>图号：</strong>${part.drawing_no}</p>`;
        if (part.material) html += `<p><strong>材料：</strong>${part.material}</p>`;
        if (part.blank_type) html += `<p><strong>毛坯类型：</strong>${part.blank_type}</p>`;
        if (part.heat_treatment) html += `<p><strong>热处理：</strong>${part.heat_treatment}</p>`;
        html += '</div>';
    }
    
    if (data.parse_result.features && data.parse_result.features.length > 0) {
        html += '<h4>识别特征：</h4>';
        data.parse_result.features.forEach(f => {
            html += `<span class="badge" style="background:#4caf50; margin:3px;">${f.name}</span>`;
        });
    }
    
    if (data.parse_result.risk_flags && data.parse_result.risk_flags.length > 0) {
        html += '<h4>风险提示：</h4>';
        data.parse_result.risk_flags.forEach(flag => {
            const className = flag.severity === 'critical' ? 'critical' : flag.severity === 'warning' ? 'warning' : 'info';
            html += `<div class="${className}"><strong>${escapeHtml(flag.field)}:</strong> ${escapeHtml(flag.message)}</div>`;
        });
    }

    if (data.parse_result.raw_text) {
        html += '<h4>解析文本：</h4>';
        html += `<pre class="raw-text-preview">${escapeHtml(data.parse_result.raw_text)}</pre>`;
    }
    
    html += '</div>';
    
    // 工序方案
    html += '<div class="result-section">';
    html += `<h3>${data.process_plan.title}</h3>`;
    html += `<p><strong>模式：</strong> ${data.process_plan.mode === 'standard_8' ? '标准8道工序' : '详细10道工序'}</p>`;
    
    if (data.process_plan.validation_issues && data.process_plan.validation_issues.length > 0) {
        html += '<h4>验证问题：</h4>';
        data.process_plan.validation_issues.forEach(issue => {
            const className = issue.severity === 'critical' ? 'critical' : issue.severity === 'warning' ? 'warning' : 'info';
            html += `<div class="${className}"><strong>[${issue.code}]</strong> ${issue.message}</div>`;
        });
    }
    
    html += '<h4>工序列表：</h4>';
    data.process_plan.operations.forEach(op => {
        html += `<div class="operation-card">`;
        html += `<div class="operation-header">`;
        html += `<span class="operation-no">${op.operation_no}</span>`;
        html += `<span class="operation-name">${op.operation_name}</span>`;
        if (op.mandatory) html += `<span class="badge mandatory">必须</span>`;
        if (op.requires_manual_review) html += `<span class="badge review">需审核</span>`;
        html += `<span class="operation-type">${op.operation_type}</span>`;
        html += `</div>`;
        html += `<p style="color:#555; margin-bottom:10px;">${escapeHtml(op.content)}</p>`;
        
        if (op.targets && op.targets.length > 0) {
            html += `<p><strong>加工对象：</strong>${op.targets.map(escapeHtml).join(', ')}</p>`;
        }
        html += '<div class="worker-guidance">';
        html += renderOperationList('操作步骤', op.worker_steps);
        html += renderOperationList('物料/半成品', op.materials);
        html += renderOperationList('工装刀量具', op.tools);
        html += renderOperationList('准备要求', op.setup_requirements);
        html += renderOperationList('安全注意', op.safety_points);
        html += renderOperationList('质量放行', op.quality_gates);
        html += renderOperationList('交接要求', op.handoff_requirements);
        html += '</div>';
        if (op.control_points && op.control_points.length > 0) {
            html += `<p><strong>控制要点：</strong>${op.control_points.map(escapeHtml).join('；')}</p>`;
        }
        if (op.equipment && op.equipment.length > 0) {
            html += `<p><strong>设备：</strong>${op.equipment.map(escapeHtml).join(', ')}</p>`;
        }
        if (op.inspection_items && op.inspection_items.length > 0) {
            html += `<p><strong>检验项：</strong>${op.inspection_items.map(escapeHtml).join('；')}</p>`;
        }
        if (op.drawing_basis && op.drawing_basis.length > 0) {
            html += renderOperationList('图纸依据', op.drawing_basis);
        }
        html += `</div>`;
    });
    
    html += '</div>';
    
    // 可读流程
    html += '<div class="result-section">';
    html += `<h3>${escapeHtml(data.flow.title || '流程图')}</h3>`;
    html += '<p class="flow-readable-hint">默认展示按工序顺序展开的人话版流程；原始 Mermaid 技术图保留在下方，可横向滚动查看。</p>';
    html += renderReadableFlow(data.process_plan.operations || []);
    html += '<details class="technical-flow-details">';
    html += '<summary>查看原始技术流程图</summary>';
    html += '<div class="mermaid-scroll">';
    html += `<div class="mermaid-diagram" id="mermaid-diagram">${data.flow.mermaid}</div>`;
    html += '</div>';
    html += '</details>';
    html += '</div>';
    
    // 操作按钮
    html += '<div class="result-section">';
    html += '<button class="btn btn-primary" onclick="editCurrentPlan()">编辑工序</button>';
    html += '<button class="btn btn-secondary" onclick="saveAsCase()">保存为案例</button>';
    html += '<button class="btn" onclick="downloadMarkdown()">下载 Markdown</button>';
    html += '</div>';
    
    container.innerHTML = html;
    container.classList.add('active');
    
    // 渲染流程图
    setTimeout(() => {
        const element = document.getElementById('mermaid-diagram');
        if (element) {
            mermaid.render('mermaid-svg-' + Date.now(), data.flow.mermaid).then(result => {
                element.innerHTML = result.svg;
            }).catch(err => {
                console.error('Mermaid rendering error:', err);
                element.innerHTML = '<pre>' + data.flow.mermaid + '</pre>';
            });
        }
    }, 100);
}

// 编辑当前方案
function editCurrentPlan() {
    if (!currentData) {
        alert('没有可编辑的方案');
        return;
    }
    
    // 切换到编辑标签页
    document.querySelectorAll('.tab')[1].click();
    
    // 加载编辑器
    const workspace = document.getElementById('edit-workspace');
    let html = '<div class="edit-container">';
    html += '<h4>编辑工序（点击工序卡片进行修改）</h4>';
    
    currentData.process_plan.operations.forEach((op, index) => {
        html += `<div class="operation-card editable" onclick="editOperation(${index})">`;
        html += `<div class="operation-header">`;
        html += `<span class="operation-no">${op.operation_no}</span>`;
        html += `<span class="operation-name">${op.operation_name}</span>`;
        html += `</div>`;
        html += `<p>${op.content}</p>`;
        html += `</div>`;
    });
    
    html += '<div style="margin-top:20px;">';
    html += '<button class="btn btn-primary" onclick="saveEditedPlan()">保存修改</button>';
    html += '<button class="btn btn-secondary" onclick="cancelEdit()">取消</button>';
    html += '</div>';
    html += '</div>';
    
    workspace.innerHTML = html;
}

// 编辑单个工序
function editOperation(index) {
    const op = currentData.process_plan.operations[index];
    const newName = prompt('工序名称：', op.operation_name);
    if (newName !== null && newName.trim()) {
        op.operation_name = newName.trim();
        editCurrentPlan(); // 刷新显示
    }
}

// 保存编辑后的方案
async function saveEditedPlan() {
    if (!currentData) return;
    
    try {
        const response = await fetch(`${API_BASE}/process/confirm-edited`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                process_plan: currentData.process_plan,
                archive: false,
                editor_name: '用户',
                edit_notes: '人工编辑'
            })
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        alert('保存成功！');
    } catch (error) {
        alert('保存失败：' + error.message);
    }
}

// 取消编辑
function cancelEdit() {
    document.getElementById('edit-workspace').innerHTML = '<p>加载生成的工序后，可以在这里进行编辑</p>';
}

// 保存为案例
async function saveAsCase() {
    if (!currentData) {
        alert('没有可保存的数据');
        return;
    }
    
    const caseName = prompt('请输入案例名称：');
    if (!caseName) return;
    
    const caseData = {
        case: {
            case_id: 'case_' + Date.now(),
            case_name: caseName,
            drawing_parse_result: currentData.parse_result,
            process_plan: currentData.process_plan,
            external_conditions: null,
            human_edits: [],
            ai_errors: [],
            status: 'draft',
            quality: null,
            tags: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString()
        }
    };
    
    try {
        const response = await fetch(`${API_BASE}/cases/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(caseData)
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const result = await response.json();
        currentCaseId = result.case_id;
        alert('案例保存成功！案例ID：' + result.case_id);
    } catch (error) {
        alert('保存失败：' + error.message);
        console.error(error);
    }
}

// 加载案例列表
async function loadCases() {
    const status = document.getElementById('case-status-filter').value;
    const quality = document.getElementById('case-quality-filter').value;
    
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (quality) params.append('quality', quality);
    params.append('limit', '50');
    
    try {
        const response = await fetch(`${API_BASE}/cases/list?${params}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const cases = await response.json();
        displayCases(cases);
    } catch (error) {
        document.getElementById('cases-list').innerHTML = `<div class="warning">加载失败：${error.message}</div>`;
    }
}

// 显示案例列表
function displayCases(cases) {
    const container = document.getElementById('cases-list');
    
    if (cases.length === 0) {
        container.innerHTML = '<div class="info">暂无案例</div>';
        return;
    }
    
    let html = '';
    cases.forEach(c => {
        html += `<div class="case-item" onclick="loadCase('${c.case_id}')">`;
        html += `<div class="case-header">`;
        html += `<span class="case-title">${c.case_name}</span>`;
        html += `<span class="case-status ${c.status}">${c.status}</span>`;
        html += `</div>`;
        html += `<p style="font-size:14px; color:#666;">创建于：${new Date(c.created_at).toLocaleString()}</p>`;
        if (c.tags && c.tags.length > 0) {
            html += `<p style="margin-top:5px;">`;
            c.tags.forEach(tag => {
                html += `<span class="badge" style="background:#999;">${tag}</span>`;
            });
            html += `</p>`;
        }
        html += `</div>`;
    });
    
    container.innerHTML = html;
}

// 加载单个案例
async function loadCase(caseId) {
    try {
        const response = await fetch(`${API_BASE}/cases/${caseId}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const caseData = await response.json();
        currentData = {
            parse_result: caseData.drawing_parse_result,
            process_plan: caseData.process_plan,
            flow: null // TODO: 重新生成流程图
        };
        currentCaseId = caseId;
        
        // 切换到生成标签页并显示
        document.querySelectorAll('.tab')[0].click();
        alert('案例已加载！');
    } catch (error) {
        alert('加载案例失败：' + error.message);
    }
}

// 下载Markdown
async function downloadMarkdown() {
    if (!currentData) {
        alert('没有可下载的数据');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/process/confirm-edited`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                process_plan: currentData.process_plan,
                archive: false
            })
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const result = await response.json();
        const blob = new Blob([result.markdown], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `工序方案_${new Date().toISOString().slice(0, 10)}.md`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (error) {
        alert('下载失败：' + error.message);
    }
}

// 清空表单
function clearForm() {
    document.getElementById('text-input').value = '';
    document.getElementById('json-input').value = '';
    document.getElementById('file-input').value = '';
    document.getElementById('external-conditions-input').value = '';
    const fileInfo = document.getElementById('file-info');
    if (fileInfo) {
        fileInfo.style.display = 'none';
        fileInfo.innerHTML = '';
    }
    document.getElementById('generate-result').classList.remove('active');
}

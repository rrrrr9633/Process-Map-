const DEPLOYED_API_BASE = '/api';
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8080/api'
    : DEPLOYED_API_BASE;

const MIN_PROGRESS_STAGE_VISIBLE_MS = 4000;

// 全局状态
let currentData = null;
let currentCaseId = null;
let isGeneratingProcess = false;
let generationProgressTimer = null;
let generationProgressSnapshot = {
    extraItems: [],
    activeKey: 'request',
    visibleStage: '',
    visibleDetail: '',
    visibleActiveKey: 'request',
    visibleSince: 0,
};
let lastJob = null;
let boundCaseSourceFiles = null;
let boundCaseDisplayNames = [];
let caseAnnotationPollTimer = null;

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
        clearBoundCaseSourceFiles();
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
    if (suffix === 'pdf') return 'PDF 将作为快速工序生成输入；精细图解和标注仅在案例后台运行';
    if (['png', 'jpg', 'jpeg', 'webp', 'bmp'].includes(suffix)) return '图片将作为快速工序生成输入；精细图解和标注仅在案例后台运行';
    if (['dwg', 'dxf'].includes(suffix)) return 'CAD 将尝试提取可用内容参与快速工序生成';
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


function clearBoundCaseSourceFiles() {
    boundCaseSourceFiles = null;
    boundCaseDisplayNames = [];
    updateBoundCaseFilesHint();
}

function updateBoundCaseFilesHint() {
    const hint = document.getElementById('case-bound-files-hint');
    if (!hint) return;
    if (boundCaseSourceFiles?.length) {
        const names = boundCaseDisplayNames.length
            ? boundCaseDisplayNames.join('、')
            : boundCaseSourceFiles.join('、');
        hint.innerHTML = `<div class="info">案例图纸已绑定：<strong>${escapeHtml(names)}</strong>。再次生成将直接复用服务器 uploads 中已有文件，不走浏览器重传。</div>`;
        hint.style.display = 'block';
    } else {
        hint.innerHTML = '';
        hint.style.display = 'none';
    }
}

function collectCaseSourceFilesFromData(data) {
    const files = [];
    const job = data?.process_job;
    if (job?.files?.length) {
        job.files.forEach((filePath, index) => {
            const stored = String(filePath).split(/[\\/]/).pop();
            const original = job.explanations?.[index]?.file_name || stored;
            if (stored) files.push({ stored_name: stored, original_name: original });
        });
    }
    return files;
}

async function startJobFromStoredFiles(storedNames, mode, targetOperationCount, startedAt, uploadInfo) {
    const response = await fetch(`${API_BASE}/process/jobs/from-stored`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stored_names: storedNames, mode, target_operation_count: targetOperationCount }),
    });
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errorText}`);
    }
    const job = await response.json();
    setGenerationProgress(
        '已复用 uploads 图纸，任务处理中',
        `任务 ${job.job_id} 已创建，跳过了浏览器重复上传。`,
        startedAt,
        [
            { key: 'job-id', label: '任务 ID', value: job.job_id },
            { key: 'upload-files', label: '图纸文件', value: uploadInfo.name },
        ],
        'backend',
    );
    return pollProcessJob(job.job_id, startedAt, uploadInfo);
}


function getGenerationProgressItems(extraItems = []) {
    const baseItems = [
        { key: 'request', label: '前端请求', value: '已准备生成参数并发起请求' },
        { key: 'upload', label: '文件上传', value: '正在把图纸文件发送到后端' },
        { key: 'backend', label: '等待后端创建任务', value: '文件已上传，等待后端返回任务 ID' },
        { key: 'uploaded', label: '任务已创建', value: '后端已接收文件并创建任务' },
        { key: 'flow_generating', label: '快速工序生成', value: '后端正在快速生成工序方案' },
        { key: 'failed', label: '失败处理', value: '后端任务失败后停留在当前页并展示失败原因' },
        { key: 'completed', label: '结果返回', value: '后端任务完成并返回工序方案' },
    ];
    const merged = new Map(baseItems.map(item => [item.key, item]));
    for (const item of [...generationProgressSnapshot.extraItems, ...extraItems]) {
        if (!item || !item.key) continue;
        merged.set(item.key, item);
    }
    generationProgressSnapshot.extraItems = Array.from(merged.values()).filter(item => !baseItems.some(base => base.key === item.key));
    return Array.from(merged.values());
}

function renderGenerationProgress(stage, detail, startedAt, extraItems = [], activeKey = 'backend') {
    const elapsedSeconds = startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0;
    const items = getGenerationProgressItems(extraItems);
    return `
        <div class="progress-panel">
            <div class="progress-panel-header">
                <strong data-progress-stage>${escapeHtml(stage)}</strong>
                <span data-progress-elapsed>已等待 ${elapsedSeconds} 秒</span>
            </div>
            <div class="progress-current"><span data-progress-detail>${escapeHtml(detail)}</span></div>
            <div class="progress-steps">
                ${items.map(item => `
                    <div class="progress-step ${item.key === activeKey ? 'active' : ''}" data-progress-key="${escapeHtml(item.key)}">
                        <strong>${item.key === activeKey ? '<span class="progress-step-spinner"></span>' : ''}${escapeHtml(item.label)}</strong>
                        <span>${escapeHtml(item.value)}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function renderGenerationFailure(stage, detail, startedAt, extraItems = []) {
    const elapsedSeconds = startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0;
    const items = extraItems.filter(item => item && item.key);
    return `
        <div class="progress-panel progress-panel-failed">
            <div class="progress-panel-header">
                <strong>${escapeHtml(stage)}</strong>
                <span>已等待 ${elapsedSeconds} 秒</span>
            </div>
            <div class="critical"><strong>失败原因：</strong>${escapeHtml(detail)}</div>
            <div class="progress-steps">
                ${items.map(item => `
                    <div class="progress-step failed" data-progress-key="${escapeHtml(item.key)}">
                        <strong>${escapeHtml(item.label)}</strong>
                        <span>${escapeHtml(item.value)}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function showGenerationFailure(stage, detail, startedAt, extraItems = []) {
    const loading = document.getElementById('generate-loading');
    if (!loading) return;
    generationProgressSnapshot = {
        extraItems: [],
        activeKey: 'failed',
        visibleStage: stage,
        visibleDetail: detail,
        visibleActiveKey: 'failed',
        visibleSince: Date.now(),
    };
    loading.innerHTML = renderGenerationFailure(stage, detail, startedAt, extraItems);
    loading.classList.add('active');
}

function getProgressRank(activeKey) {
    const orderedKeys = [
        'request',
        'upload',
        'backend',
        'queued',
        'created',
        'uploading',
        'uploaded',
        'flow_generating',
        'failed',
        'completed',
        'result',
    ];
    const index = orderedKeys.indexOf(activeKey);
    return index >= 0 ? index : orderedKeys.indexOf('uploaded');
}

function stabilizeProgressActiveKey(activeKey) {
    const currentKey = generationProgressSnapshot.activeKey || 'request';
    if (getProgressRank(activeKey) < getProgressRank(currentKey)) {
        return currentKey;
    }
    generationProgressSnapshot.activeKey = activeKey;
    return activeKey;
}

function getVisibleProgressState(stage, detail, activeKey) {
    const now = Date.now();
    const current = generationProgressSnapshot;
    const hasVisibleState = current.visibleStage && current.visibleDetail;
    const isSameState = current.visibleStage === stage
        && current.visibleDetail === detail
        && current.visibleActiveKey === activeKey;
    const canSwitch = !hasVisibleState
        || isSameState
        || now - (current.visibleSince || 0) >= MIN_PROGRESS_STAGE_VISIBLE_MS
        || activeKey === 'failed'
        || activeKey === 'result';

    if (canSwitch) {
        current.visibleStage = stage;
        current.visibleDetail = detail;
        current.visibleActiveKey = activeKey;
        current.visibleSince = isSameState ? current.visibleSince : now;
    }

    return {
        stage: current.visibleStage || stage,
        detail: current.visibleDetail || detail,
        activeKey: current.visibleActiveKey || activeKey,
    };
}

function updateGenerationProgressDom(stage, detail, startedAt, extraItems = [], activeKey = 'backend') {
    const loading = document.getElementById('generate-loading');
    if (!loading) return;

    activeKey = stabilizeProgressActiveKey(activeKey);
    const visible = getVisibleProgressState(stage, detail, activeKey);

    const incomingKeys = extraItems.map(item => item?.key).filter(Boolean).sort().join('|');
    const currentKeys = generationProgressSnapshot.extraItems.map(item => item.key).sort().join('|');
    const needsFullRender = !loading.querySelector('.progress-panel') || (incomingKeys && incomingKeys !== currentKeys);

    if (needsFullRender) {
        loading.innerHTML = renderGenerationProgress(visible.stage, visible.detail, startedAt, extraItems, visible.activeKey);
        loading.classList.add('active');
        return;
    }

    const elapsedSeconds = startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0;
    const stageNode = loading.querySelector('[data-progress-stage]');
    const elapsedNode = loading.querySelector('[data-progress-elapsed]');
    const detailNode = loading.querySelector('[data-progress-detail]');
    if (stageNode) stageNode.textContent = visible.stage;
    if (elapsedNode) elapsedNode.textContent = `已等待 ${elapsedSeconds} 秒`;
    if (detailNode) detailNode.textContent = visible.detail;

    loading.querySelectorAll('.progress-step').forEach(step => {
        const isActive = step.dataset.progressKey === visible.activeKey;
        step.classList.toggle('active', isActive);
        const titleNode = step.querySelector('strong');
        const spinner = step.querySelector('.progress-step-spinner');
        if (isActive && titleNode && !spinner) {
            titleNode.insertAdjacentHTML('afterbegin', '<span class="progress-step-spinner"></span>');
        }
        if (!isActive && spinner) {
            spinner.remove();
        }
    });
    loading.classList.add('active');
}

function setGenerationProgress(stage, detail, startedAt, extraItems = [], activeKey = 'backend') {
    updateGenerationProgressDom(stage, detail, startedAt, extraItems, activeKey);
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

function getProcessJobActiveKey(job) {
    if (!job) return 'uploaded';
    if (job.status === 'completed' || job.stage === 'completed') return 'completed';
    if (job.status === 'failed' || job.stage === 'failed') return 'failed';

    const stage = String(job.stage || '').toLowerCase();
    return stage || 'uploaded';
}

async function pollProcessJob(jobId, startedAt, uploadInfo) {
    let statusReadFailures = 0;
    while (true) {
        const response = await fetch(`${API_BASE}/process/jobs/${jobId}`);
        if (!response.ok) {
            const errorText = await response.text();
            statusReadFailures += 1;
            if (response.status >= 500 && statusReadFailures <= 8) {
                setGenerationProgress(
                    '任务仍在运行，正在重试状态读取',
                    `状态接口临时返回 HTTP ${response.status}，已重试 ${statusReadFailures}/8 次。`,
                    startedAt,
                    [
                        { key: 'job-id', label: '任务 ID', value: jobId },
                        { key: 'upload-files', label: '上传文件', value: uploadInfo.name },
                        { key: 'upload-size', label: '总大小', value: formatFileSize(uploadInfo.size) },
                        { key: 'status-error', label: '状态读取', value: errorText || `HTTP ${response.status}` },
                    ],
                    'backend',
                );
                await new Promise(resolve => setTimeout(resolve, 1500));
                continue;
            }
            throw new Error(`任务状态读取失败 HTTP ${response.status}: ${errorText}`);
        }
        statusReadFailures = 0;
        const job = await response.json();
        lastJob = job;
        const isFailed = job.status === 'failed' || job.stage === 'failed';
        const aiPreview = String(job.ai_stream_preview || '').trim();
        const isAiStage = ['flow_generating'].includes(String(job.stage || '').toLowerCase());
        const aiStreamItem = aiPreview || isAiStage
            ? {
                key: 'ai-stream',
                label: job.ai_stream_chunks ? `AI 实时输出（${job.ai_stream_chunks} 段）` : 'AI 实时状态',
                value: aiPreview || 'AI 请求已进入后端，正在等待模型返回第一段内容。',
            }
            : null;
        const jobDetail = isFailed
            ? `失败原因：${job.error || job.message || '任务失败'}；未生成可用工序结果。`
            : aiPreview
                ? `阶段：${job.stage}；AI 已返回 ${job.ai_stream_chunks || 0} 段内容，正在等待完整结果。`
                : `阶段：${job.stage}；进度：${job.progress || 0}%。`;
        setGenerationProgress(
            job.message || (isFailed ? '任务失败' : '任务处理中'),
            jobDetail,
            startedAt,
            [
                { key: 'job-id', label: '任务 ID', value: job.job_id },
                { key: 'upload-files', label: '上传文件', value: uploadInfo.name },
                { key: 'upload-size', label: '总大小', value: formatFileSize(uploadInfo.size) },
                aiStreamItem,
            ].filter(Boolean),
            getProcessJobActiveKey(job),
        );
        if (job.process_result) return job;
        if (job.status === 'completed') return job;
        if (job.status === 'failed') throw new Error(job.error || job.message || '任务失败');
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
}

async function uploadWithJobProgress(url, formData, startedAt, uploadInfo) {
    const response = await requestWithUploadProgress(url, formData, startedAt, uploadInfo);
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errorText}`);
    }
    const job = await response.json();
    return pollProcessJob(job.job_id, startedAt, uploadInfo);
}

function requestWithUploadProgress(url, formData, startedAt, uploadInfo) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url);
        xhr.upload.onprogress = event => {
            if (!event.lengthComputable) return;
            const percent = Math.round((event.loaded / event.total) * 100);
            setGenerationProgress(
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
            stopGenerationProgressTimer();
            setGenerationProgress(
                '上传完成，等待后端创建任务',
                '文件已传输完成，正在等待后端返回任务 ID；后续进度只展示后端任务状态。',
                startedAt,
                [
                    { key: 'upload-files', label: '上传文件', value: uploadInfo.name },
                    { key: 'upload-size', label: '总大小', value: formatFileSize(uploadInfo.size) },
                ],
                'backend',
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
    if (loading) {
        loading.classList.remove('active');
    }
    isGeneratingProcess = false;
    if (generateButton) {
        generateButton.disabled = false;
        generateButton.textContent = '生成工序方案';
        delete generateButton.dataset.generating;
    }
}

// 生成工序
async function generateProcess() {
    const generateButton = document.getElementById('generate-process-btn');
    if (isGeneratingProcess || generateButton?.dataset.generating === 'true') {
        return;
    }
    isGeneratingProcess = true;
    if (generateButton) {
        generateButton.dataset.generating = 'true';
    }

    const method = document.getElementById('input-method').value;
    const mode = document.getElementById('process-mode').value;
    const targetOperationCount = Math.max(1, Math.min(60, Number(document.getElementById('target-operation-count')?.value || 15)));
    const useExternalConditions = document.getElementById('use-external-conditions').checked;
    
    const loading = document.getElementById('generate-loading');
    const result = document.getElementById('generate-result');
    const startedAt = Date.now();
    generationProgressSnapshot = {
        extraItems: [],
        activeKey: 'request',
        visibleStage: '',
        visibleDetail: '',
        visibleActiveKey: 'request',
        visibleSince: 0,
    };
    
    result.classList.remove('active');
    startGenerationProgressTimer(
        '准备生成工序',
        `输入方式：${method}；目标工序数：${targetOperationCount}`,
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
        target_operation_count: targetOperationCount,
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
        currentData = null;
        currentCaseId = null;
        lastJob = null;
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
            const selectedFiles = Array.from(fileInput.files || []);
            const useBoundCaseFiles = !selectedFiles.length && boundCaseSourceFiles?.length;

            if (!selectedFiles.length && !useBoundCaseFiles) {
                resetGenerateButton(loading, generateButton);
                alert('请选择文件，或先从案例库加载带图纸绑定的案例');
                return;
            }

            let job;
            if (useBoundCaseFiles) {
                uploadInfo = {
                    name: boundCaseDisplayNames.join('、') || boundCaseSourceFiles.join('、'),
                    size: 0,
                    suffix: 'stored',
                    supportNote: '复用案例绑定的 uploads 文件，跳过浏览器上传',
                };
                startGenerationProgressTimer(
                    '复用案例图纸',
                    `将直接使用 uploads 中的 ${boundCaseSourceFiles.length} 个文件创建任务。`,
                    startedAt,
                    [
                        { key: 'upload-files', label: '图纸文件', value: uploadInfo.name },
                        { key: 'upload-mode', label: '来源', value: '案例库 / uploads 复用' },
                    ],
                    'backend',
                );
                job = await startJobFromStoredFiles(boundCaseSourceFiles, mode, targetOperationCount, startedAt, uploadInfo);
            } else {
                const files = selectedFiles;
                const supportedSuffixes = ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'dwg', 'dxf'];
                const unsupportedFile = files.find(file => !supportedSuffixes.includes(getFileSuffix(file.name)));
                if (unsupportedFile) {
                    resetGenerateButton(loading, generateButton);
                    alert(`暂不支持 ${unsupportedFile.name} 的文件格式，请上传 PDF、图片或 DWG/DXF 文件`);
                    return;
                }

                const formData = new FormData();
                files.forEach(file => formData.append('files', file));
                uploadInfo = {
                    name: files.map(file => file.name).join('、'),
                    size: files.reduce((total, file) => total + file.size, 0),
                    suffix: files.length > 1 ? 'batch' : getFileSuffix(files[0].name),
                    supportNote: files.length > 1
                        ? `批量上传 ${files.length} 个文件：快速合并生成工艺流程`
                        : getUploadSupportNote(getFileSuffix(files[0].name))
                };
                const endpoint = '/process/jobs/upload-batch';
                startGenerationProgressTimer(
                    '后端任务接口已调用',
                    `正在发送 ${files.length} 个文件到 ${endpoint}。上传完成后会创建快速工序任务。`,
                    startedAt,
                    [
                        { key: 'upload-files', label: '上传文件', value: files.map(file => file.name).join('、') },
                        { key: 'upload-size', label: '总大小', value: formatFileSize(uploadInfo.size) },
                    ],
                    'upload',
                );
                job = await uploadWithJobProgress(
                    `${API_BASE}${endpoint}?mode=${mode}&target_operation_count=${targetOperationCount}`,
                    formData,
                    startedAt,
                    uploadInfo,
                );
            }
            const data = job.process_result;
            if (!data) {
                throw new Error('任务已完成但没有返回流程结果');
            }
            data.upload_info = uploadInfo;
            data.process_job = job;
            currentData = data;
            setGenerationProgress(
                '生成完成，正在渲染结果',
                `后端返回 ${data.process_plan?.operations?.length || 0} 道工序。`,
                startedAt,
                [],
                'result',
            );
            displayResult(data);
            response = null;
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
        
        if (response) {
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
        }
        
    } catch (error) {
        keepProgressVisible = true;
        currentData = null;
        currentCaseId = null;
        stopGenerationProgressTimer();
        result.classList.remove('active');
        result.innerHTML = '';
        const failureItems = [
            { key: 'failed-reason', label: '失败原因', value: error.message },
            { key: 'suggestion', label: '处理建议', value: '待定' },
        ];
        if (lastJob?.job_id) {
            failureItems.unshift({ key: 'job-id', label: '任务 ID', value: lastJob.job_id });
        }
        showGenerationFailure(
            '生成失败',
            error.message,
            startedAt,
            failureItems,
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
                delete generateButton.dataset.generating;
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
    
    // 生成页只展示快速工序结果；精细图解、气泡图和标注只在案例详情页展示。

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
    const flow = data.flow || {
        title: data.loaded_case_name ? `案例流程：${data.loaded_case_name}` : '流程图',
        mermaid: '',
    };
    html += '<div class="result-section">';
    html += `<h3>${escapeHtml(flow.title || '流程图')}</h3>`;
    if (data.loaded_case_name) {
        html += `<div class="info"><strong>案例来源：</strong>${escapeHtml(data.loaded_case_name)}。当前案例已加载为输入来源；如已绑定图纸，点击“生成工序方案”会复用对应 uploads 文件重新生成。</div>`;
    }
    html += '<p class="flow-readable-hint">默认展示按工序顺序展开的人话版流程；原始 Mermaid 技术图只在后端返回流程图时展示。</p>';
    html += renderReadableFlow(data.process_plan.operations || []);
    if (flow.mermaid) {
        html += '<details class="technical-flow-details">';
        html += '<summary>查看原始技术流程图</summary>';
        html += '<div class="mermaid-scroll">';
        html += `<div class="mermaid-diagram" id="mermaid-diagram">${flow.mermaid}</div>`;
        html += '</div>';
        html += '</details>';
    }
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
    if (flow.mermaid) {
        setTimeout(() => {
            const element = document.getElementById('mermaid-diagram');
            if (element) {
                mermaid.render('mermaid-svg-' + Date.now(), flow.mermaid).then(result => {
                    element.innerHTML = result.svg;
                }).catch(err => {
                    console.error('Mermaid rendering error:', err);
                    element.innerHTML = '<pre>' + escapeHtml(flow.mermaid) + '</pre>';
                });
            }
        }, 100);
    }
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
    
    const sourceFiles = collectCaseSourceFilesFromData(currentData);
    const caseData = {
        start_annotation: sourceFiles.length > 0,
        case: {
            case_id: 'case_' + Date.now(),
            case_name: caseName,
            drawing_parse_result: currentData.parse_result,
            source_files: sourceFiles,
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
        const annotationMessage = result.annotation_job
            ? `\n精细标注：${result.annotation_job.message || result.annotation_job.status || '已启动'}`
            : '\n精细标注：未启动';
        alert('案例保存成功！案例ID：' + result.case_id + annotationMessage);
        switchTab('cases', document.querySelector('.tab[data-tab="cases"]'));
        await loadCase(result.case_id);
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
        html += `<div class="case-item" onclick="loadCase('${escapeHtml(c.case_id)}')">`;
        html += `<div class="case-header">`;
        html += `<span class="case-title">${escapeHtml(c.case_name)}</span>`;
        html += `<span class="case-status ${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>`;
        html += `</div>`;
        html += `<p style="font-size:14px; color:#666;">创建于：${new Date(c.created_at).toLocaleString()}</p>`;
        const sourceFiles = c.source_files || [];
        if (sourceFiles.length) {
            html += `<p style="font-size:13px; color:#666;">绑定文件：${sourceFiles.map(item => escapeHtml(item.original_name || item.stored_name)).join('、')}</p>`;
        }
        html += `<div class="case-annotation-summary" id="case-annotation-${escapeHtml(c.case_id)}"><span class="badge" style="background:#999;">标注状态读取中</span></div>`;
        if (c.tags && c.tags.length > 0) {
            html += `<p style="margin-top:5px;">`;
            c.tags.forEach(tag => {
                html += `<span class="badge" style="background:#999;">${escapeHtml(tag)}</span>`;
            });
            html += `</p>`;
        }
        html += `<div style="margin-top:10px;">`;
        html += `<button type="button" class="btn btn-sm btn-danger" onclick="deleteCase(event, '${escapeHtml(c.case_id)}', '${escapeHtml(c.case_name)}')">删除案例和对应文件</button>`;
        html += `</div>`;
        html += `</div>`;
    });
    
    container.innerHTML = html;
    cases.forEach(c => refreshCaseAnnotationSummary(c.case_id));
}

async function refreshCaseAnnotationSummary(caseId) {
    const target = document.getElementById(`case-annotation-${caseId}`);
    if (!target) return;
    try {
        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/status`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const status = await response.json();
        const rawStatus = String(status.status || 'not_started');
        const color = rawStatus === 'completed' ? '#2e7d32'
            : rawStatus === 'failed' ? '#c62828'
            : ['pending', 'running'].includes(rawStatus) ? '#ef6c00'
            : '#777';
        target.innerHTML = `<span class="badge" style="background:${color};">精细标注：${escapeHtml(rawStatus)}</span> <small>${escapeHtml(status.message || '')}</small>`;
    } catch (error) {
        target.innerHTML = `<span class="badge" style="background:#999;">精细标注：未知</span>`;
    }
}

async function deleteCase(event, caseId, caseName) {
    event.stopPropagation();
    const confirmed = confirm(`确认删除案例「${caseName}」吗？\n会同步删除该案例绑定、且未被其他案例引用的 uploads 文件。`);
    if (!confirmed) return;

    try {
        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }
        const result = await response.json();
        if (currentCaseId === caseId) {
            currentCaseId = null;
            clearBoundCaseSourceFiles();
        }
        const deletedCount = result.deleted_files?.length || 0;
        const retainedCount = result.retained_files?.length || 0;
        alert(`案例已删除。已删除文件 ${deletedCount} 个${retainedCount ? `，仍被其他案例引用未删 ${retainedCount} 个` : ''}。`);
        loadCases();
    } catch (error) {
        alert('删除案例失败：' + error.message);
    }
}

// 加载单个案例详情
async function loadCase(caseId) {
    try {
        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const caseData = await response.json();
        currentCaseId = caseId;
        renderCaseDetail(caseData, { status: 'loading', message: '正在读取精细标注状态...' }, null);
        await refreshCaseAnnotation(caseId, caseData);
    } catch (error) {
        alert('加载案例失败：' + error.message);
    }
}

function renderCaseDetail(caseData, annotationStatus, annotationResult) {
    const container = document.getElementById('case-detail');
    if (!container) return;
    const sourceFiles = caseData.source_files || [];
    const operations = caseData.process_plan?.operations || [];
    const status = annotationStatus || { status: 'not_started', progress: 0, message: '尚未启动精细标注' };
    const explanations = annotationResult?.explanations || [];
    const canPoll = ['pending', 'running'].includes(String(status.status || '').toLowerCase());

    let html = '<div class="result-section">';
    html += `<h3>案例详情：${escapeHtml(caseData.case_name)}</h3>`;
    html += `<div class="part-info-grid">`;
    html += `<p><strong>案例ID：</strong>${escapeHtml(caseData.case_id)}</p>`;
    html += `<p><strong>状态：</strong>${escapeHtml(caseData.status || 'draft')}</p>`;
    html += `<p><strong>工序数：</strong>${operations.length}</p>`;
    html += `<p><strong>绑定图纸：</strong>${sourceFiles.length ? sourceFiles.map(item => escapeHtml(item.original_name || item.stored_name)).join('、') : '未绑定'}</p>`;
    html += '</div>';
    html += '<div style="margin-top:10px;">';
    html += `<button class="btn btn-primary" onclick="loadCaseForEdit('${escapeHtml(caseData.case_id)}')">编辑工序</button>`;
    html += `<button class="btn btn-secondary" onclick="loadCaseToAnalysis('${escapeHtml(caseData.case_id)}')">重新生成工序</button>`;
    html += `<button class="btn btn-secondary" onclick="startCaseAnnotation('${escapeHtml(caseData.case_id)}')">${status.status === 'failed' ? '重试精细标注' : '启动/刷新精细标注'}</button>`;
    html += '</div>';
    html += '</div>';

    html += '<div class="result-section">';
    html += '<h3>案例精细标注</h3>';
    html += `<div class="info"><strong>状态：</strong>${escapeHtml(status.status || 'not_started')} / ${escapeHtml(status.stage || 'not_started')}</div>`;
    html += `<div class="info"><strong>说明：</strong>${escapeHtml(status.message || '')}</div>`;
    if (status.ai_stream_preview) {
        html += `<div class="info"><strong>AI 状态：</strong>${escapeHtml(String(status.ai_stream_preview).slice(-180))}</div>`;
    }
    if (status.error_message) {
        html += `<div class="critical"><strong>${escapeHtml(status.error_type || 'Error')}：</strong>${escapeHtml(status.error_message)}</div>`;
    }
    if (canPoll) {
        html += '<div class="warning">精细标注在案例后台运行。你可以关闭页面，之后回到案例详情继续查看。</div>';
    }
    html += '</div>';

    if (explanations.length) {
        html += '<div class="result-section">';
        html += `<h3>精细标注结果（${explanations.length} 份图纸）</h3>`;
        if (annotationResult.export_csv_url) {
            html += `<p><a class="btn btn-sm" href="${API_BASE}/cases/${encodeURIComponent(caseData.case_id)}/annotations/assets/${encodeURIComponent(annotationResult.job_id)}/${annotationResult.export_csv_url}" target="_blank">下载标注 CSV</a></p>`;
        }
        explanations.slice(0, 6).forEach(explanation => {
            html += `<div class="operation-card">`;
            html += `<div class="operation-header"><span class="operation-no">${escapeHtml(explanation.file_index)}</span><span class="operation-name">${escapeHtml(explanation.file_name)}</span></div>`;
            html += `<p>${escapeHtml(explanation.visual_summary || '暂无图解摘要')}</p>`;
            const pages = explanation.page_explanations || [];
            pages.forEach(page => {
                const bubble = page.bubble_asset || explanation.bubble_asset;
                html += `<div class="info"><strong>第 ${escapeHtml(page.page || 1)} 页：</strong>${escapeHtml(page.visual_summary || '')}</div>`;
                if (bubble?.image_url) {
                    html += `<p><a class="btn btn-sm" href="${API_BASE}/cases/${encodeURIComponent(caseData.case_id)}/annotations/assets/${encodeURIComponent(annotationResult.job_id)}/${bubble.image_url}" target="_blank">打开气泡图</a></p>`;
                }
                const annotations = page.annotation_result?.annotations || [];
                if (annotations.length) {
                    html += `<div class="info">标注数量：${annotations.length}</div>`;
                }
            });
            html += '</div>';
        });
        if (explanations.length > 6) {
            html += `<div class="info">已隐藏 ${explanations.length - 6} 份图纸的页面预览；完整标注请下载 CSV 或逐项打开气泡图。</div>`;
        }
        html += '</div>';
    }

    container.innerHTML = html;
    container.classList.add('active');
}

async function refreshCaseAnnotation(caseId, caseData = null) {
    if (caseAnnotationPollTimer) {
        clearTimeout(caseAnnotationPollTimer);
        caseAnnotationPollTimer = null;
    }
    const loadedCase = caseData || await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`).then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    });
    const statusResponse = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/status`);
    const status = statusResponse.ok ? await statusResponse.json() : { status: 'not_started', progress: 0, message: '尚未启动精细标注' };
    let result = null;
    if (['completed', 'failed'].includes(String(status.status || '').toLowerCase())) {
        const resultResponse = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/result`);
        if (resultResponse.ok) result = await resultResponse.json();
    }
    renderCaseDetail(loadedCase, status, result);
    if (['pending', 'running'].includes(String(status.status || '').toLowerCase())) {
        caseAnnotationPollTimer = setTimeout(() => refreshCaseAnnotation(caseId, loadedCase), 3000);
    }
}

async function startCaseAnnotation(caseId) {
    try {
        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/retry`, { method: 'POST' });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        await refreshCaseAnnotation(caseId);
    } catch (error) {
        alert('启动精细标注失败：' + error.message);
    }
}

async function loadCaseForEdit(caseId) {
    try {
        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const caseData = await response.json();
        currentCaseId = caseData.case_id;
        currentData = {
            loaded_case_name: caseData.case_name,
            parse_result: caseData.drawing_parse_result,
            process_plan: caseData.process_plan,
            flow: { title: `案例流程：${caseData.case_name}`, mermaid: '' },
            similar_cases: [],
            ai_suggestions: [],
        };
        displayResult(currentData);
        editCurrentPlan();
    } catch (error) {
        alert('加载案例到编辑工序失败：' + error.message);
    }
}

async function loadCaseToAnalysis(caseId) {
    try {
        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/load-to-workbench`, { method: 'POST' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        const sourceFiles = payload.source_files || [];
        boundCaseSourceFiles = sourceFiles.map(item => item.stored_name).filter(Boolean);
        boundCaseDisplayNames = sourceFiles.map(item => item.original_name || item.stored_name).filter(Boolean);
        if (!boundCaseSourceFiles.length) {
            alert('该案例没有绑定 uploads 文件，无法直接复用到分析台');
            return;
        }
        currentCaseId = payload.case_id;
        document.getElementById('input-method').value = 'file';
        toggleInputMethod();
        updateBoundCaseFilesHint();
        switchTab('generate', document.querySelector('.tab[data-tab="generate"]'));
    } catch (error) {
        alert('加载到分析台失败：' + error.message);
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
    const loading = document.getElementById('generate-loading');
    const generateButton = document.getElementById('generate-process-btn');
    resetGenerateButton(loading, generateButton);
    clearBoundCaseSourceFiles();
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

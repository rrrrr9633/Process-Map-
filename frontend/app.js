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
let mermaidZoom = 1;
let agentUploadedFiles = [];
let agentConversation = [];
let lastAgentResponse = null;
let agentSessionId = window.localStorage.getItem('cutr_agent_session_id') || '';

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    mermaid.initialize({ startOnLoad: false, theme: 'default' });
    bindFileUploadPreview();
    bindModelProfileSwitcher();
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

function toggleAgentMode() {
    const enabled = Boolean(document.getElementById('use-agent-mode')?.checked);
    const panel = document.getElementById('agent-chat-panel');
    const button = document.getElementById('generate-process-btn');
    if (panel) panel.style.display = enabled ? 'block' : 'none';
    if (button) button.textContent = enabled ? '启动 Agent 分析' : '生成工序方案';
}

window.toggleAgentMode = toggleAgentMode;

function appendAgentMessage(role, content) {
    const messages = document.getElementById('agent-chat-messages');
    if (!messages) return;
    const node = document.createElement('div');
    node.className = `agent-message agent-message-${role}`;
    node.textContent = content;
    messages.appendChild(node);
    messages.scrollTop = messages.scrollHeight;
    return node;
}

function clearAgentChat() {
    agentUploadedFiles = [];
    agentConversation = [];
    const input = document.getElementById('agent-chat-input');
    const fileInput = document.getElementById('agent-file-input');
    const messages = document.getElementById('agent-chat-messages');
    if (input) input.value = '';
    if (fileInput) fileInput.value = '';
    if (messages) {
        messages.innerHTML = '<div class="agent-message agent-message-system">Agent 模式已开启。可以直接提问，也可以上传图纸文件让 Agent 自动选择工具分析。</div>';
    }
}

async function startNewAgentSession() {
    agentSessionId = '';
    window.localStorage.removeItem('cutr_agent_session_id');
    lastAgentResponse = null;
    clearAgentChat();
    await ensureAgentSession();
    appendAgentMessage('system', `已创建新 Agent 会话：${agentSessionId}`);
}

async function uploadAgentFiles(files) {
    if (!files.length) return [];
    await ensureAgentSession();
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    const response = await fetch(`${API_BASE}/agent/files?session_id=${encodeURIComponent(agentSessionId)}`, {
        method: 'POST',
        body: formData,
    });
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Agent 文件上传失败：HTTP ${response.status}: ${errorText}`);
    }
    const data = await response.json();
    return data.files || [];
}

async function ensureAgentSession() {
    if (agentSessionId) return agentSessionId;
    const response = await fetch(`${API_BASE}/agent/sessions`, { method: 'POST' });
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Agent 会话创建失败：HTTP ${response.status}: ${errorText}`);
    }
    const data = await response.json();
    agentSessionId = data.session?.session_id || '';
    if (agentSessionId) {
        window.localStorage.setItem('cutr_agent_session_id', agentSessionId);
    }
    return agentSessionId;
}

function summarizeAgentRun(run) {
    if (!run) return 'Agent 没有返回运行结果。';
    const actualRun = run.run || run;
    if (run.assistant_message) {
        return run.assistant_message;
    }
    const lines = [`状态：${actualRun.status || run.status || 'unknown'}`];
    if (actualRun.final_result) {
        lines.push(`最终结果：${JSON.stringify(actualRun.final_result, null, 2)}`);
    }
    const lastObservation = (actualRun.observations || []).slice(-1)[0];
    if (lastObservation) {
        lines.push(`最后工具：${lastObservation.tool_name}，${lastObservation.ok ? '成功' : '失败'}`);
        if (lastObservation.error_message) lines.push(`错误：${lastObservation.error_message}`);
    }
    const lastEvent = (actualRun.events || []).slice(-1)[0];
    if (lastEvent) lines.push(`事件：${lastEvent.message}`);
    return lines.join('\n');
}

function renderAgentRunResult(run) {
    const result = document.getElementById('generate-result');
    if (!result) return;
    lastAgentResponse = run;
    const actualRun = run.run || run;
    const cards = run.cards || [];
    const actions = run.actions || [];
    const cardHtml = cards.map(renderAgentCard).join('');
    const actionHtml = renderAgentActions(actions);
    result.innerHTML = `
        <div class="result-section">
            <h3>Agent 状态</h3>
            <div class="agent-run-status">${escapeHtml(summarizeAgentRun(run))}</div>
            ${actionHtml}
            <details class="technical-flow-details">
                <summary>查看计划和运行轨迹</summary>
                ${cardHtml}
                <pre>${escapeHtml(JSON.stringify(actualRun, null, 2))}</pre>
            </details>
        </div>
    `;
    result.classList.add('active');
}

function renderAgentActions(actions) {
    if (!actions.length) return '';
    return `<div class="agent-actions">${actions.map((action, index) => `<button class="btn btn-sm" type="button" onclick="handleAgentAction(${index})">${escapeHtml(action.label || action.type)}</button>`).join('')}</div>`;
}

function appendAgentActions(actions) {
    const messages = document.getElementById('agent-chat-messages');
    if (!messages || !actions?.length) return;
    const node = document.createElement('div');
    node.className = 'agent-message agent-message-system agent-action-message';
    node.innerHTML = renderAgentActions(actions);
    messages.appendChild(node);
    messages.scrollTop = messages.scrollHeight;
}

async function handleAgentAction(index) {
    const action = lastAgentResponse?.actions?.[index];
    if (!action) return;
    if (action.type === 'revise_request' || action.type === 'ask_followup' || action.type === 'retry') {
        const input = document.getElementById('agent-chat-input');
        if (input) {
            input.focus();
            input.placeholder = '补充你的需求后点击发送给 Agent';
        }
        return;
    }
    if (action.type === 'confirm_tool') {
        const toolName = action.tool_name;
        if (!toolName) {
            alert('缺少需要确认的工具名');
            return;
        }
        const confirmed = confirm(`确认继续执行工具：${toolName}？`);
        if (!confirmed) return;
        try {
            appendAgentMessage('user', `确认继续执行：${toolName}`);
            const response = await continueAgentWithConfirmation(toolName);
            const summary = summarizeAgentRun(response);
            appendAgentMessage('assistant', summary);
            appendAgentActions(response.actions || []);
            agentConversation.push({ role: 'assistant', content: summary, run_id: response.run?.run_id || response.run_id, status: response.status || response.run?.status });
            renderAgentRunResult(response);
        } catch (error) {
            appendAgentMessage('assistant', `确认执行失败：${error.message}`);
            console.error(error);
        }
    }
}

async function continueAgentWithConfirmation(toolName) {
    const actualRun = lastAgentResponse?.run || lastAgentResponse || {};
    const inputFiles = agentUploadedFiles.map(file => file.file_path);
    const action = (lastAgentResponse?.actions || []).find(item => item.type === 'confirm_tool' && item.tool_name === toolName) || {};
    const response = await fetch(`${API_BASE}/agent/runs/confirm-tool`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            goal: actualRun.goal || '继续执行已确认的 Agent 动作',
            session_id: agentSessionId,
            tool_name: toolName,
            arguments: action.arguments || {},
            input_files: inputFiles.length ? inputFiles : (actualRun.input_files || []),
            max_permission: 'write',
        }),
    });
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Agent 确认执行失败：HTTP ${response.status}: ${errorText}`);
    }
    return response.json();
}

function renderAgentCard(card) {
    if (card.kind === 'plan' && Array.isArray(card.items)) {
        return `
            <div class="agent-result-card">
                <strong>${escapeHtml(card.title || 'Agent 计划')}</strong>
                <div class="agent-plan-list">
                    ${card.items.map(step => `
                        <div class="agent-plan-step">
                            <span>${escapeHtml(step.status || 'pending')}</span>
                            <div>
                                <strong>${escapeHtml(step.title || `步骤 ${step.step_no || ''}`)}</strong>
                                <p>${escapeHtml(step.purpose || '')}</p>
                                ${step.tool_name ? `<small>工具：${escapeHtml(step.tool_name)}</small>` : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }
    return `
        <div class="agent-result-card">
            <strong>${escapeHtml(card.title || card.kind || '结果')}</strong>
            <pre>${escapeHtml(JSON.stringify(card.content || card.items || card, null, 2))}</pre>
        </div>
    `;
}

async function runAgentConversation(message, files = []) {
    await ensureAgentSession();
    const uploaded = await uploadAgentFiles(files);
    agentUploadedFiles = agentUploadedFiles.concat(uploaded);
    const inputFiles = agentUploadedFiles.map(file => file.file_path);
    const goal = message || '请根据当前上下文和文件进行工艺分析，并给出下一步建议。';
    const response = await fetch(`${API_BASE}/agent/runs/auto`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            goal,
            session_id: agentSessionId,
            user_message: message,
            input_files: inputFiles,
            max_permission: 'read_only',
            max_steps: 5,
            initial_context: {
                conversation: agentConversation.slice(-8),
                uploaded_files: agentUploadedFiles,
                file_path: inputFiles[0] || '',
            },
        }),
    });
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Agent 运行失败：HTTP ${response.status}: ${errorText}`);
    }
    return response.json();
}

async function sendAgentMessage() {
    const input = document.getElementById('agent-chat-input');
    const fileInput = document.getElementById('agent-file-input');
    const message = (input?.value || '').trim();
    const files = Array.from(fileInput?.files || []);
    if (!message && !files.length) {
        alert('请输入消息或选择文件');
        return;
    }
    appendAgentMessage('user', [message, files.length ? `附件：${files.map(file => file.name).join('、')}` : ''].filter(Boolean).join('\n'));
    agentConversation.push({ role: 'user', content: message, file_count: files.length });
    if (input) input.value = '';
    if (fileInput) fileInput.value = '';
    try {
        appendAgentMessage('system', 'Agent 正在感知输入、规划工具并执行...');
        const run = await runAgentConversation(message, files);
        const summary = summarizeAgentRun(run);
        appendAgentMessage('assistant', summary);
        appendAgentActions(run.actions || []);
        agentConversation.push({ role: 'assistant', content: summary, run_id: run.run?.run_id || run.run_id, status: run.status || run.run?.status });
        renderAgentRunResult(run);
    } catch (error) {
        appendAgentMessage('assistant', `失败：${error.message}`);
        console.error(error);
    }
}

function getFileSuffix(fileName) {
    const index = fileName.lastIndexOf('.');
    return index >= 0 ? fileName.slice(index + 1).toLowerCase() : '';
}

function getUploadSupportNote(suffix) {
    if (suffix === 'pdf') return 'PDF 将作为快速工序生成输入；精细图解和标注仅在案例后台运行';
    if (['png', 'jpg', 'jpeg', 'webp', 'bmp'].includes(suffix)) return '图片将作为快速工序生成输入；精细图解和标注仅在案例后台运行';
    if (['dwg', 'dxf'].includes(suffix)) return 'CAD 将尝试提取可用内容参与快速工序生成';
    if (['stl', 'obj', 'ply'].includes(suffix)) return '3D 网格将提取包围盒、主轴方向和预览图参与流程生成';
    if (['step', 'stp', 'iges', 'igs'].includes(suffix)) return '精确 3D CAD 已接收；需要 CAD 内核才能提取孔、圆角和 B-Rep 特征';
    return '该格式后端可能不支持';
}

function formatFileSize(size) {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function caseStatusLabel(status) {
    return {
        draft: '草稿',
        reviewed: '已审核',
        approved: '已批准',
        archived: '已归档',
    }[status] || status || '草稿';
}

function caseQualityLabel(quality) {
    return {
        excellent: '优秀',
        good: '良好',
        normal: '一般',
        poor: '较差',
    }[quality] || '未评级';
}

function renderCaseSelectOptions(options, selectedValue) {
    return options.map(option => {
        const selected = option.value === selectedValue ? 'selected' : '';
        return `<option value="${escapeHtml(option.value)}" ${selected}>${escapeHtml(option.label)}</option>`;
    }).join('');
}

function defaultModelProfiles() {
    return [
        { profile_id: 'gpt55', label: 'OpenAI / GPT', configured: false, model: 'gpt-5.5', api_base: '' },
        { profile_id: 'ark_doubao', label: '火山 Ark / 豆包', configured: false, model: 'doubao-seed-2-0-pro-260215', api_base: 'https://ark.cn-beijing.volces.com/api/v3' },
        { profile_id: 'default', label: '默认环境模型', configured: false, model: '', api_base: '' },
    ];
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

function renderResultModule(title, body, { open = false, className = '' } = {}) {
    if (!body) return '';
    return `
        <details class="result-section result-module ${className}" ${open ? 'open' : ''}>
            <summary>
                <span>${escapeHtml(title)}</span>
                <small class="result-module-toggle"></small>
            </summary>
            <div class="result-module-body">${body}</div>
        </details>
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

function buildGenerationAiResponse(data) {
    return {
        ai_suggestions: data?.ai_suggestions || [],
        agent_trace: data?.agent_trace || null,
        process_guidance: data?.process_guidance || data?.generation_ai_response?.process_guidance || null,
        job_id: data?.job_id || data?.process_job?.job_id || null,
        saved_at: new Date().toISOString(),
    };
}

function renderGenerationAiResponse(aiResponse, { details = false } = {}) {
    const suggestions = aiResponse?.ai_suggestions || [];
    const trace = aiResponse?.agent_trace || null;
    if (!suggestions.length && !trace) {
        return '<div class="info">暂无快速 AI 回复记录</div>';
    }

    let html = details ? '<details class="technical-flow-details"><summary>查看快速 AI 回复</summary>' : '';
    if (suggestions.length) {
        html += '<h4>AI 建议</h4>';
        suggestions.forEach(s => {
            html += `<div class="info">${escapeHtml(s)}</div>`;
        });
    }
    if (trace) {
        html += '<h4>Agent 识别链路</h4>';
        html += '<div class="part-info-grid">';
        html += `<p><strong>AI调用：</strong>${trace.used_ai ? '已使用' : '未使用'}</p>`;
        html += `<p><strong>视觉输入：</strong>${trace.used_vision ? '已使用图像' : '未使用图像'}</p>`;
        html += `<p><strong>兜底方案：</strong>${trace.fallback_used ? '已启用' : '未启用'}</p>`;
        html += '</div>';
        if (trace.stages && trace.stages.length > 0) {
            html += '<h4>执行阶段</h4>';
            trace.stages.forEach(stage => {
                html += `<div class="info">${escapeHtml(stage)}</div>`;
            });
        }
        if (trace.questions && trace.questions.length > 0) {
            html += '<h4>人工确认项</h4>';
            trace.questions.forEach(item => {
                const className = item.severity === 'critical' ? 'critical' : item.severity === 'warning' ? 'warning' : 'info';
                html += `<div class="${className}"><strong>${escapeHtml(item.field)}：</strong>${escapeHtml(item.question)}<br><small>${escapeHtml(item.reason || '')}</small></div>`;
            });
        }
    }
    if (details) {
        html += '</details>';
    }
    return html;
}

function buildFallbackProcessGuidance(data) {
    const operations = data?.process_plan?.operations || [];
    const part = data?.parse_result?.part || {};
    const partName = part.part_name || part.drawing_no || '当前零件';
    const operationNames = operations
        .map(op => op.operation_name || op.operation_no)
        .filter(Boolean);
    const reviewItems = [];
    operations.forEach(op => {
        (op.drawing_basis || []).slice(0, 1).forEach(item => reviewItems.push(`${op.operation_name || op.operation_no || '工序'}：${item}`));
        if (op.requires_manual_review) reviewItems.push(`${op.operation_name || op.operation_no || '工序'} 需要人工复核`);
    });

    return {
        feasibility: operations.length ? 'medium' : 'low',
        feasibility_text: operations.length
            ? '已基于当前工序方案整理出可执行的文字指导。'
            : '当前结果缺少工序方案，无法形成完整文字指导。',
        quality_score: operations.length ? 3.5 : 1,
        executive_summary: operations.length
            ? `${partName} 当前建议按 ${operations.length} 道工序组织：${operationNames.slice(0, 8).join(' -> ')}${operationNames.length > 8 ? ' ...' : ''}。`
            : '暂无可汇总的工序内容。',
        data_readability: data?.process_guidance
            ? ''
            : '后端未返回独立的最终文字指导，本模块由前端根据工序方案自动整理。',
        recommended_workflow: operations.map((op, index) => `${index + 1}. ${op.operation_name || op.operation_no || '未命名工序'}：${op.content || '按工序卡片执行'}`),
        metrics: [
            { label: '工序数量', value: String(operations.length), note: '来自当前工序方案' },
            { label: '需复核工序', value: String(operations.filter(op => op.requires_manual_review).length), note: '按工序标记统计' },
        ],
        key_usable_data: [
            part.material ? `材料：${part.material}` : '',
            part.blank_type ? `毛坯：${part.blank_type}` : '',
            part.heat_treatment ? `热处理：${part.heat_treatment}` : '',
        ].filter(Boolean),
        issues: [],
        manual_review: reviewItems.slice(0, 8),
        next_actions: ['优先展开“图文对照流程”核对工序顺序', '再展开“工序方案”逐道确认设备、检验项和图纸依据'],
    };
}

function renderProcessGuidance(guidance, { open = true, data = null } = {}) {
    const visibleGuidance = guidance || buildFallbackProcessGuidance(data);
    const feasibilityLabel = {
        high: '可行性高',
        medium: '可行性中等',
        low: '可行性低',
    }[visibleGuidance.feasibility] || '待评估';

    let html = '<div class="guidance-panel">';
    html += '<div class="guidance-head">';
    html += `<div><span class="guidance-status">${escapeHtml(feasibilityLabel)}</span><strong>${escapeHtml(visibleGuidance.feasibility_text || '')}</strong></div>`;
    html += `<div class="guidance-score">${escapeHtml(String(visibleGuidance.quality_score ?? '-'))}<small>/5</small></div>`;
    html += '</div>';
    if (visibleGuidance.executive_summary) {
        html += `<div class="info">${escapeHtml(visibleGuidance.executive_summary)}</div>`;
    }
    if (visibleGuidance.data_readability) {
        html += `<div class="info">${escapeHtml(visibleGuidance.data_readability)}</div>`;
    }
    if (visibleGuidance.metrics && visibleGuidance.metrics.length > 0) {
        html += '<div class="guidance-metrics">';
        visibleGuidance.metrics.forEach(metric => {
            html += '<div class="guidance-metric">';
            html += `<strong>${escapeHtml(metric.value || '')}</strong>`;
            html += `<span>${escapeHtml(metric.label || '')}</span>`;
            if (metric.note) html += `<small>${escapeHtml(metric.note)}</small>`;
            html += '</div>';
        });
        html += '</div>';
    }
    html += renderGuidanceList('可直接利用的数据', visibleGuidance.key_usable_data);
    html += renderGuidanceIssues(visibleGuidance.issues);
    html += renderGuidanceList('建议流程', visibleGuidance.recommended_workflow);
    html += renderGuidanceList('人工复核清单', visibleGuidance.manual_review);
    html += renderGuidanceList('下一步动作', visibleGuidance.next_actions);
    html += '</div>';
    return renderResultModule('最终文字指导', html, { open, className: 'guidance-module' });
}

function buildAnnotationGuidance(explanations) {
    const pages = [];
    const annotations = [];
    (explanations || []).forEach(explanation => {
        (explanation.page_explanations || []).forEach(page => {
            pages.push({ explanation, page });
            (page.annotation_result?.annotations || []).forEach(annotation => {
                annotations.push({ explanation, page, annotation });
            });
        });
    });
    const reviewItems = annotations.filter(item => {
        const status = item.annotation.review_status;
        const confidence = Number(item.annotation.confidence || 0);
        return status === 'pending' || status === 'needs_manual_review' || confidence < 0.85 || item.annotation.source === 'agent_reasoning';
    });
    const acceptedItems = annotations.filter(item => {
        const status = item.annotation.review_status;
        const confidence = Number(item.annotation.confidence || 0);
        return status === 'accepted' && confidence >= 0.85;
    });
    return {
        pageCount: pages.length,
        annotationCount: annotations.length,
        reviewCount: reviewItems.length,
        acceptedCount: acceptedItems.length,
        acceptedItems,
        reviewItems,
    };
}

function renderAnnotationGuidance(explanations) {
    const guidance = buildAnnotationGuidance(explanations);
    if (!guidance.pageCount && !guidance.annotationCount) {
        return '<div class="info">精细标注尚未形成可读结果。建议先启动或重试精细标注。</div>';
    }
    let html = '<div class="guidance-metrics">';
    html += `<div class="guidance-metric"><strong>${guidance.pageCount}</strong><span>已解析页数</span><small>参与气泡图与标注导出</small></div>`;
    html += `<div class="guidance-metric"><strong>${guidance.annotationCount}</strong><span>标注数量</span><small>已转换为可读摘要</small></div>`;
    html += `<div class="guidance-metric"><strong>${guidance.acceptedCount}</strong><span>可优先利用</span><small>高置信且已通过</small></div>`;
    html += `<div class="guidance-metric"><strong>${guidance.reviewCount}</strong><span>需复核</span><small>低置信、待审核或推理来源</small></div>`;
    html += '</div>';

    const usable = guidance.acceptedItems.slice(0, 8).map(item => readableAnnotationLine(item.annotation, item.explanation, item.page));
    const review = guidance.reviewItems.slice(0, 10).map(item => readableAnnotationLine(item.annotation, item.explanation, item.page));
    html += renderGuidanceList('可优先利用的标注', usable);
    html += renderGuidanceList('必须人工复核的标注', review);
    if (guidance.reviewCount > review.length) {
        html += `<div class="warning">还有 ${guidance.reviewCount - review.length} 条复核项未展开，请下载 CSV 查看 readable_summary 和 review_action 列。</div>`;
    }
    return html;
}

function renderFinalInstructionUnit(finalGuidance, caseId, jobId) {
    if (!finalGuidance) return '';
    const statusLabel = {
        needs_annotation: '需要补充标注',
        review_required: '需要人工复核',
        ready_for_process_review: '可进入工艺评审',
    }[finalGuidance.status] || finalGuidance.status || '待确认';

    let html = '<div class="result-section final-guidance-panel">';
    html += `<h3>${escapeHtml(finalGuidance.title || '最终工序流程指导')}</h3>`;
    html += `<div class="info"><strong>${escapeHtml(statusLabel)}：</strong>${escapeHtml(finalGuidance.summary || '')}</div>`;
    if (finalGuidance.objective) {
        html += `<div class="info">${escapeHtml(finalGuidance.objective)}</div>`;
    }

    if (finalGuidance.csv_url) {
        html += `<p><a class="btn btn-sm" href="${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/assets/${encodeURIComponent(jobId || finalGuidance.job_id)}/${finalGuidance.csv_url}" target="_blank">下载可读 CSV</a></p>`;
    }

    const imageRefs = finalGuidance.image_refs || [];
    if (imageRefs.length) {
        html += '<h4>气泡图证据</h4>';
        html += '<div class="final-image-grid">';
        imageRefs.slice(0, 8).forEach(ref => {
            const url = `${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/assets/${encodeURIComponent(jobId || finalGuidance.job_id)}/${ref.image_url}`;
            html += '<a class="final-image-card" target="_blank" href="' + url + '">';
            html += `<img src="${url}" alt="${escapeHtml(ref.title || '气泡图')}">`;
            html += `<strong>${escapeHtml(ref.title || '气泡图')}</strong>`;
            if (ref.summary) html += `<span>${escapeHtml(ref.summary)}</span>`;
            html += '</a>';
        });
        html += '</div>';
    }

    const operationUnits = finalGuidance.operation_units || [];
    if (operationUnits.length) {
        html += '<h4>工序指导单元</h4>';
        operationUnits.slice(0, 12).forEach(unit => {
            html += '<div class="operation-card final-operation-unit">';
            html += `<div class="operation-header"><span class="operation-no">${escapeHtml(unit.operation_no || '')}</span><span class="operation-name">${escapeHtml(unit.operation_name || '')}</span></div>`;
            html += `<p>${escapeHtml(unit.instruction || '')}</p>`;
            html += renderGuidanceList('操作步骤', unit.worker_steps);
            html += renderGuidanceList('质量放行', unit.quality_gates);
            html += renderGuidanceList('图纸依据', unit.drawing_basis);
            html += renderGuidanceList('可用标注依据', unit.usable_annotation_basis);
            html += renderGuidanceList('放行前复核', unit.review_before_release);
            html += '</div>';
        });
    }

    html += renderGuidanceList('可优先使用的标注', finalGuidance.usable_annotations);
    html += renderGuidanceList('必须复核的标注', finalGuidance.review_required);
    html += renderGuidanceList('交付说明', finalGuidance.handoff);
    html += '</div>';
    return html;
}

function readableAnnotationLine(annotation, explanation, page) {
    const name = annotation.parameter_name || annotation.label || annotation.annotation_id || '未命名参数';
    const value = annotation.parameter_value || annotation.normalized_text || annotation.raw_text || '待确认';
    const source = annotation.source === 'pdf_page_image' ? '图像识别' : annotation.source === 'pdf_text' ? 'PDF文本' : '模型推理';
    const confidence = Number(annotation.confidence || 0).toFixed(2);
    return `${explanation.file_name} 第${page.page || 1}页：${name} = ${value}；来源 ${source}；置信度 ${confidence}`;
}

function renderGuidanceList(title, list) {
    if (!list || list.length === 0) return '';
    const items = list.map(item => `<li>${escapeHtml(item)}</li>`).join('');
    return `<div class="guidance-list"><h4>${escapeHtml(title)}</h4><ul>${items}</ul></div>`;
}

function renderGuidanceIssues(issues) {
    if (!issues || issues.length === 0) return '';
    let html = '<div class="guidance-list"><h4>风险与限制</h4>';
    issues.forEach(issue => {
        const className = issue.severity === 'critical' ? 'critical' : issue.severity === 'warning' ? 'warning' : 'info';
        html += `<div class="${className}"><strong>${escapeHtml(issue.title || '风险')}：</strong>${escapeHtml(issue.detail || '')}</div>`;
    });
    html += '</div>';
    return html;
}

async function loadConfigStatus() {
    const apiBaseDisplay = document.getElementById('api-base-display');
    const aiStatus = document.getElementById('ai-status');
    const ocrStatus = document.getElementById('ocr-status');
    const visionStatus = document.getElementById('vision-status');
    const settingsDetail = document.getElementById('settings-detail');
    const modelProfileSelect = document.getElementById('model-profile-select');

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
        const modelProfiles = config.model_profiles || {};
        const profiles = (modelProfiles.profiles && modelProfiles.profiles.length)
            ? modelProfiles.profiles
            : defaultModelProfiles();

        apiBaseDisplay.textContent = config.api_base || API_BASE;
        aiStatus.textContent = ai.configured ? `已配置：${ai.provider || 'custom'} / ${ai.model || '未指定模型'} / ${ai.active_profile || 'default'}` : '未配置：当前模型档案缺少密钥/API地址/模型名';
        ocrStatus.textContent = ocr.configured ? `已配置：${ocr.provider || 'custom'}` : `未启用：${ocr.provider || 'none'}`;
        visionStatus.textContent = vision.configured ? `已配置：${vision.provider || 'custom'}` : `未启用：${vision.provider || 'none'}`;

        if (modelProfileSelect) {
            modelProfileSelect.innerHTML = profiles.map(profile => {
                const selected = profile.profile_id === (modelProfiles.active_profile || modelProfileSelect?.value) ? 'selected' : '';
                const configured = profile.configured ? '已配置' : '未配置';
                return `<option value="${escapeHtml(profile.profile_id)}" ${selected}>${escapeHtml(profile.label)} - ${escapeHtml(configured)}</option>`;
            }).join('');
        }

        const aiBase = ai.api_base || '未配置';
        const timeout = ai.timeout_seconds ? `${ai.timeout_seconds} 秒` : '未配置';
        const profileRows = profiles.map(profile => `
            <div>
                <strong>${escapeHtml(profile.label)}：</strong>
                ${escapeHtml(profile.configured ? '已配置' : '未配置')} /
                ${escapeHtml(profile.model || '未指定模型')} /
                ${escapeHtml(profile.api_base || '未配置 API 地址')}
            </div>
        `).join('');
        settingsDetail.innerHTML = `
            <div><strong>AI 接口：</strong>${escapeHtml(aiBase)}</div>
            <div><strong>AI 模型：</strong>${escapeHtml(ai.model || '未配置')}</div>
            <div><strong>AI 超时：</strong>${escapeHtml(timeout)}</div>
            <div><strong>模型档案：</strong>${escapeHtml(modelProfiles.active_profile || 'default')}</div>
            ${profileRows}
            <div><strong>说明：</strong>配置页只切换后端模型档案；密钥不会在前端展示。切换后新的 Agent 请求立即使用新模型。</div>
        `;
    } catch (error) {
        aiStatus.textContent = '状态读取失败';
        ocrStatus.textContent = '状态读取失败';
        visionStatus.textContent = '状态读取失败';
        settingsDetail.textContent = `无法读取 /config/status：${error.message}`;
    }
}

async function switchModelProfile() {
    const select = document.getElementById('model-profile-select');
    const button = document.getElementById('model-profile-switch-btn');
    const statusNode = document.getElementById('model-profile-switch-status');
    if (!select || !select.value) {
        if (statusNode) statusNode.textContent = '请选择模型档案。';
        return;
    }
    if (button) button.disabled = true;
    if (statusNode) statusNode.textContent = '正在切换模型档案...';
    try {
        const response = await fetch(`${API_BASE}/config/model-profile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile_id: select.value }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        const result = await response.json();
        if (statusNode) statusNode.textContent = `已切换到：${result.active?.label || result.active_profile}`;
        await loadConfigStatus();
    } catch (error) {
        if (statusNode) statusNode.textContent = `模型切换失败：${error.message}`;
    } finally {
        if (button) button.disabled = false;
    }
}

function bindModelProfileSwitcher() {
    const button = document.getElementById('model-profile-switch-btn');
    if (!button || button.dataset.bound === 'true') return;
    button.dataset.bound = 'true';
    button.addEventListener('click', switchModelProfile);
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
            : aiPreview && Number(job.ai_stream_chunks || 0) > 0
                ? `阶段：${job.stage}；AI 已返回 ${job.ai_stream_chunks || 0} 段内容，正在等待完整结果。`
                : isAiStage
                    ? `阶段：${job.stage}；AI 请求已发出，正在等待模型完成。`
                    : `阶段：${job.stage}；正在等待后端返回结果。`;
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
        generateButton.textContent = document.getElementById('use-agent-mode')?.checked ? '启动 Agent 分析' : '生成工序方案';
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
    const useAgentMode = Boolean(document.getElementById('use-agent-mode')?.checked);
    
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
        generateButton.textContent = useAgentMode ? 'Agent 运行中...' : '生成中...';
    }
    
    let requestData = {
        mode,
        target_operation_count: targetOperationCount,
    };

    let keepProgressVisible = false;
    try {
        currentData = null;
        currentCaseId = null;
        lastJob = null;
        let response;
        let uploadInfo = null;

        if (useAgentMode) {
            const chatInput = document.getElementById('agent-chat-input');
            const agentFileInput = document.getElementById('agent-file-input');
            let message = (chatInput?.value || '').trim();
            let files = Array.from(agentFileInput?.files || []);
            if (!message && method === 'text') {
                message = document.getElementById('text-input').value.trim();
            }
            if (!files.length && method === 'file') {
                files = Array.from(document.getElementById('file-input')?.files || []);
            }
            if (!message && !files.length && boundCaseSourceFiles?.length) {
                message = `请分析这些已绑定图纸：${boundCaseDisplayNames.join('、') || boundCaseSourceFiles.join('、')}`;
                agentUploadedFiles = agentUploadedFiles.concat(
                    boundCaseSourceFiles.map((storedName, index) => ({
                        original_name: boundCaseDisplayNames[index] || storedName,
                        stored_name: storedName,
                        file_path: storedName,
                        size: 0,
                    }))
                );
            }
            if (!message && !files.length && !agentUploadedFiles.length) {
                resetGenerateButton(loading, generateButton);
                alert('Agent 模式下请输入消息或选择文件');
                return;
            }
            startGenerationProgressTimer(
                'Agent 模式已启动',
                '正在上传附件并让 Agent 自动选择工具。',
                startedAt,
                [],
                'backend',
            );
            appendAgentMessage('user', [message, files.length ? `附件：${files.map(file => file.name).join('、')}` : ''].filter(Boolean).join('\n'));
            agentConversation.push({ role: 'user', content: message, file_count: files.length });
            const run = await runAgentConversation(message, files);
            const summary = summarizeAgentRun(run);
            appendAgentMessage('assistant', summary);
            appendAgentActions(run.actions || []);
            agentConversation.push({ role: 'assistant', content: summary, run_id: run.run?.run_id || run.run_id, status: run.status || run.run?.status });
            renderAgentRunResult(run);
            setGenerationProgress('Agent 运行完成', `状态：${run.status || run.run?.status || 'unknown'}`, startedAt, [], 'result');
            return;
        }
        
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
                const supportedSuffixes = ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'dwg', 'dxf', 'stl', 'obj', 'ply', 'step', 'stp', 'iges', 'igs'];
                const unsupportedFile = files.find(file => !supportedSuffixes.includes(getFileSuffix(file.name)));
                if (unsupportedFile) {
                    resetGenerateButton(loading, generateButton);
                    alert(`暂不支持 ${unsupportedFile.name} 的文件格式，请上传 PDF、图片、DWG/DXF 或 3D 模型文件`);
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
                generateButton.textContent = document.getElementById('use-agent-mode')?.checked ? '启动 Agent 分析' : '生成工序方案';
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
                    <div class="flow-step-head">
                        <span class="flow-step-index">${index + 1}</span>
                        <div class="flow-step-summary">
                            <span class="operation-no">${escapeHtml(op.operation_no || String(index + 1))}</span>
                            <strong>${escapeHtml(op.operation_name || '未命名工序')}</strong>
                            <small>${escapeHtml(op.content || '暂无工序说明')}</small>
                        </div>
                    </div>
                    ${(op.targets?.length || op.equipment?.length || op.inspection_items?.length || op.control_points?.length) ? `
                    <div class="flow-step-body">
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
                    ` : ''}
                </div>
                ${index < operations.length - 1 ? '<div class="flow-step-arrow">↓</div>' : ''}
            `).join('')}
        </div>
    `;
}

function renderProcessOverview(operations = []) {
    if (!operations.length) return '<div class="info">暂无工序</div>';
    return `
        <div class="process-overview-strip">
            ${operations.map((op, index) => `
                <div class="process-overview-node">
                    <span>${index + 1}</span>
                    <strong>${escapeHtml(op.operation_name || op.operation_no || `工序${index + 1}`)}</strong>
                </div>
            `).join('')}
        </div>
    `;
}

function operationVisualLabel(op) {
    const type = String(op.operation_type || '');
    if (type.includes('inspection')) return '检';
    if (type.includes('cleaning')) return '清';
    if (type.includes('finishing')) return '精';
    if (type.includes('rough')) return '粗';
    if (type.includes('hole')) return '孔';
    if (type.includes('blank')) return '坯';
    return '工';
}

function renderWorkerVisualCards(operations = []) {
    if (!operations.length) {
        return '<div class="info">暂无可展示的工序图文卡</div>';
    }
    return `
        <div class="worker-visual-grid">
            ${operations.map((op, index) => `
                <article class="worker-visual-card">
                    <div class="worker-visual-scene" aria-hidden="true">
                        <div class="worker-visual-badge">${escapeHtml(operationVisualLabel(op))}</div>
                        <div class="worker-visual-line"></div>
                        <div class="worker-visual-part"></div>
                        <div class="worker-visual-tool"></div>
                    </div>
                    <div class="worker-visual-body">
                        <div class="operation-header worker-visual-header">
                            <span class="operation-no">${escapeHtml(op.operation_no || String(index + 1))}</span>
                            <span class="operation-name">${escapeHtml(op.operation_name || '未命名工序')}</span>
                        </div>
                        <p>${escapeHtml(op.content || '暂无工序说明')}</p>
                        <div class="flow-step-meta">
                            ${(op.targets || []).slice(0, 2).map(item => `<span>对象：${escapeHtml(item)}</span>`).join('')}
                            ${(op.equipment || []).slice(0, 2).map(item => `<span>设备：${escapeHtml(item)}</span>`).join('')}
                            ${(op.inspection_items || []).slice(0, 2).map(item => `<span>检验：${escapeHtml(item)}</span>`).join('')}
                        </div>
                        ${renderGuidanceList('操作要点', (op.worker_steps || op.control_points || []).slice(0, 4))}
                        ${renderGuidanceList('放行条件', (op.quality_gates || op.handoff_requirements || []).slice(0, 3))}
                    </div>
                </article>
            `).join('')}
        </div>
    `;
}

function renderDrawingParseModule(data) {
    let html = '';
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
        if (part.part_name) html += `<p><strong>零件名称：</strong>${escapeHtml(part.part_name)}</p>`;
        if (part.drawing_no) html += `<p><strong>图号：</strong>${escapeHtml(part.drawing_no)}</p>`;
        if (part.material) html += `<p><strong>材料：</strong>${escapeHtml(part.material)}</p>`;
        if (part.blank_type) html += `<p><strong>毛坯类型：</strong>${escapeHtml(part.blank_type)}</p>`;
        if (part.heat_treatment) html += `<p><strong>热处理：</strong>${escapeHtml(part.heat_treatment)}</p>`;
        html += '</div>';
    }

    if (data.parse_result.features && data.parse_result.features.length > 0) {
        html += '<h4>识别特征</h4>';
        html += '<div class="feature-chip-row">';
        data.parse_result.features.forEach(f => {
            html += `<span class="badge">${escapeHtml(f.name)}</span>`;
        });
        html += '</div>';
    }

    if (data.parse_result.risk_flags && data.parse_result.risk_flags.length > 0) {
        html += '<h4>风险提示</h4>';
        data.parse_result.risk_flags.forEach(flag => {
            const className = flag.severity === 'critical' ? 'critical' : flag.severity === 'warning' ? 'warning' : 'info';
            html += `<div class="${className}"><strong>${escapeHtml(flag.field)}：</strong>${escapeHtml(flag.message)}</div>`;
        });
    }

    if (data.parse_result.raw_text) {
        html += '<details class="nested-details">';
        html += '<summary>查看解析原文</summary>';
        html += `<pre class="raw-text-preview">${escapeHtml(data.parse_result.raw_text)}</pre>`;
        html += '</details>';
    }
    return html || '<div class="info">暂无图纸解析结果</div>';
}

function renderOperationDetail(op, index) {
    let html = '<div class="operation-detail-grid">';
    html += '<div>';
    html += `<p>${escapeHtml(op.content || '暂无工序说明')}</p>`;
    if (op.targets && op.targets.length > 0) {
        html += `<p><strong>加工对象：</strong>${op.targets.map(escapeHtml).join('、')}</p>`;
    }
    if (op.control_points && op.control_points.length > 0) {
        html += `<p><strong>控制要点：</strong>${op.control_points.map(escapeHtml).join('；')}</p>`;
    }
    html += '</div>';
    html += '<div class="operation-reference">';
    if (op.equipment && op.equipment.length > 0) html += `<p><strong>设备：</strong>${op.equipment.map(escapeHtml).join('、')}</p>`;
    if (op.inspection_items && op.inspection_items.length > 0) html += `<p><strong>检验项：</strong>${op.inspection_items.map(escapeHtml).join('；')}</p>`;
    if (op.drawing_basis && op.drawing_basis.length > 0) html += renderOperationList('图纸依据', op.drawing_basis);
    html += '</div>';
    html += '</div>';
    html += '<div class="worker-guidance">';
    html += renderOperationList('操作步骤', op.worker_steps);
    html += renderOperationList('物料/半成品', op.materials);
    html += renderOperationList('工装刀量具', op.tools);
    html += renderOperationList('准备要求', op.setup_requirements);
    html += renderOperationList('安全注意', op.safety_points);
    html += renderOperationList('质量放行', op.quality_gates);
    html += renderOperationList('交接要求', op.handoff_requirements);
    html += '</div>';
    return html;
}

function renderProcessPlanModule(plan) {
    const operations = plan.operations || [];
    let html = `<p><strong>模式：</strong>${plan.mode === 'standard_8' ? '标准8道工序' : '详细工序'}</p>`;
    html += '<div class="info">每道工序默认展开；只保留上层模块折叠，便于整体收起或展开。</div>';
    if (plan.validation_issues && plan.validation_issues.length > 0) {
        html += '<h4>验证问题</h4>';
        plan.validation_issues.forEach(issue => {
            const className = issue.severity === 'critical' ? 'critical' : issue.severity === 'warning' ? 'warning' : 'info';
            html += `<div class="${className}"><strong>[${escapeHtml(issue.code)}]</strong> ${escapeHtml(issue.message)}</div>`;
        });
    }
    html += '<div class="operation-accordion">';
    operations.forEach((op, index) => {
        html += '<div class="operation-card">';
        html += '<div class="operation-header">';
        html += `<span class="operation-no">${escapeHtml(op.operation_no || String(index + 1))}</span>`;
        html += `<span class="operation-name">${escapeHtml(op.operation_name || '未命名工序')}</span>`;
        if (op.mandatory) html += '<span class="badge mandatory">必须</span>';
        if (op.requires_manual_review) html += '<span class="badge review">需审核</span>';
        if (op.operation_type) html += `<span class="operation-type">${escapeHtml(op.operation_type)}</span>`;
        html += '</div>';
        html += renderOperationDetail(op, index);
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function renderFlowModule(data, flow) {
    let html = '';
    if (data.loaded_case_name) {
        html += `<div class="info"><strong>案例来源：</strong>${escapeHtml(data.loaded_case_name)}。当前案例已加载为输入来源；如已绑定图纸，点击“生成工序方案”会复用对应 uploads 文件重新生成。</div>`;
    }
    html += '<div class="info">这里是默认展开的图文对照流程；单道工序全部展开，只有本模块整体可折叠。</div>';
    html += renderProcessOverview(data.process_plan.operations || []);
    html += renderReadableFlow(data.process_plan.operations || []);
    return html;
}

function renderTechnicalFlowModule(flow) {
    if (!flow.mermaid) return '';
    return `
        <div class="mermaid-toolbar">
            <button class="btn btn-sm" type="button" onclick="setMermaidZoom(-0.15)">缩小</button>
            <button class="btn btn-sm" type="button" onclick="resetMermaidZoom()">重置</button>
            <button class="btn btn-sm" type="button" onclick="setMermaidZoom(0.15)">放大</button>
            <span id="mermaid-zoom-label">100%</span>
        </div>
        <div class="mermaid-scroll">
            <div class="mermaid-diagram" id="mermaid-diagram">${escapeHtml(flow.mermaid)}</div>
        </div>
    `;
}

// 显示结果
function displayResult(data) {
    const container = document.getElementById('generate-result');
    let html = '';

    // 生成页只展示快速工序结果；精细图解、气泡图和标注只在案例详情页展示。
    html += renderProcessGuidance(data.process_guidance, { data });

    // 相似案例推荐
    if (data.similar_cases && data.similar_cases.length > 0) {
        let similarHtml = '';
        data.similar_cases.forEach(c => {
            similarHtml += `<div class="info">案例：${escapeHtml(c.case_name)} (质量：${escapeHtml(c.quality || '未评级')})</div>`;
        });
        html += renderResultModule('相似案例推荐', similarHtml);
    }

    // AI 回复与 Agent 执行链路
    if ((data.ai_suggestions && data.ai_suggestions.length > 0) || data.agent_trace) {
        html += renderResultModule('快速 AI 回复', renderGenerationAiResponse(buildGenerationAiResponse(data)));
    }

    // 图纸解析结果
    html += renderResultModule('图纸解析结果', renderDrawingParseModule(data));

    // 工人图文作业卡
    html += renderResultModule(
        '工序图文作业卡',
        renderWorkerVisualCards(data.process_plan.operations || []),
        { open: true },
    );

    // 工序方案
    html += renderResultModule(
        data.process_plan.title || '工序方案',
        renderProcessPlanModule(data.process_plan),
    );
    
    // 可读流程
    const flow = data.flow || {
        title: data.loaded_case_name ? `案例流程：${data.loaded_case_name}` : '流程图',
        mermaid: '',
    };
    html += renderResultModule(flow.title || '图文对照流程', renderFlowModule(data, flow), { open: true });
    if (flow.mermaid) {
        html += renderResultModule('原始技术流程图', renderTechnicalFlowModule(flow), { className: 'technical-flow-details' });
    }
    
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
        mermaidZoom = 1;
        setTimeout(() => {
            const element = document.getElementById('mermaid-diagram');
            if (element) {
                mermaid.render('mermaid-svg-' + Date.now(), flow.mermaid).then(result => {
                    element.innerHTML = result.svg;
                    applyMermaidZoom();
                }).catch(err => {
                    console.error('Mermaid rendering error:', err);
                    element.innerHTML = '<pre>' + escapeHtml(flow.mermaid) + '</pre>';
                });
            }
        }, 100);
    }
}

function applyMermaidZoom() {
    const diagram = document.getElementById('mermaid-diagram');
    const label = document.getElementById('mermaid-zoom-label');
    if (!diagram) return;
    diagram.style.transform = `scale(${mermaidZoom})`;
    diagram.style.transformOrigin = 'top left';
    diagram.style.width = `${100 / mermaidZoom}%`;
    if (label) {
        label.textContent = `${Math.round(mermaidZoom * 100)}%`;
    }
}

function setMermaidZoom(delta) {
    mermaidZoom = Math.max(0.5, Math.min(2.5, mermaidZoom + delta));
    applyMermaidZoom();
}

function resetMermaidZoom() {
    mermaidZoom = 1;
    applyMermaidZoom();
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
            generation_ai_response: buildGenerationAiResponse(currentData),
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
        const caseId = escapeHtml(c.case_id);
        const isActive = currentCaseId === c.case_id;
        html += `<div class="case-row ${isActive ? 'active' : ''}" id="case-row-${caseId}">`;
        html += `<div class="case-item" onclick="loadCase('${escapeHtml(c.case_id)}')">`;
        html += `<div class="case-header">`;
        html += `<span class="case-title">${escapeHtml(c.case_name)}</span>`;
        html += `<span class="case-status ${escapeHtml(c.status || 'draft')}">${escapeHtml(caseStatusLabel(c.status))}</span>`;
        html += `</div>`;
        html += `<p style="font-size:14px; color:#666;">创建于：${new Date(c.created_at).toLocaleString()}</p>`;
        html += `<p style="font-size:13px; color:#666;">质量：${escapeHtml(caseQualityLabel(c.quality))}</p>`;
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
        html += `<div id="case-detail-${caseId}" class="case-detail-inline result"></div>`;
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

async function saveCaseReview(caseId) {
    const status = document.getElementById('case-detail-status')?.value || 'draft';
    const quality = document.getElementById('case-detail-quality')?.value || null;
    const reviewer = document.getElementById('case-detail-reviewer')?.value.trim() || null;
    const comments = document.getElementById('case-detail-comments')?.value.trim() || null;

    try {
        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status, quality, reviewer, comments }),
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        }
        await loadCases();
        await loadCase(caseId);
    } catch (error) {
        alert('保存案例状态失败：' + error.message);
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

function renderCaseDetail(caseData, annotationStatus, annotationResult, options = {}) {
    const detailId = `case-detail-${caseData.case_id}`;
    const container = document.getElementById(detailId) || document.getElementById('case-detail');
    if (!container) return;
    document.querySelectorAll('.case-detail-inline').forEach(element => {
        const shouldKeep = element.id === detailId;
        element.classList.toggle('active', shouldKeep);
        if (!shouldKeep) element.innerHTML = '';
    });
    document.querySelectorAll('.case-row').forEach(element => {
        element.classList.toggle('active', element.id === `case-row-${caseData.case_id}`);
    });
    const sourceFiles = caseData.source_files || [];
    const operations = caseData.process_plan?.operations || [];
    const status = annotationStatus || { status: 'not_started', progress: 0, message: '尚未启动精细标注' };
    const explanations = annotationResult?.explanations || [];
    const canPoll = ['pending', 'running'].includes(String(status.status || '').toLowerCase());

    let overviewHtml = `<h3>案例详情：${escapeHtml(caseData.case_name)}</h3>`;
    overviewHtml += `<div class="part-info-grid">`;
    overviewHtml += `<p><strong>案例ID：</strong>${escapeHtml(caseData.case_id)}</p>`;
    overviewHtml += `<p><strong>状态：</strong>${escapeHtml(caseStatusLabel(caseData.status))}</p>`;
    overviewHtml += `<p><strong>质量：</strong>${escapeHtml(caseQualityLabel(caseData.quality))}</p>`;
    if (caseData.reviewer) overviewHtml += `<p><strong>审核人：</strong>${escapeHtml(caseData.reviewer)}</p>`;
    overviewHtml += `<p><strong>工序数：</strong>${operations.length}</p>`;
    overviewHtml += `<p><strong>绑定图纸：</strong>${sourceFiles.length ? sourceFiles.map(item => escapeHtml(item.original_name || item.stored_name)).join('、') : '未绑定'}</p>`;
    overviewHtml += '</div>';
    overviewHtml += '<div class="case-maintenance">';
    overviewHtml += '<div class="form-row">';
    overviewHtml += '<div class="form-col">';
    overviewHtml += '<label>案例状态</label>';
    overviewHtml += `<select id="case-detail-status">${renderCaseSelectOptions([
        { value: 'draft', label: '草稿' },
        { value: 'reviewed', label: '已审核' },
        { value: 'approved', label: '已批准' },
        { value: 'archived', label: '已归档' },
    ], caseData.status || 'draft')}</select>`;
    overviewHtml += '</div>';
    overviewHtml += '<div class="form-col">';
    overviewHtml += '<label>质量评级</label>';
    overviewHtml += `<select id="case-detail-quality">${renderCaseSelectOptions([
        { value: '', label: '未评级' },
        { value: 'excellent', label: '优秀' },
        { value: 'good', label: '良好' },
        { value: 'normal', label: '一般' },
        { value: 'poor', label: '较差' },
    ], caseData.quality || '')}</select>`;
    overviewHtml += '</div>';
    overviewHtml += '<div class="form-col">';
    overviewHtml += '<label>审核人</label>';
    overviewHtml += `<input id="case-detail-reviewer" type="text" value="${escapeHtml(caseData.reviewer || '')}" placeholder="可选">`;
    overviewHtml += '</div>';
    overviewHtml += '</div>';
    overviewHtml += '<label>审核备注</label>';
    overviewHtml += `<textarea id="case-detail-comments" rows="3" placeholder="记录批准、退回或质量评级依据">${escapeHtml(caseData.review_comments || '')}</textarea>`;
    overviewHtml += `<button class="btn btn-primary" type="button" onclick="saveCaseReview('${escapeHtml(caseData.case_id)}')">保存状态和质量</button>`;
    overviewHtml += '</div>';
    overviewHtml += '<div class="case-action-row">';
    overviewHtml += `<button class="btn btn-primary" onclick="loadCaseForEdit('${escapeHtml(caseData.case_id)}')">编辑工序</button>`;
    overviewHtml += `<button class="btn btn-secondary" onclick="loadCaseToAnalysis('${escapeHtml(caseData.case_id)}')">重新生成工序</button>`;
    overviewHtml += `<button class="btn btn-secondary" onclick="startCaseAnnotation('${escapeHtml(caseData.case_id)}')">${status.status === 'failed' ? '重试精细标注' : '启动/刷新精细标注'}</button>`;
    overviewHtml += '</div>';

    let html = renderResultModule('案例信息与操作', overviewHtml, { open: true, className: 'case-detail-module' });

    const guidanceHtml = renderProcessGuidance(caseData.generation_ai_response?.process_guidance, {
        data: {
            process_plan: caseData.process_plan,
            parse_result: caseData.drawing_parse_result || {},
        },
    });
    if (guidanceHtml) {
        html += renderResultModule('最终文字指导', guidanceHtml, { open: true, className: 'case-detail-module' });
    }

    html += renderResultModule('快速 AI 回复', renderGenerationAiResponse(caseData.generation_ai_response, { details: false }), { className: 'case-detail-module' });
    html += renderResultModule('工序流程', renderReadableFlow(operations), { open: true, className: 'case-detail-module case-process-flow-module' });

    let annotationStatusHtml = `<div class="info"><strong>状态：</strong>${escapeHtml(status.status || 'not_started')} / ${escapeHtml(status.stage || 'not_started')}</div>`;
    annotationStatusHtml += `<div class="info"><strong>说明：</strong>${escapeHtml(status.message || '')}</div>`;
    if (status.ai_stream_preview) {
        annotationStatusHtml += `<div class="info"><strong>AI 状态：</strong>${escapeHtml(String(status.ai_stream_preview).slice(-180))}</div>`;
    }
    if (status.error_message) {
        annotationStatusHtml += `<div class="critical"><strong>${escapeHtml(status.error_type || 'Error')}：</strong>${escapeHtml(status.error_message)}</div>`;
    }
    if (canPoll) {
        annotationStatusHtml += '<div class="warning">精细标注在案例后台运行。你可以关闭页面，之后回到案例详情继续查看。</div>';
    }
    html += renderResultModule('案例精细标注状态', annotationStatusHtml, { open: canPoll || String(status.status || '').toLowerCase() === 'failed', className: 'case-detail-module' });

    if (explanations.length) {
        html += renderResultModule('精细标注', renderAnnotationEvidence(explanations, annotationResult, caseData.case_id), { open: true, className: 'case-detail-module' });
        html += renderResultModule('气泡图', renderBubbleDiagramGallery(explanations, caseData.case_id, annotationResult.job_id), { open: true, className: 'case-detail-module bubble-gallery-module' });
        html += renderResultModule(
            '细分工艺图草稿',
            renderProcessDrawingPlan(annotationResult.process_drawing_plan, caseData.case_id, annotationResult.job_id),
            { open: true, className: 'case-detail-module process-drawing-module' }
        );
    }

    if (options.annotationOverlay) {
        html += renderAnnotationProgressOverlay(status, options.overlayStartedAt || Date.now(), Boolean(annotationResult?.explanations?.length));
    }

    container.innerHTML = `<div class="case-detail-refresh-shell ${options.annotationOverlay ? 'is-refreshing' : ''}">${html}</div>`;
    container.classList.add('active');
}

function renderAnnotationEvidence(explanations, annotationResult, caseId) {
    let html = renderAnnotationGuidance(explanations);
    if (annotationResult.export_csv_url) {
        html += `<p><a class="btn btn-sm" href="${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/assets/${encodeURIComponent(annotationResult.job_id)}/${annotationResult.export_csv_url}" target="_blank">下载可读标注 CSV</a></p>`;
    }
    explanations.slice(0, 6).forEach(explanation => {
        let drawingHtml = `<p>${escapeHtml(explanation.visual_summary || '暂无图解摘要')}</p>`;
        const pages = explanation.page_explanations || [];
        pages.forEach(page => {
            const annotations = page.annotation_result?.annotations || [];
            drawingHtml += `<div class="info"><strong>第 ${escapeHtml(page.page || 1)} 页：</strong>${escapeHtml(page.visual_summary || '')}</div>`;
            if (annotations.length) {
                const reviewCount = annotations.filter(annotation => {
                    const status = annotation.review_status;
                    return status === 'pending' || status === 'needs_manual_review' || Number(annotation.confidence || 0) < 0.85 || annotation.source === 'agent_reasoning';
                }).length;
                drawingHtml += `<div class="info">标注数量：${annotations.length}；需复核：${reviewCount}</div>`;
                drawingHtml += renderGuidanceList(
                    '本页关键标注',
                    annotations.slice(0, 5).map(annotation => readableAnnotationLine(annotation, explanation, page))
                );
            }
        });
        html += renderResultModule(
            `${explanation.file_index} ${explanation.file_name}`,
            drawingHtml,
            { className: 'case-drawing-module' }
        );
    });
    if (explanations.length > 6) {
        html += `<div class="info">已隐藏 ${explanations.length - 6} 份图纸的页面标注；完整标注请下载 CSV 查看。</div>`;
    }
    return html;
}

function renderBubbleDiagramGallery(explanations, caseId, jobId) {
    const refs = [];
    explanations.forEach(explanation => {
        (explanation.page_explanations || []).forEach(page => {
            const bubble = page.bubble_asset || explanation.bubble_asset;
            if (!bubble?.image_url) return;
            refs.push({
                fileName: explanation.file_name,
                page: page.page || 1,
                summary: page.visual_summary || explanation.visual_summary || '',
                imageUrl: bubble.image_url,
            });
        });
    });
    if (!refs.length) {
        return '<div class="info">暂无气泡图。完成精细标注后会自动生成气泡图证据。</div>';
    }
    let html = '<div class="bubble-gallery-grid">';
    refs.slice(0, 12).forEach(ref => {
        const url = `${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/assets/${encodeURIComponent(jobId)}/${ref.imageUrl}`;
        html += '<article class="bubble-gallery-card">';
        html += `<a href="${url}" target="_blank"><img src="${url}" alt="${escapeHtml(ref.fileName)} 第${escapeHtml(ref.page)}页气泡图"></a>`;
        html += `<strong>${escapeHtml(ref.fileName)} 第${escapeHtml(ref.page)}页</strong>`;
        if (ref.summary) html += `<span>${escapeHtml(ref.summary)}</span>`;
        html += `<div class="process-drawing-actions"><a class="btn btn-sm" href="${url}" target="_blank">打开气泡图</a><a class="btn btn-sm" href="${url}" target="_blank" download>下载 PNG</a></div>`;
        html += '</article>';
    });
    html += '</div>';
    if (refs.length > 12) {
        html += `<div class="info">还有 ${refs.length - 12} 张气泡图未展开，可在各页标注结果中查看。</div>`;
    }
    return html;
}

function renderProcessDrawingPlan(plan, caseId, jobId) {
    const sheets = plan?.sheets || [];
    if (!sheets.length) {
        return '<div class="warning">当前结果里还没有 process_drawing_plan。通常是云端后端还没更新到包含工艺图草稿的版本，或这个案例是旧的精细标注结果。请先发布后端代码并重新刷新精细标注；成功后这里会显示 S01/S02/S03 三张工艺图草稿。</div>';
    }
    let html = '<div class="process-drawing-summary">';
    html += `<div class="info"><strong>${escapeHtml(plan.title || '细分工艺图草稿')}：</strong>${escapeHtml(plan.objective || '用于工艺人员复核的草稿图。')}</div>`;
    if (plan.assumptions?.length) {
        html += renderGuidanceList('生成假设', plan.assumptions.slice(0, 3));
    }
    if (plan.risks?.length) {
        html += renderGuidanceList('复核风险', plan.risks.slice(0, 4));
    }
    html += '</div>';
    html += '<div class="process-drawing-grid">';
    sheets.forEach(sheet => {
        const png = (sheet.assets || []).find(asset => asset.asset_type === 'png' && asset.file_url);
        const svg = (sheet.assets || []).find(asset => asset.asset_type === 'svg' && asset.file_url);
        const pngUrl = png ? `${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/assets/${encodeURIComponent(jobId)}/${png.file_url}` : '';
        const svgUrl = svg ? `${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/assets/${encodeURIComponent(jobId)}/${svg.file_url}` : '';
        html += '<article class="process-drawing-card">';
        html += `<div class="process-drawing-card-head"><strong>${escapeHtml(sheet.sheet_no || '')} ${escapeHtml(sheet.title || '')}</strong><span>${escapeHtml(sheet.stage || 'draft')}</span></div>`;
        if (pngUrl) {
            html += `<a href="${pngUrl}" target="_blank" class="process-drawing-preview"><img src="${pngUrl}" alt="${escapeHtml(sheet.title || '工艺图草稿')}"></a>`;
        } else {
            html += '<div class="info">PNG 预览尚未生成</div>';
        }
        if (sheet.summary) {
            html += `<p>${escapeHtml(sheet.summary)}</p>`;
        }
        if (sheet.related_operation_nos?.length) {
            html += `<small>关联工序：${sheet.related_operation_nos.map(item => `OP${escapeHtml(item)}`).join('、')}</small>`;
        }
        html += '<div class="process-drawing-actions">';
        if (pngUrl) html += `<a class="btn btn-sm" href="${pngUrl}" target="_blank" download>下载 PNG</a>`;
        if (svgUrl) html += `<a class="btn btn-sm" href="${svgUrl}" target="_blank" download>下载 SVG</a>`;
        html += '</div>';
        html += '</article>';
    });
    html += '</div>';
    const jsonAsset = (plan.assets || []).find(asset => asset.asset_type === 'json' && asset.file_url);
    if (jsonAsset) {
        const jsonUrl = `${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/assets/${encodeURIComponent(jobId)}/${jsonAsset.file_url}`;
        html += `<p><a class="btn btn-sm" href="${jsonUrl}" target="_blank" download>下载工艺图计划 JSON</a></p>`;
    }
    return html;
}

function renderAnnotationProgressOverlay(status, startedAt, hasPreviousResult) {
    const rawStatus = String(status?.status || 'pending').toLowerCase();
    const progress = Math.max(0, Math.min(100, Number(status?.progress || 0)));
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    const stageLabel = {
        queued: '排队等待',
        rendering: '准备图纸页面',
        explaining: 'AI 精细图解',
        bubble_generating: '生成气泡图和导出数据',
        completed: '完成',
        failed: '失败',
    }[status?.stage] || status?.stage || '处理中';
    const preview = status?.ai_stream_preview ? String(status.ai_stream_preview).slice(-220) : '';
    return `
        <div class="case-annotation-overlay">
            <div class="case-annotation-progress-card">
                <div class="progress-panel-header">
                    <strong>正在刷新精细标注</strong>
                    <span>已等待 ${elapsedSeconds} 秒</span>
                </div>
                <div class="progress-current">
                    <span>${escapeHtml(stageLabel)}：${escapeHtml(status?.message || '精细标注任务正在运行')}</span>
                </div>
                <div class="case-annotation-progress-bar" aria-label="精细标注进度">
                    <span style="width:${progress}%"></span>
                </div>
                <div class="part-info-grid case-annotation-progress-meta">
                    <p><strong>任务状态：</strong>${escapeHtml(rawStatus)}</p>
                    <p><strong>当前阶段：</strong>${escapeHtml(stageLabel)}</p>
                    <p><strong>进度：</strong>${progress}%</p>
                    <p><strong>旧结果：</strong>${hasPreviousResult ? '已保留，成功后才覆盖' : '暂无旧结果'}</p>
                </div>
                ${preview ? `<div class="info"><strong>AI 返回片段：</strong>${escapeHtml(preview)}</div>` : ''}
                <div class="warning">刷新期间暂时遮挡旧页面；成功后自动展示新结果，失败时会显示失败原因并保留旧结果。</div>
            </div>
        </div>
    `;
}

async function fetchCaseAnnotationResult(caseId) {
    const resultResponse = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/result`);
    if (!resultResponse.ok) return null;
    return resultResponse.json();
}

async function refreshCaseAnnotation(caseId, caseData = null, options = {}) {
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
    const rawStatus = String(status.status || '').toLowerCase();
    const fallbackResult = options.fallbackResult || null;
    const overlayStartedAt = options.overlayStartedAt || Date.now();
    let result = fallbackResult;

    if (rawStatus === 'completed') {
        result = await fetchCaseAnnotationResult(caseId);
        renderCaseDetail(loadedCase, status, result);
        refreshCaseAnnotationSummary(caseId);
        return;
    }

    if (rawStatus === 'failed') {
        if (!result) {
            result = await fetchCaseAnnotationResult(caseId);
        }
        renderCaseDetail(loadedCase, status, result);
        refreshCaseAnnotationSummary(caseId);
        return;
    }

    if (rawStatus === 'pending' || rawStatus === 'running') {
        renderCaseDetail(loadedCase, status, result, {
            annotationOverlay: true,
            overlayStartedAt,
        });
        caseAnnotationPollTimer = setTimeout(
            () => refreshCaseAnnotation(caseId, loadedCase, { fallbackResult: result, overlayStartedAt }),
            3000,
        );
        return;
    }

    if (!result) {
        result = await fetchCaseAnnotationResult(caseId);
    }
    renderCaseDetail(loadedCase, status, result);
}

async function startCaseAnnotation(caseId) {
    const confirmed = confirm(
        '确认刷新精细标注吗？\n\n该操作会重新调用 AI 视觉模型，可能消耗较多 token。\n成功后新结果会覆盖旧结果；失败时旧结果会保留。'
    );
    if (!confirmed) return;

    const overlayStartedAt = Date.now();
    try {
        const caseResponse = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`);
        if (!caseResponse.ok) throw new Error(`HTTP ${caseResponse.status}: ${await caseResponse.text()}`);
        const caseData = await caseResponse.json();
        const previousResult = await fetchCaseAnnotationResult(caseId);
        renderCaseDetail(
            caseData,
            { status: 'pending', stage: 'queued', progress: 0, message: '正在提交精细标注刷新任务' },
            previousResult,
            { annotationOverlay: true, overlayStartedAt },
        );

        const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/annotations/retry`, { method: 'POST' });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        const job = await response.json();
        await refreshCaseAnnotation(caseId, caseData, {
            fallbackResult: previousResult,
            overlayStartedAt,
        });
        if (job?.reused) {
            refreshCaseAnnotationSummary(caseId);
        }
    } catch (error) {
        alert('启动精细标注失败：' + error.message);
        await refreshCaseAnnotation(caseId);
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
            ai_suggestions: caseData.generation_ai_response?.ai_suggestions || [],
            agent_trace: caseData.generation_ai_response?.agent_trace || null,
            generation_ai_response: caseData.generation_ai_response || null,
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
        const caseResponse = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`);
        if (!caseResponse.ok) throw new Error(`HTTP ${caseResponse.status}`);
        const caseData = await caseResponse.json();
        currentData = {
            loaded_case_name: caseData.case_name,
            parse_result: caseData.drawing_parse_result || {},
            process_plan: caseData.process_plan || { title: caseData.case_name || '案例工序方案', operations: [] },
            flow: {
                title: caseData.process_plan?.title || `案例流程：${caseData.case_name}`,
                mermaid: '',
            },
            similar_cases: [],
            ai_suggestions: caseData.generation_ai_response?.ai_suggestions || [],
            agent_trace: caseData.generation_ai_response?.agent_trace || null,
            process_guidance: caseData.generation_ai_response?.process_guidance || null,
            generation_ai_response: caseData.generation_ai_response || null,
            source_files: sourceFiles,
        };
        document.getElementById('input-method').value = 'file';
        toggleInputMethod();
        updateBoundCaseFilesHint();
        switchTab('generate', document.querySelector('.tab[data-tab="generate"]'));
        displayResult(currentData);
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
    clearAgentChat();
    document.getElementById('text-input').value = '';
    document.getElementById('json-input').value = '';
    document.getElementById('file-input').value = '';
    const fileInfo = document.getElementById('file-info');
    if (fileInfo) {
        fileInfo.style.display = 'none';
        fileInfo.innerHTML = '';
    }
    document.getElementById('generate-result').classList.remove('active');
}

Object.assign(window, {
    switchTab,
    toggleInputMethod,
    toggleAgentMode,
    sendAgentMessage,
    clearAgentChat,
    startNewAgentSession,
    handleAgentAction,
    generateProcess,
    clearForm,
    loadCases,
    setMermaidZoom,
    resetMermaidZoom,
    editCurrentPlan,
    editOperation,
    saveEditedPlan,
    cancelEdit,
    saveAsCase,
    refreshCaseAnnotationSummary,
    deleteCase,
    saveCaseReview,
    loadCase,
    refreshCaseAnnotation,
    startCaseAnnotation,
    loadCaseForEdit,
    loadCaseToAnalysis,
    downloadMarkdown,
});

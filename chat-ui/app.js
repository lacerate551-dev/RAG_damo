// ===== 配置 =====
const DEFAULT_API_BASE = 'http://localhost:5001';
let API_BASE = localStorage.getItem('rag_api_base') || DEFAULT_API_BASE;
const TOKEN_KEY = 'rag_auth_token';
const USER_KEY = 'rag_auth_user';
const LOG_KEY = 'rag_chat_logs';

// ===== 状态 =====
const state = {
    token: localStorage.getItem(TOKEN_KEY),
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
    sessionId: null,
    mode: 'chat',  // 'chat' 或 'rag'
    sessions: [],
    messages: {},
    logs: JSON.parse(localStorage.getItem(LOG_KEY) || '[]'),
    systemStatus: {
        knowledgeBase: null,
        bm25Index: null,
        graph: null
    },
    // 新增状态
    collections: [],
    currentMessage: null,  // 当前消息（用于反馈）
    feedbackRating: 1,     // 反馈评分
    selectedFiles: []      // 上传文件列表
};

// ===== DOM =====
const $ = id => document.getElementById(id);

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    // 恢复配置
    const apiInput = $('apiBaseUrl');
    if (apiInput) apiInput.value = API_BASE;
    checkAuth();
    initEvents();
    renderLogs();
});

window.updateApiBase = function(url) {
    if (!url) url = DEFAULT_API_BASE;
    if (url.endsWith('/')) url = url.slice(0, -1);
    localStorage.setItem('rag_api_base', url);
    alert('API 地址已更新，将刷新页面。');
    location.reload();
};

function checkAuth() {
    if (state.token && state.user) {
        showMain();
    } else {
        showLogin();
    }
}

function showLogin() {
    $('loginPanel').style.display = 'flex';
    $('mainContent').style.display = 'none';
}

function showMain() {
    $('loginPanel').style.display = 'none';
    $('mainContent').style.display = 'flex';
    $('username').textContent = state.user.username;
    $('userRole').textContent = getRoleLabel(state.user.role);
    $('userRole').className = `role ${state.user.role}`;
    updateModeUI();
    loadSessions();
    loadSystemStatus();

    // 显示管理员功能
    if (state.user.role === 'admin') {
        $('adminSection').style.display = 'block';
        $('statsPanel').style.display = 'block';
        $('createKbBtn').style.display = 'inline-block';
    }

    // 加载知识库面板数据
    loadCollections();
    loadDocuments();
    loadFeedbackStats();
    loadSyncStatus();
}

function getRoleLabel(role) {
    const labels = { admin: '管理员', manager: '经理', user: '用户' };
    return labels[role] || role;
}

// ===== 事件绑定 =====
function initEvents() {
    // 登录
    $('loginForm').addEventListener('submit', handleLogin);

    // 登出
    $('logoutBtn').addEventListener('click', handleLogout);

    // 设置弹窗
    $('settingsBtn').addEventListener('click', () => $('settingsModal').style.display = 'flex');
    $('closeSettingsBtn').addEventListener('click', () => $('settingsModal').style.display = 'none');
    $('changePasswordForm').addEventListener('submit', handleChangePassword);

    // 模式切换
    $('chatModeBtn').addEventListener('click', () => setMode('chat'));
    $('ragModeBtn').addEventListener('click', () => setMode('rag'));

    // 发送消息
    $('sendBtn').addEventListener('click', sendMessage);
    $('messageInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // 新建会话
    $('newSessionBtn').addEventListener('click', newSession);

    // 日志面板
    $('clearLogBtn').addEventListener('click', clearLogs);
    $('toggleLogPanelBtn').addEventListener('click', toggleLogPanel);

    // 管理员功能
    $('showUsersBtn')?.addEventListener('click', showUsersModal);
    $('closeUsersBtn')?.addEventListener('click', () => $('usersModal').style.display = 'none');
    $('showAuditLogsBtn')?.addEventListener('click', showAuditLogsModal);
    $('closeAuditBtn')?.addEventListener('click', () => $('auditModal').style.display = 'none');
    $('refreshAuditBtn')?.addEventListener('click', loadAuditLogs);
    $('buildGraphBtn')?.addEventListener('click', buildKnowledgeGraph);

    // 点击弹窗外部关闭
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.style.display = 'none';
        });
    });

    // 文件上传拖拽
    const uploadArea = $('fileUploadArea');
    if (uploadArea) {
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            handleFileSelect(e.dataTransfer.files);
        });
        $('uploadFileInput').addEventListener('change', (e) => {
            handleFileSelect(e.target.files);
        });
    }

    // 反馈原因选择
    document.querySelectorAll('input[name="feedbackReason"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            $('otherReasonInput').style.display = e.target.value === 'other' ? 'block' : 'none';
        });
    });
}

// ===== 认证处理 =====
async function handleLogin(e) {
    e.preventDefault();
    const username = $('loginUsername').value.trim();
    const password = $('loginPassword').value;
    if (!username || !password) return;

    try {
        $('loginError').textContent = '';
        const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '登录失败');

        state.token = data.token;
        state.user = data.user;
        localStorage.setItem(TOKEN_KEY, data.token);
        localStorage.setItem(USER_KEY, JSON.stringify(data.user));
        showMain();
        showToast('登录成功', 'success');
    } catch (err) {
        $('loginError').textContent = err.message;
    }
}

function handleLogout() {
    state.token = null;
    state.user = null;
    state.sessionId = null;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    showLogin();
    showToast('已退出登录');
}

async function handleChangePassword(e) {
    e.preventDefault();
    const oldPassword = $('oldPassword').value;
    const newPassword = $('newPassword').value;
    const confirmPassword = $('confirmPassword').value;

    if (newPassword !== confirmPassword) {
        $('passwordError').textContent = '两次输入的密码不一致';
        return;
    }

    try {
        await api('/auth/change-password', {
            method: 'POST',
            body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
        });
        $('passwordError').textContent = '';
        $('changePasswordForm').reset();
        showToast('密码修改成功', 'success');
    } catch (err) {
        $('passwordError').textContent = err.message;
    }
}

// ===== 模式切换 =====
function setMode(mode) {
    state.mode = mode;
    updateModeUI();
}

function updateModeUI() {
    const chatBtn = $('chatModeBtn');
    const ragBtn = $('ragModeBtn');
    if (state.mode === 'chat') {
        chatBtn.classList.add('chat-mode');
        chatBtn.classList.remove('rag-mode');
        chatBtn.style.background = '#4a90d9';
        chatBtn.style.color = 'white';
        ragBtn.style.background = '#ccc';
        ragBtn.style.color = '#666';
    } else {
        ragBtn.classList.add('rag-mode');
        ragBtn.classList.remove('chat-mode');
        ragBtn.style.background = '#e67e22';
        ragBtn.style.color = 'white';
        chatBtn.style.background = '#ccc';
        chatBtn.style.color = '#666';
    }
}

// ===== API 封装 =====
async function api(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }

    const res = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers
    });

    if (res.status === 401) {
        showToast('登录已过期，请重新登录', 'error');
        handleLogout();
        throw new Error('Unauthorized');
    }

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

// ===== 系统状态 =====
async function loadSystemStatus() {
    try {
        // 健康检查（无需认证）
        const health = await fetch(`${API_BASE}/health`).then(r => r.json());
        $('kbStatus').textContent = health.knowledge_base || '-';
        $('kbStatus').className = 'status-value success';
        $('bm25Status').textContent = health.bm25_index || '-';
        $('bm25Status').className = health.bm25_index !== '未加载' ? 'status-value success' : 'status-value error';

        // 图谱状态
        try {
            const graphStats = await api('/graph/stats');
            if (graphStats.enabled && graphStats.connected) {
                $('graphStatus').textContent = `${graphStats.nodes}节点 / ${graphStats.edges}边`;
                $('graphStatus').className = 'status-value success';
            } else {
                $('graphStatus').textContent = graphStats.message || '未连接';
                $('graphStatus').className = 'status-value error';
            }
        } catch {
            $('graphStatus').textContent = '未启用';
            $('graphStatus').className = 'status-value';
        }
    } catch (err) {
        console.error('加载系统状态失败:', err);
    }
}

// ===== 消息发送 =====
async function sendMessage() {
    const input = $('messageInput');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    $('sendBtn').disabled = true;

    // 添加用户消息
    addMessage('user', msg);

    try {
        if (state.mode === 'chat') {
            // 聊天模式
            const data = await api('/chat', {
                method: 'POST',
                body: JSON.stringify({ session_id: state.sessionId, message: msg })
            });
            state.sessionId = data.session_id;
            $('currentSessionId').textContent = state.sessionId ? state.sessionId.substring(0, 8) : '新会话';
            addMessage('assistant', data.answer, data.sources, data.web_searched, false, data.images);
            loadSessions();
        } else {
            // RAG 模式（SSE流式）
            await sendRagMessage(msg);
        }
    } catch (err) {
        addMessage('assistant', `错误: ${err.message}`);
    }

    $('sendBtn').disabled = false;
    input.focus();
}

async function sendRagMessage(msg) {
    // 使用合并后的 /rag 端点（SSE 流式返回）
    const res = await fetch(`${API_BASE}/rag`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${state.token}`
        },
        body: JSON.stringify({
            message: msg,
            collections: ['public_kb'],
            session_id: state.sessionId
        })
    });

    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || '请求失败');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let result = null;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const event = JSON.parse(line.slice(6));
                    handleStreamEvent(event);
                    // 新规范使用 'finish' 事件类型
                    if (event.type === 'finish') {
                        result = event;
                    }
                } catch (e) {}
            }
        }
    }

    // 流式输出完成后，替换占位符为最终消息
    if (result) {
        state.sessionId = result.session_id;
        $('currentSessionId').textContent = state.sessionId ? state.sessionId.substring(0, 8) : '新会话';
        // 替换流式占位符为最终消息
        finalizeStreamMessage(result.answer, result.sources, result.images, result.citations);
        loadSessions();
    }
}

// 流式输出相关变量
let streamingMessageEl = null;
let streamingContent = '';

function handleStreamEvent(event) {
    const type = event.type;
    let msg = '';
    switch (type) {
        case 'start':
            msg = event.message || '开始处理...';
            // 创建流式消息占位符
            createStreamingPlaceholder();
            break;
        case 'sources':
            msg = `检索到 ${event.sources?.length || 0} 个来源`;
            break;
        case 'chunk':
            // 追加内容到流式消息
            if (event.content) {
                appendStreamingContent(event.content);
            }
            break;
        case 'decision': msg = `决策: ${event.action}`; break;
        case 'rewrite': msg = `重写: ${event.new_query || event.rewritten_query || ''}`; break;
        case 'decompose': msg = `分解查询: ${event.sub_queries?.join(', ') || ''}`; break;
        case 'retrieve': msg = `检索${event.source ? '(' + event.source + ')' : ''}: ${event.query || ''}`; break;
        case 'answer': msg = '生成回答...'; break;
        case 'warning': msg = `警告: ${event.message || ''}`; break;
        case 'max_iterations': msg = '达到最大迭代次数'; break;
        case 'finish': msg = '处理完成'; break;
        case 'complete': msg = '处理完成'; break;
        case 'error':
            msg = `错误: ${event.message || ''}`;
            // 错误时清理占位符
            clearStreamingPlaceholder();
            break;
        default: msg = type;
    }
    if (msg) addLog(type, msg, event);
}

function createStreamingPlaceholder() {
    const container = $('chatMessages');
    // 移除空状态
    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    // 创建流式消息占位符
    const div = document.createElement('div');
    div.className = 'message assistant streaming';
    div.id = 'streaming-message';
    div.innerHTML = `
        <div class="message-header">
            <span class="role-icon">🤖</span>
            <span class="role-name">AI 助手</span>
            <span class="streaming-indicator">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
            </span>
        </div>
        <div class="message-content" id="streaming-content">
            <span class="typing-cursor">▌</span>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;

    streamingMessageEl = div;
    streamingContent = '';
}

function appendStreamingContent(content) {
    if (!streamingMessageEl) return;

    streamingContent += content;
    const contentEl = $('streaming-content');
    if (contentEl) {
        // 解析 Markdown 并显示
        contentEl.innerHTML = renderMarkdown(streamingContent) + '<span class="typing-cursor">▌</span>';

        // 滚动到底部
        const container = $('chatMessages');
        container.scrollTop = container.scrollHeight;
    }
}

function finalizeStreamMessage(answer, sources, images, citations) {
    if (streamingMessageEl) {
        // 移除流式指示器
        streamingMessageEl.classList.remove('streaming');
        streamingMessageEl.removeAttribute('id');

        // 使用完整的消息格式
        const formatted = formatMessage(answer, sources, false, true, images, citations);
        streamingMessageEl.innerHTML = formatted;

        streamingMessageEl = null;
        streamingContent = '';
    }
}

function clearStreamingPlaceholder() {
    if (streamingMessageEl) {
        streamingMessageEl.remove();
        streamingMessageEl = null;
        streamingContent = '';
    }
}

function addMessage(role, content, sources, webSearched, isRag, images, citations) {
    const container = $('chatMessages');
    // 移除空状态
    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    const messageId = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    div.dataset.messageId = messageId;

    let html = '';

    // 消息头部标签
    if (role === 'assistant') {
        html += '<div class="message-header">';
        if (isRag) {
            html += '<span class="mode-tag">知识库</span>';
        }
        if (webSearched) {
            html += '<span class="web-tag">网络搜索</span>';
        }
        html += '</div>';
    }

    if (role === 'assistant') {
        html += `<div class="message-content">${renderMarkdown(content)}</div>`;
    } else {
        html += `<div class="message-content">${escapeHtml(content)}</div>`;
    }

    // 显示图片
    if (images && images.length > 0) {
        html += '<div class="message-images"><strong>相关图片:</strong><div class="images-grid">';
        images.forEach(img => {
            const caption = img.caption ? `<div class="image-caption">${escapeHtml(img.caption)}</div>` : '';
            const pageLabel = img.page ? `<span class="image-page">第${img.page}页</span>` : '';
            html += `
                <div class="image-card">
                    <img src="${typeof API_BASE !== 'undefined' ? API_BASE : ''}${img.url}" alt="${img.id}" loading="lazy" onclick="window.showImageModal('${typeof API_BASE !== 'undefined' ? API_BASE : ''}${img.url}', '${escapeHtml(img.id)}')">
                    <div class="image-info">
                        ${pageLabel}
                        ${caption}
                    </div>
                </div>
            `;
        });
        html += '</div></div>';
    }

    // 显示来源
    if (sources && sources.length > 0) {
        html += '<div class="message-sources"><strong>来源:</strong><br>';
        sources.forEach((s, i) => {
            const level = s.security_level || s.level || '';
            const levelTag = level ? `<span class="security-tag ${level}">${level}</span>` : '';

            // 解析 source 字符串（可能已包含位置信息）
            const sourceText = s.source || s;
            const docType = s.doc_type || 'other';
            const previews = s.previews || [];
            const sectionChunkId = s.section_chunk_id;

            html += `<div class="source-item-detailed" data-doc-type="${docType}">`;
            html += `${levelTag}📄 <strong>${escapeHtml(sourceText)}</strong>`;

            // 根据文档类型差异化展示定位信息
            if (docType === 'pdf') {
                // PDF: 页码信息已在 sourceText 中
            } else if (docType === 'word') {
                // Word: 显示章节内段落信息
                if (sectionChunkId) {
                    html += `<br><span class="location-hint">🔢 段落: 第${sectionChunkId}段（本章节）</span>`;
                }
            } else if (docType === 'excel') {
                // Excel: 工作表信息已在 sourceText 中
            }

            // 所有文档类型都显示搜索片段（帮助用户定位）
            if (previews.length > 0) {
                html += `<br><span class="search-hint">🔍 搜索: "${escapeHtml(previews[0])}"</span>`;
            }

            html += `</div>`;
        });
        html += '</div>';
    }

    // 添加消息操作栏（仅 AI 回复）
    if (role === 'assistant') {
        html += `
            <div class="message-actions">
                <button class="action-btn upvote" onclick="openFeedbackModal('${messageId}', 1)" title="有帮助">👍</button>
                <button class="action-btn downvote" onclick="openFeedbackModal('${messageId}', -1)" title="没帮助">👎</button>
                <button class="action-btn exam-btn" onclick="createExamFromChat('${messageId}')" title="基于此对话出题">📝 出题</button>
            </div>
        `;
    }

    div.innerHTML = html;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;

    // 保存消息数据（用于反馈）
    if (role === 'assistant') {
        div.dataset.content = content;
        div.dataset.sources = JSON.stringify(sources || []);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 展开/收起引用内容
function toggleCitationContent(contentId) {
    const preview = document.getElementById(contentId);
    const fullContent = document.getElementById(contentId + '-full');
    const btn = preview.parentElement.querySelector('.citation-expand-btn');

    if (fullContent.style.display === 'none') {
        // 展开
        preview.style.display = 'none';
        fullContent.style.display = 'block';
        btn.textContent = '收起';
    } else {
        // 收起
        preview.style.display = 'inline';
        fullContent.style.display = 'none';
        btn.textContent = '展开';
    }
}

// 简单的 Markdown 渲染（用于流式输出）
function renderMarkdown(text) {
    if (!text) return '';

    // 先提取 <sup> 标签，避免被转义
    const supPlaceholders = [];
    let processedText = text.replace(/<sup class="citation-ref"[^>]*data-chunk-id="[^"]*"[^>]*>\[[^\]]+\]<\/sup>/g, (match) => {
        supPlaceholders.push(match);
        return `__SUP_PLACEHOLDER_${supPlaceholders.length - 1}__`;
    });

    // 转义 HTML（除了我们提取的 <sup> 标签）
    let html = escapeHtml(processedText);

    // 恢复 <sup> 标签
    supPlaceholders.forEach((sup, i) => {
        html = html.replace(`__SUP_PLACEHOLDER_${i}__`, sup);
    });

    // 图片
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, url) => {
        const fullUrl = url.startsWith('http') ? url : `${typeof API_BASE !== 'undefined' ? API_BASE : ''}/${url.replace(/^\//, '')}`;
        return `<img src="${fullUrl}" alt="${alt}" loading="lazy" onclick="window.showImageModal('${fullUrl}', '${alt}')" style="max-width: 100%; max-height: 400px; border-radius: 4px; margin: 8px 0; cursor: zoom-in;">`;
    });

    // 链接
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

    // 代码块
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');

    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 标题
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // 粗体和斜体
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // 列表
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // 段落
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');

    return html;
}

// 格式化消息（用于流式输出完成后的最终显示）
function formatMessage(content, sources, webSearched, isRag, images, citations) {
    const messageId = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    let html = '';

    // 消息头部标签
    html += '<div class="message-header">';
    html += '<span class="role-icon">🤖</span>';
    html += '<span class="role-name">AI 助手</span>';
    if (isRag) {
        html += '<span class="mode-tag">知识库</span>';
    }
    if (webSearched) {
        html += '<span class="web-tag">网络搜索</span>';
    }
    html += '</div>';

    // 处理引用标注：将 [ref:chunk_id] 替换为编号
    let processedContent = content;
    const citationMap = {};
    const orderedCitations = []; // 按内容中出现顺序排列的引用

    if (citations && citations.length > 0) {
        // 先建立 chunk_id -> citation 的映射
        const citationByChunkId = {};
        citations.forEach(c => {
            citationByChunkId[c.chunk_id] = c;
        });

        // 按内容中出现的顺序收集引用（去重）
        const seenChunks = new Set();
        const refPattern = /\[ref:([^\]]+)\]/g;
        let match;
        while ((match = refPattern.exec(content)) !== null) {
            const chunkId = match[1];
            if (!seenChunks.has(chunkId) && citationByChunkId[chunkId]) {
                seenChunks.add(chunkId);
                orderedCitations.push(citationByChunkId[chunkId]);
                citationMap[chunkId] = orderedCitations.length; // 按出现顺序编号
            }
        }

        // 替换 [ref:chunk_id] 为可点击的编号
        processedContent = content.replace(/\[ref:([^\]]+)\]/g, (match, chunkId) => {
            const num = citationMap[chunkId];
            if (num) {
                return `<sup class="citation-ref" data-chunk-id="${chunkId}">[${num}]</sup>`;
            }
            return '';
        });
    }

    html += `<div class="message-content">${renderMarkdown(processedContent)}</div>`;

    // 显示图片
    if (images && images.length > 0) {
        html += '<div class="message-images"><strong>相关图片:</strong><div class="images-grid">';
        images.forEach(img => {
            const caption = img.caption ? `<div class="image-caption">${escapeHtml(img.caption)}</div>` : '';
            const pageLabel = img.page ? `<span class="image-page">第${img.page}页</span>` : '';
            html += `
                <div class="image-card">
                    <img src="${API_BASE}${img.url}" alt="${img.id}" loading="lazy" onclick="showImageModal('${API_BASE}${img.url}', '${escapeHtml(img.id)}')">
                    <div class="image-info">
                        ${pageLabel}
                        ${caption}
                    </div>
                </div>
            `;
        });
        html += '</div></div>';
    }

    // 显示引用列表（按内容中出现顺序，只显示实际被引用的）
    if (orderedCitations.length > 0) {
        html += '<div class="message-citations"><strong>引用来源:</strong><ol class="citations-list">';
        orderedCitations.forEach((c, i) => {
            const docType = c.doc_type || 'other';
            let locationInfo = '';
            let icon = '📄';

            if (docType === 'pdf') {
                icon = '📕';
                if (c.page) {
                    locationInfo = `第${c.page}页`;
                    if (c.page_end && c.page_end !== c.page) {
                        locationInfo += `-${c.page_end}页`;
                    }
                }
            } else if (docType === 'word') {
                icon = '📘';
                if (c.section_chunk_id) {
                    locationInfo = `第${c.section_chunk_id}段`;
                }
            } else if (docType === 'excel') {
                icon = '📗';
                if (c.page) {
                    locationInfo = `工作表${c.page}`;
                }
            }

            // 完整内容（用于展开查看）
            const fullContent = c.content || c.preview || '';
            // 截断 preview 到 50 字符（用于默认显示）
            let preview = c.preview || '';
            if (preview.length > 50) {
                preview = preview.substring(0, 50) + '...';
            }

            html += `<li class="citation-item" data-doc-type="${docType}" data-chunk-id="${c.chunk_id}">`;
            html += `<span class="citation-source">${icon} ${escapeHtml(c.source || '未知')}</span>`;
            if (locationInfo) {
                html += `<span class="citation-location"> (${locationInfo})</span>`;
            }
            if (c.section) {
                html += `<br><span class="citation-section">${escapeHtml(c.section)}</span>`;
            }
            // 可展开的内容预览
            if (fullContent) {
                const contentId = `citation-content-${Date.now()}-${i}`;
                html += `<br><div class="citation-content-wrapper">`;
                html += `<span class="citation-preview collapsed" id="${contentId}">"${escapeHtml(preview)}"</span>`;
                html += `<div class="citation-full-content" id="${contentId}-full" style="display:none;">"${escapeHtml(fullContent)}"</div>`;
                html += `<button class="citation-expand-btn" onclick="toggleCitationContent('${contentId}')">展开</button>`;
                html += `</div>`;
            }
            html += '</li>';
        });
        html += '</ol></div>';
    } else if (sources && sources.length > 0) {
        // 兼容旧格式：显示来源
        html += '<div class="message-sources"><strong>来源:</strong><br>';
        sources.forEach((s, i) => {
            const level = s.security_level || s.level || '';
            const levelTag = level ? `<span class="security-tag ${level}">${level}</span>` : '';

            // 解析 source 字符串（可能已包含位置信息）
            const sourceText = s.source || s;
            const docType = s.doc_type || 'other';
            const previews = s.previews || [];
            const sectionChunkId = s.section_chunk_id;

            html += `<div class="source-item-detailed" data-doc-type="${docType}">`;
            html += `${levelTag}📄 <strong>${escapeHtml(sourceText)}</strong>`;

            // 根据文档类型差异化展示定位信息
            if (docType === 'pdf') {
                // PDF: 页码信息已在 sourceText 中
            } else if (docType === 'word') {
                // Word: 显示章节内段落信息
                if (sectionChunkId) {
                    html += `<br><span class="location-hint">🔢 段落: 第${sectionChunkId}段（本章节）</span>`;
                }
            } else if (docType === 'excel') {
                // Excel: 工作表信息已在 sourceText 中
            }

            // 所有文档类型都显示搜索片段（帮助用户定位）
            if (previews.length > 0) {
                html += `<br><span class="search-hint">🔍 搜索: "${escapeHtml(previews[0])}"</span>`;
            }

            html += `</div>`;
        });
        html += '</div>';
    }

    // 添加消息操作栏
    html += `
        <div class="message-actions">
            <button class="action-btn upvote" onclick="openFeedbackModal('${messageId}', 1)" title="有帮助">👍</button>
            <button class="action-btn downvote" onclick="openFeedbackModal('${messageId}', -1)" title="没帮助">👎</button>
            <button class="action-btn exam-btn" onclick="createExamFromChat('${messageId}')" title="基于此对话出题">📝 出题</button>
        </div>
    `;

    return html;
}

// ===== 会话管理 =====
async function loadSessions() {
    try {
        const data = await api('/sessions');
        state.sessions = data.sessions || [];
        renderSessions();
    } catch (err) {
        console.error('加载会话失败:', err);
    }
}

function renderSessions() {
    const container = $('sessionList');
    if (!state.sessions.length) {
        container.innerHTML = '<div class="empty-state">暂无会话</div>';
        return;
    }

    container.innerHTML = state.sessions.map(s => `
        <div class="session-item ${s.session_id === state.sessionId ? 'active' : ''}" data-id="${s.session_id}">
            <span class="session-preview">${escapeHtml(s.preview || s.session_id.substring(0, 8))}</span>
            <span class="session-time">${formatTime(s.last_active || s.created_at)}</span>
            <button class="delete-btn" data-id="${s.session_id}" title="删除">×</button>
        </div>
    `).join('');

    // 点击加载会话
    container.querySelectorAll('.session-item').forEach(el => {
        el.addEventListener('click', (e) => {
            if (e.target.classList.contains('delete-btn')) return;
            const id = el.dataset.id;
            state.sessionId = id;
            $('currentSessionId').textContent = id.substring(0, 8);
            loadHistory(id);
            renderSessions();
        });
    });

    // 删除会话
    container.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = e.target.dataset.id;
            if (!confirm('确定删除此会话吗？')) return;

            try {
                await api(`/session/${id}`, { method: 'DELETE' });
                if (state.sessionId === id) {
                    newSession();
                }
                loadSessions();
                showToast('会话已删除', 'success');
            } catch (err) {
                showToast('删除失败: ' + err.message, 'error');
            }
        });
    });
}

function newSession() {
    state.sessionId = null;
    $('currentSessionId').textContent = '新会话';
    $('chatMessages').innerHTML = '<div class="empty-state"><h3>新会话</h3><p>输入问题开始对话</p></div>';
}

async function loadHistory(sessionId) {
    try {
        const data = await api(`/history/${sessionId}`);
        state.messages[sessionId] = data.history || [];
        renderMessages(sessionId);
    } catch (err) {
        console.error('加载历史失败:', err);
    }
}

function renderMessages(sessionId) {
    const container = $('chatMessages');
    const messages = state.messages[sessionId] || [];

    if (!messages.length) {
        container.innerHTML = '<div class="empty-state"><h3>新会话</h3><p>输入问题开始对话</p></div>';
        return;
    }

    container.innerHTML = '';
    
    messages.forEach(m => {
        const meta = m.metadata || {};
        addMessage(
            m.role,
            m.content,
            meta.sources || [],
            meta.web_searched || false,
            meta.is_rag || false,
            meta.images || [],
            meta.citations || []  // 修复：从会话历史恢复引用信息
        );
    });
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
    return `${date.getMonth() + 1}/${date.getDate()}`;
}

// ===== 日志管理 =====
function addLog(type, msg, data) {
    state.logs.push({
        type, msg, data,
        time: new Date().toLocaleTimeString()
    });
    if (state.logs.length > 200) state.logs = state.logs.slice(-200);
    localStorage.setItem(LOG_KEY, JSON.stringify(state.logs));
    renderLogs();
}

function renderLogs() {
    const container = $('logPanelContent');
    if (!state.logs.length) {
        container.innerHTML = '<div class="log-empty">暂无日志</div>';
        return;
    }
    container.innerHTML = state.logs.slice(-50).map(l => `
        <div class="log-entry log-${l.type}">
            <div class="log-header">
                <span class="log-type">${l.type}</span>
                <span class="log-time">${l.time}</span>
            </div>
            <div class="log-content">${escapeHtml(l.msg)}</div>
        </div>
    `).join('');
    container.scrollTop = container.scrollHeight;
}

function clearLogs() {
    state.logs = [];
    localStorage.removeItem(LOG_KEY);
    renderLogs();
}

function toggleLogPanel() {
    $('logPanel').classList.toggle('collapsed');
    $('toggleLogPanelBtn').textContent = $('logPanel').classList.contains('collapsed') ? '▶' : '◀';
}

// ===== 管理员功能 =====
async function showUsersModal() {
    $('usersModal').style.display = 'flex';
    try {
        const data = await api('/auth/users');
        renderUsers(data.users || []);
    } catch (err) {
        showToast('加载用户列表失败', 'error');
    }
}

function renderUsers(users) {
    const tbody = $('usersTableBody');
    tbody.innerHTML = users.map(u => `
        <tr>
            <td>${escapeHtml(u.username)}</td>
            <td>${getRoleLabel(u.role)}</td>
            <td>${escapeHtml(u.department || '-')}</td>
            <td><span class="user-status ${u.is_active ? 'active' : 'inactive'}">${u.is_active ? '活跃' : '禁用'}</span></td>
            <td>
                <button class="btn btn-sm btn-secondary" onclick="toggleUserStatus('${u.user_id}', ${!u.is_active})">${u.is_active ? '禁用' : '启用'}</button>
            </td>
        </tr>
    `).join('');
}

async function toggleUserStatus(userId, isActive) {
    try {
        await api(`/auth/users/${userId}`, {
            method: 'PUT',
            body: JSON.stringify({ is_active: isActive })
        });
        showUsersModal();
        showToast(`用户已${isActive ? '启用' : '禁用'}`, 'success');
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

async function showAuditLogsModal() {
    $('auditModal').style.display = 'flex';
    loadAuditLogs();
}

async function loadAuditLogs() {
    const action = $('auditActionFilter').value;
    try {
        const params = new URLSearchParams({ limit: 50, days: 7 });
        if (action) params.append('action', action);
        const data = await api(`/audit/logs?${params}`);
        renderAuditLogs(data.logs || []);
    } catch (err) {
        showToast('加载审计日志失败', 'error');
    }
}

function renderAuditLogs(logs) {
    const container = $('auditList');
    if (!logs.length) {
        container.innerHTML = '<div class="empty-state">暂无日志</div>';
        return;
    }
    container.innerHTML = logs.map(log => `
        <div class="audit-entry">
            <div class="audit-header">
                <span class="audit-action">${log.action || '-'}</span>
                <span class="audit-time">${log.timestamp || '-'}</span>
            </div>
            <div class="audit-user">用户: ${log.username || '-'} (${log.role || '-'})</div>
            <div class="audit-query" style="color: var(--text-color); margin-top: 4px;">${escapeHtml(log.query || '-')}</div>
        </div>
    `).join('');
}

async function buildKnowledgeGraph() {
    if (!confirm('确定要重建知识图谱吗？这可能需要一些时间。')) return;

    showToast('开始构建知识图谱...', 'info');
    try {
        const result = await api('/graph/build', { method: 'POST' });
        showToast(result.message || '知识图谱构建完成', 'success');
        loadSystemStatus();
    } catch (err) {
        showToast('构建失败: ' + err.message, 'error');
    }
}

// ===== Toast 提示 =====
function showToast(message, type = 'info') {
    const toast = $('toast');
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

// ===== 图片弹窗 =====
function showImageModal(url, caption) {
    const modal = $('imageModal');
    const img = $('modalImage');
    const captionEl = $('modalCaption');

    img.src = url;
    captionEl.textContent = caption || '';
    modal.style.display = 'flex';

    // 点击背景关闭
    modal.onclick = (e) => {
        if (e.target === modal) closeImageModal();
    };
}

function closeImageModal() {
    $('imageModal').style.display = 'none';
}

// ESC 键关闭弹窗
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeImageModal();
});

// 暴露给 HTML 的全局函数
window.toggleUserStatus = toggleUserStatus;
window.showImageModal = showImageModal;
window.closeImageModal = closeImageModal;

// ===== 反馈系统 =====

// 打开反馈弹窗
function openFeedbackModal(messageId, rating) {
    const messageEl = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageEl) return;

    state.currentMessage = {
        id: messageId,
        content: messageEl.dataset.content || messageEl.querySelector('.message-content')?.textContent || '',
        sources: JSON.parse(messageEl.dataset.sources || '[]')
    };
    state.feedbackRating = rating;

    // 找到对应的用户问题
    const prevMessage = messageEl.previousElementSibling;
    const userQuery = prevMessage?.querySelector('.message-content')?.textContent || '';

    state.currentMessage.query = userQuery;

    $('feedbackModal').style.display = 'flex';
    selectFeedbackRating(rating);
}

function closeFeedbackModal() {
    $('feedbackModal').style.display = 'none';
    // 重置表单
    document.querySelectorAll('input[name="feedbackReason"]').forEach(r => r.checked = false);
    $('otherReasonInput').style.display = 'none';
    $('feedbackComment').value = '';
    $('otherReasonText').value = '';
}

function selectFeedbackRating(rating) {
    state.feedbackRating = rating;
    document.querySelectorAll('.rating-btn').forEach(btn => {
        btn.classList.remove('active');
        if (parseInt(btn.dataset.rating) === rating) {
            btn.classList.add('active');
        }
    });

    // 点踩时显示原因选择
    $('feedbackReasonSection').style.display = rating === -1 ? 'block' : 'none';
}

async function submitFeedbackForm() {
    if (!state.currentMessage) return;

    const rating = state.feedbackRating;
    let reason = '';

    if (rating === -1) {
        const selectedReason = document.querySelector('input[name="feedbackReason"]:checked');
        if (selectedReason) {
            reason = selectedReason.value === 'other' ? $('otherReasonText').value : selectedReason.value;
        }
    }

    const comment = $('feedbackComment').value;

    try {
        await api('/feedback', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId || 'anonymous',
                query: state.currentMessage.query,
                answer: state.currentMessage.content,
                rating: rating,
                reason: reason || comment,
                sources: state.currentMessage.sources,
                user_id: state.user?.user_id || ''
            })
        });

        closeFeedbackModal();
        showToast('感谢您的反馈！', 'success');

        // 更新按钮状态
        const messageEl = document.querySelector(`[data-message-id="${state.currentMessage.id}"]`);
        if (messageEl) {
            const btn = messageEl.querySelector(rating === 1 ? '.upvote' : '.downvote');
            if (btn) {
                btn.classList.add('voted');
                btn.disabled = true;
            }
        }

        // 刷新统计
        loadFeedbackStats();
    } catch (err) {
        showToast('提交失败: ' + err.message, 'error');
    }
}

// 反馈统计
async function loadFeedbackStats() {
    if (state.user?.role !== 'admin') return;

    try {
        const stats = await api('/feedback/stats');
        const statsData = stats.stats || {};

        $('weeklyQueries').textContent = statsData.total_queries || 0;

        const likeRate = statsData.total_queries > 0
            ? Math.round((statsData.positive_count || 0) / statsData.total_queries * 100)
            : 0;
        $('weeklyLikeRate').textContent = `${likeRate}%`;

        // 获取待审核FAQ数
        try {
            const faqSuggestions = await api('/faq/suggestions?status=pending');
            $('pendingFaqs').textContent = faqSuggestions.total || 0;
        } catch {
            $('pendingFaqs').textContent = '0';
        }
    } catch (err) {
        console.error('加载反馈统计失败:', err);
    }
}

function showFeedbackStatsModal() {
    $('feedbackStatsModal').style.display = 'flex';
    showStatsTab('overview');
}

function closeFeedbackStatsModal() {
    $('feedbackStatsModal').style.display = 'none';
}

async function showStatsTab(tab) {
    document.querySelectorAll('.stats-tabs .tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');

    const content = $('statsTabContent');
    content.innerHTML = '<div class="loading">加载中...</div>';

    try {
        if (tab === 'overview') {
            const stats = await api('/feedback/stats');
            const weekly = await api('/reports/weekly');
            content.innerHTML = `
                <div class="stats-overview">
                    <div class="stat-card">
                        <h4>本周统计</h4>
                        <p>总查询: ${stats.stats?.total_queries || 0}</p>
                        <p>好评: ${stats.stats?.positive_count || 0}</p>
                        <p>差评: ${stats.stats?.negative_count || 0}</p>
                    </div>
                    <div class="stat-card">
                        <h4>周报摘要</h4>
                        <pre>${JSON.stringify(weekly.report || {}, null, 2)}</pre>
                    </div>
                </div>
            `;
        } else if (tab === 'feedbacks') {
            const feedbacks = await api('/feedback/list?limit=50');
            content.innerHTML = `
                <div class="feedback-list">
                    ${(feedbacks.feedbacks || []).map(f => `
                        <div class="feedback-item ${f.rating === 1 ? 'positive' : 'negative'}">
                            <div class="feedback-header">
                                <span class="feedback-rating">${f.rating === 1 ? '👍' : '👎'}</span>
                                <span class="feedback-time">${f.created_at || ''}</span>
                            </div>
                            <div class="feedback-query">${escapeHtml(f.query || '')}</div>
                            ${f.reason ? `<div class="feedback-reason">原因: ${escapeHtml(f.reason)}</div>` : ''}
                        </div>
                    `).join('')}
                </div>
            `;
        } else if (tab === 'faq') {
            const faqs = await api('/faq');
            const suggestions = await api('/faq/suggestions');
            content.innerHTML = `
                <div class="faq-management">
                    <h4>已批准的 FAQ</h4>
                    <ul class="faq-list">
                        ${(faqs.faqs || []).map(f => `
                            <li class="faq-item">
                                <div class="faq-question">${escapeHtml(f.question)}</div>
                                <div class="faq-answer">${escapeHtml(f.answer)}</div>
                            </li>
                        `).join('')}
                    </ul>
                    <h4>待审核建议</h4>
                    <ul class="suggestion-list">
                        ${(suggestions.suggestions || []).map(s => `
                            <li class="suggestion-item">
                                <div class="suggestion-question">${escapeHtml(s.question)}</div>
                                <div class="suggestion-actions">
                                    <button class="btn btn-sm btn-primary" onclick="approveFaqSuggestion(${s.id})">批准</button>
                                    <button class="btn btn-sm btn-danger" onclick="rejectFaqSuggestion(${s.id})">拒绝</button>
                                </div>
                            </li>
                        `).join('')}
                    </ul>
                </div>
            `;
        }
    } catch (err) {
        content.innerHTML = `<div class="error">加载失败: ${err.message}</div>`;
    }
}

async function approveFaqSuggestion(id) {
    try {
        await api(`/faq/suggestions/${id}/approve`, { method: 'POST' });
        showToast('FAQ 已批准', 'success');
        showStatsTab('faq');
    } catch (err) {
        showToast('操作失败', 'error');
    }
}

async function rejectFaqSuggestion(id) {
    try {
        await api(`/faq/suggestions/${id}/reject`, { method: 'POST' });
        showToast('FAQ 已拒绝', 'success');
        showStatsTab('faq');
    } catch (err) {
        showToast('操作失败', 'error');
    }
}

// ===== 知识库管理 =====

function toggleKbPanel() {
    const content = $('kbContent');
    const btn = $('kbToggleBtn');
    if (content.style.display === 'none') {
        content.style.display = 'block';
        btn.textContent = '▲';
        loadCollections();
        loadDocuments();
    } else {
        content.style.display = 'none';
        btn.textContent = '▼';
    }
}

async function loadCollections() {
    try {
        const data = await api('/collections');
        state.collections = data.collections || [];
        renderCollections();
        updateKbFilters();
    } catch (err) {
        $('kbList').innerHTML = `<li class="error">加载失败: ${err.message}</li>`;
    }
}

function renderCollections() {
    const list = $('kbList');
    if (!state.collections.length) {
        list.innerHTML = '<li class="empty">暂无向量库</li>';
        return;
    }

    list.innerHTML = state.collections.map(c => `
        <li class="kb-item" data-name="${c.name}">
            <div class="kb-item-info">
                <span class="kb-name">${escapeHtml(c.display_name || c.name)}</span>
                <span class="kb-count">${c.document_count || 0} 文档</span>
            </div>
            <div class="kb-item-actions">
                <button class="btn-icon-sm" onclick="viewKbDocuments('${c.name}')" title="查看文档">📄</button>
                ${state.user?.role === 'admin' ? `<button class="btn-icon-sm danger" onclick="deleteKb('${c.name}')" title="删除">×</button>` : ''}
            </div>
        </li>
    `).join('');
}

function updateKbFilters() {
    const options = state.collections.map(c => `<option value="${c.name}">${c.display_name || c.name}</option>`).join('');
    $('docKbFilter').innerHTML = `<option value="">全部向量库</option>${options}`;
    $('uploadKbSelect').innerHTML = `<option value="">请选择向量库</option>${options}`;
}

function showCreateKbModal() {
    $('createKbModal').style.display = 'flex';
}

function closeCreateKbModal() {
    $('createKbModal').style.display = 'none';
    $('createKbForm').reset();
}

async function createKb(e) {
    e.preventDefault();

    const name = $('newKbName').value.trim();
    const displayName = $('newKbDisplayName').value.trim();
    const department = $('newKbDepartment').value.trim();
    const description = $('newKbDescription').value.trim();

    try {
        await api('/collections', {
            method: 'POST',
            body: JSON.stringify({ name, display_name: displayName, department, description })
        });
        closeCreateKbModal();
        showToast('向量库创建成功', 'success');
        loadCollections();
    } catch (err) {
        showToast('创建失败: ' + err.message, 'error');
    }
}

async function deleteKb(name) {
    if (!confirm(`确定删除向量库 "${name}" 吗？此操作不可恢复！`)) return;

    try {
        await api(`/collections/${name}`, { method: 'DELETE' });
        showToast('向量库已删除', 'success');
        loadCollections();
    } catch (err) {
        showToast('删除失败: ' + err.message, 'error');
    }
}

async function viewKbDocuments(kbName) {
    $('docKbFilter').value = kbName;
    loadDocuments();
}

// ===== 文档管理 =====

async function loadDocuments() {
    const kbFilter = $('docKbFilter').value;
    const list = $('docList');

    try {
        const params = kbFilter ? `?collection=${kbFilter}` : '';
        const data = await api(`/documents/list${params}`);
        const docs = data.documents || [];

        if (!docs.length) {
            list.innerHTML = '<li class="empty">暂无文档</li>';
            return;
        }

        list.innerHTML = docs.map(d => `
            <li class="doc-item">
                <div class="doc-info">
                    <span class="doc-name">${escapeHtml(d.filename)}</span>
                    <span class="doc-meta">${formatFileSize(d.size)} · ${d.collection}</span>
                </div>
                <div class="doc-actions">
                    <button class="btn-icon-sm" onclick="viewDocChunks('${d.path}')" title="查看切片">📄</button>
                    ${state.user?.role === 'admin' ? `<button class="btn-icon-sm danger" onclick="deleteDocument('${d.path}')" title="删除">×</button>` : ''}
                </div>
            </li>
        `).join('');
    } catch (err) {
        list.innerHTML = `<li class="error">加载失败: ${err.message}</li>`;
    }
}

function formatFileSize(bytes) {
    if (!bytes) return '-';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function viewDocChunks(docPath) {
    $('chunksModal').style.display = 'flex';
    const content = $('chunksContent');
    content.innerHTML = '<div class="loading">加载中...</div>';

    try {
        const data = await api(`/documents/${encodeURIComponent(docPath)}/chunks`);
        const chunks = data.chunks || [];

        content.innerHTML = `
            <div class="chunks-header">
                <h4>${docPath} - 共 ${chunks.length} 个切片</h4>
            </div>
            <div class="chunks-list">
                ${chunks.map((c, i) => `
                    <div class="chunk-item">
                        <div class="chunk-header">
                            <span class="chunk-id">#${i + 1}</span>
                            <span class="chunk-meta">${c.metadata?.page ? '第' + c.metadata.page + '页' : ''}</span>
                        </div>
                        <div class="chunk-content">${escapeHtml((c.document || c.content || '').substring(0, 200))}${(c.document || c.content || '').length > 200 ? '...' : ''}</div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (err) {
        content.innerHTML = `<div class="error">加载失败: ${err.message}</div>`;
    }
}

function closeChunksModal() {
    $('chunksModal').style.display = 'none';
}

async function deleteDocument(docPath) {
    if (!confirm('确定删除此文档吗？')) return;

    try {
        await api(`/documents/${encodeURIComponent(docPath)}`, { method: 'DELETE' });
        showToast('文档已删除', 'success');
        loadDocuments();
        loadCollections();
    } catch (err) {
        showToast('删除失败: ' + err.message, 'error');
    }
}

// ===== 文档上传 =====

function showUploadModal() {
    $('uploadModal').style.display = 'flex';
    state.selectedFiles = [];
    $('selectedFiles').innerHTML = '';
}

function closeUploadModal() {
    $('uploadModal').style.display = 'none';
    state.selectedFiles = [];
    $('selectedFiles').innerHTML = '';
    $('uploadFileInput').value = '';
}

function handleFileSelect(files) {
    const validFiles = Array.from(files).filter(f => {
        const ext = f.name.split('.').pop().toLowerCase();
        return ['pdf', 'docx', 'doc', 'xlsx', 'txt'].includes(ext) && f.size <= 10 * 1024 * 1024;
    });

    state.selectedFiles = validFiles;
    $('selectedFiles').innerHTML = validFiles.map(f => `
        <div class="selected-file">
            <span>${escapeHtml(f.name)}</span>
            <span class="file-size">${formatFileSize(f.size)}</span>
        </div>
    `).join('');
}

async function uploadDocument(e) {
    e.preventDefault();

    const kbName = $('uploadKbSelect').value;
    if (!kbName) {
        showToast('请选择目标向量库', 'error');
        return;
    }

    if (!state.selectedFiles.length) {
        showToast('请选择要上传的文件', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('collection', kbName);

    if (state.selectedFiles.length === 1) {
        formData.append('file', state.selectedFiles[0]);
    } else {
        state.selectedFiles.forEach(f => formData.append('files', f));
    }

    try {
        const endpoint = state.selectedFiles.length === 1 ? '/documents/upload' : '/documents/batch-upload';
        const res = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${state.token}` },
            body: formData
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '上传失败');

        closeUploadModal();
        showToast(`成功上传 ${state.selectedFiles.length} 个文件`, 'success');
        loadDocuments();
        loadCollections();
    } catch (err) {
        showToast('上传失败: ' + err.message, 'error');
    }
}

// ===== 同步状态 =====

async function loadSyncStatus() {
    try {
        const data = await api('/sync/status');

        $('syncStatusValue').textContent = data.enabled ? '正常' : '未启用';
        $('syncStatusValue').className = `sync-value ${data.enabled ? 'success' : 'error'}`;

        if (data.last_sync) {
            $('lastSyncTime').textContent = formatTime(data.last_sync.time) || '--';
        }
    } catch (err) {
        $('syncStatusValue').textContent = '错误';
        $('syncStatusValue').className = 'sync-value error';
    }
}

async function triggerSync() {
    showToast('正在同步...', 'info');
    try {
        await api('/sync', { method: 'POST' });
        showToast('同步完成', 'success');
        loadSyncStatus();
        loadCollections();
        loadDocuments();
    } catch (err) {
        showToast('同步失败: ' + err.message, 'error');
    }
}

// ===== 出题联动 =====

function createExamFromChat(messageId) {
    const messageEl = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageEl) return;

    // 获取对话上下文作为出题主题
    const content = messageEl.querySelector('.message-content')?.textContent || '';
    const sources = JSON.parse(messageEl.dataset.sources || '[]');

    // 提取主题（取前50字符或来源文档名）
    let topic = content.substring(0, 50);
    if (sources.length > 0) {
        topic = sources[0].source || sources[0] || topic;
    }

    // 跳转到出题页面
    window.location.href = `exam.html?mode=chat&topic=${encodeURIComponent(topic)}`;
}

// 暴露更多全局函数
window.toggleKbPanel = toggleKbPanel;
window.openFeedbackModal = openFeedbackModal;
window.closeFeedbackModal = closeFeedbackModal;
window.selectFeedbackRating = selectFeedbackRating;
window.submitFeedbackForm = submitFeedbackForm;
window.showFeedbackStatsModal = showFeedbackStatsModal;
window.closeFeedbackStatsModal = closeFeedbackStatsModal;
window.showStatsTab = showStatsTab;
window.approveFaqSuggestion = approveFaqSuggestion;
window.rejectFaqSuggestion = rejectFaqSuggestion;
window.showCreateKbModal = showCreateKbModal;
window.closeCreateKbModal = closeCreateKbModal;
window.createKb = createKb;
window.deleteKb = deleteKb;
window.viewKbDocuments = viewKbDocuments;
window.loadDocuments = loadDocuments;
window.viewDocChunks = viewDocChunks;
window.closeChunksModal = closeChunksModal;
window.deleteDocument = deleteDocument;
window.showUploadModal = showUploadModal;
window.closeUploadModal = closeUploadModal;
window.handleFileSelect = handleFileSelect;
window.uploadDocument = uploadDocument;
window.triggerSync = triggerSync;
window.createExamFromChat = createExamFromChat;

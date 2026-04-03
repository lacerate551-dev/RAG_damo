// ===== 配置 =====
const API_BASE = 'http://localhost:5001';
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
    }
};

// ===== DOM =====
const $ = id => document.getElementById(id);

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    initEvents();
    renderLogs();
});

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
    }
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
            $('currentSessionId').textContent = state.sessionId.substring(0, 8);
            addMessage('assistant', data.answer, data.sources, data.web_searched, false);
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
    const res = await fetch(`${API_BASE}/rag/stream`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${state.token}`
        },
        body: JSON.stringify({ session_id: state.sessionId, message: msg })
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
                    if (event.type === 'result') {
                        result = event;
                    }
                } catch (e) {}
            }
        }
    }

    if (result) {
        state.sessionId = result.session_id;
        $('currentSessionId').textContent = state.sessionId.substring(0, 8);
        addMessage('assistant', result.answer, result.sources, false, true);
        loadSessions();
    }
}

function handleStreamEvent(event) {
    const type = event.type;
    let msg = '';
    switch (type) {
        case 'start': msg = '开始处理...'; break;
        case 'decision': msg = `决策: ${event.action}`; break;
        case 'rewrite': msg = `重写: ${event.new_query || event.rewritten_query || ''}`; break;
        case 'decompose': msg = `分解查询: ${event.sub_queries?.join(', ') || ''}`; break;
        case 'retrieve': msg = `检索${event.source ? '(' + event.source + ')' : ''}: ${event.query || ''}`; break;
        case 'answer': msg = '生成回答...'; break;
        case 'warning': msg = `警告: ${event.message || ''}`; break;
        case 'max_iterations': msg = '达到最大迭代次数'; break;
        case 'complete': msg = '处理完成'; break;
        default: msg = type;
    }
    addLog(type, msg, event);
}

function addMessage(role, content, sources, webSearched, isRag) {
    const container = $('chatMessages');
    // 移除空状态
    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;

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

    html += `<div class="message-content">${escapeHtml(content)}</div>`;

    // 显示来源
    if (sources && sources.length > 0) {
        html += '<div class="message-sources"><strong>来源:</strong> ';
        sources.forEach((s, i) => {
            const level = s.security_level || s.level || '';
            const levelTag = level ? `<span class="security-tag ${level}">${level}</span>` : '';
            html += `<span class="source-item">${levelTag}${escapeHtml(s.source || s)}</span>`;
            if (i < sources.length - 1) html += ', ';
        });
        html += '</div>';
    }

    div.innerHTML = html;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
            if (!confirm('确定删除此会话？')) return;
            try {
                await api(`/session/${btn.dataset.id}`, { method: 'DELETE' });
                loadSessions();
                if (state.sessionId === btn.dataset.id) {
                    newSession();
                }
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

    container.innerHTML = messages.map(m => `
        <div class="message ${m.role}">
            <div class="message-content">${escapeHtml(m.content)}</div>
        </div>
    `).join('');
    container.scrollTop = container.scrollHeight;
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

// 暴露给 HTML 的全局函数
window.toggleUserStatus = toggleUserStatus;

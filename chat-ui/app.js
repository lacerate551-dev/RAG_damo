// ===== 配置 =====
const API_BASE = 'http://localhost:5001';

// ===== 状态管理 =====
let state = {
    currentUserId: 'test_user_001',
    currentSessionId: null,
    mode: 'chat',  // 'chat' 或 'rag'
    sessions: [],
    messages: {},
    pendingRequests: new Map()
};

// ===== DOM 元素 =====
const elements = {
    userSelect: document.getElementById('userSelect'),
    customUserInput: document.getElementById('customUserInput'),
    currentSessionId: document.getElementById('currentSessionId'),
    sessionList: document.getElementById('sessionList'),
    chatMessages: document.getElementById('chatMessages'),
    messageInput: document.getElementById('messageInput'),
    sendBtn: document.getElementById('sendBtn'),
    newSessionBtn: document.getElementById('newSessionBtn'),
    modeToggle: document.getElementById('modeToggle'),
    modeLabel: document.getElementById('modeLabel')
};

// ===== API 调用 =====
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// 发送消息
async function sendMessage(message, targetSessionId) {
    // 根据模式选择接口
    const endpoint = state.mode === 'chat' ? '/chat' : '/rag';

    const data = await apiCall(endpoint, {
        method: 'POST',
        body: JSON.stringify({
            user_id: state.currentUserId,
            session_id: targetSessionId,
            message: message
        })
    });

    return data;
}

// 获取会话列表
async function fetchSessions() {
    const data = await apiCall(`/sessions?user_id=${state.currentUserId}`);
    state.sessions = data.sessions || [];
    renderSessionList();
}

// 获取会话历史
async function fetchHistory(sessionId) {
    const data = await apiCall(`/history/${sessionId}?user_id=${state.currentUserId}`);
    return data.history || [];
}

// 删除会话
async function deleteSession(sessionId) {
    await apiCall(`/session/${sessionId}?user_id=${state.currentUserId}`, {
        method: 'DELETE'
    });
}

// ===== 模式切换 =====
function toggleMode() {
    state.mode = state.mode === 'chat' ? 'rag' : 'chat';
    updateModeUI();

    // 切换模式时可以新建会话（可选）
    // newSession();
}

function updateModeUI() {
    if (state.mode === 'chat') {
        elements.modeToggle.classList.remove('rag-mode');
        elements.modeToggle.classList.add('chat-mode');
        elements.modeLabel.textContent = '普通聊天';
        elements.modeLabel.title = '直接使用LLM回复，速度快';
    } else {
        elements.modeToggle.classList.remove('chat-mode');
        elements.modeToggle.classList.add('rag-mode');
        elements.modeLabel.textContent = '知识库问答';
        elements.modeLabel.title = '使用Agentic RAG检索知识库后回复';
    }
}

// ===== 渲染函数 =====

// 获取会话的加载状态
function isSessionLoading(sessionId) {
    return state.pendingRequests.has(sessionId);
}

// 渲染会话列表
function renderSessionList() {
    if (state.sessions.length === 0) {
        elements.sessionList.innerHTML = `
            <div class="empty-state">
                <h3>暂无会话</h3>
                <p>发送消息开始新对话</p>
            </div>
        `;
        return;
    }

    elements.sessionList.innerHTML = state.sessions.map(session => {
        const isLoading = isSessionLoading(session.session_id);
        const isActive = session.session_id === state.currentSessionId;
        return `
            <div class="session-item ${isActive ? 'active' : ''} ${isLoading ? 'loading' : ''}"
                 data-session-id="${session.session_id}">
                <div class="session-preview">
                    ${isLoading ? '<span class="loading-indicator">...</span> ' : ''}
                    ${escapeHtml(session.preview || '空会话')}
                </div>
                <div class="session-time">${formatTime(session.last_active)}</div>
                <button class="delete-btn" data-delete="${session.session_id}">x</button>
            </div>
        `;
    }).join('');

    // 绑定点击事件
    elements.sessionList.querySelectorAll('.session-item').forEach(item => {
        item.addEventListener('click', async (e) => {
            if (e.target.classList.contains('delete-btn')) return;
            const sessionId = item.dataset.sessionId;
            await switchSession(sessionId);
        });
    });

    // 绑定删除事件
    elements.sessionList.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const sessionId = btn.dataset.delete;
            if (confirm('确定删除此会话？')) {
                await deleteSession(sessionId);
                if (state.currentSessionId === sessionId) {
                    newSession();
                }
                await fetchSessions();
            }
        });
    });
}

// 渲染消息列表
function renderMessages() {
    const sessionId = state.currentSessionId || 'new';
    const messages = state.messages[sessionId] || [];
    const isLoading = state.currentSessionId ? isSessionLoading(state.currentSessionId) : false;

    if (messages.length === 0 && !isLoading) {
        elements.chatMessages.innerHTML = `
            <div class="empty-state">
                <h3>开始对话</h3>
                <p>当前模式: ${state.mode === 'chat' ? '普通聊天' : '知识库问答'}</p>
                <p class="mode-hint">${state.mode === 'chat' ? '直接LLM回复，速度快' : '检索知识库后回复'}</p>
            </div>
        `;
        return;
    }

    let html = messages.map(msg => `
        <div class="message ${msg.role}">
            <div class="message-header">
                ${msg.role === 'user' ? '用户' : '助手'}
                ${msg.mode ? `<span class="mode-tag">${msg.mode === 'chat' ? '聊天' : '知识库'}</span>` : ''}
            </div>
            <div class="message-content">${escapeHtml(msg.content)}</div>
            ${msg.sources && msg.sources.length > 0 ? renderSources(msg.sources) : ''}
        </div>
    `).join('');

    // 如果当前会话正在加载，显示加载指示器
    if (isLoading) {
        html += `
            <div class="message assistant loading-message">
                <div class="loading">正在思考...</div>
            </div>
        `;
    }

    elements.chatMessages.innerHTML = html;
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

// 渲染来源
function renderSources(sources) {
    if (!sources || sources.length === 0) return '';
    return `
        <div class="message-sources">
            <strong>来源:</strong>
            ${sources.map(s => `<span>${escapeHtml(s.source)}</span>`).join(', ')}
        </div>
    `;
}

// 更新发送按钮状态
function updateSendButton() {
    const isLoading = state.currentSessionId ? isSessionLoading(state.currentSessionId) : false;
    elements.sendBtn.disabled = isLoading;
    elements.sendBtn.textContent = isLoading ? '等待中...' : '发送';
}

// ===== 事件处理 =====

// 切换会话
async function switchSession(sessionId) {
    state.currentSessionId = sessionId;
    elements.currentSessionId.textContent = sessionId.substring(0, 8) + '...';

    // 如果还没有加载过这个会话的消息，从服务器加载
    if (!state.messages[sessionId]) {
        const history = await fetchHistory(sessionId);
        state.messages[sessionId] = history;
    }

    renderMessages();
    renderSessionList();
    updateSendButton();
}

// 新建会话
function newSession() {
    state.currentSessionId = null;
    state.messages['new'] = [];
    elements.currentSessionId.textContent = '新会话';
    renderMessages();
    renderSessionList();
    updateSendButton();
}

// 发送消息处理
async function handleSend() {
    const message = elements.messageInput.value.trim();
    if (!message) return;

    const targetSessionId = state.currentSessionId;
    const sessionKey = targetSessionId || 'new';

    // 如果当前会话已经在加载中，不发送新请求
    if (isSessionLoading(targetSessionId)) {
        return;
    }

    // 初始化会话消息数组
    if (!state.messages[sessionKey]) {
        state.messages[sessionKey] = [];
    }

    // 添加用户消息到对应会话
    state.messages[sessionKey].push({ role: 'user', content: message });

    // 如果是当前显示的会话，立即渲染
    const isCurrentSession = (state.currentSessionId === targetSessionId) ||
                             (!targetSessionId && state.currentSessionId === null);
    if (isCurrentSession) {
        renderMessages();
    }

    elements.messageInput.value = '';

    // 标记该会话为加载中
    state.pendingRequests.set(targetSessionId, { message, startTime: Date.now() });

    // 更新UI
    renderSessionList();
    if (isCurrentSession) {
        renderMessages();
        updateSendButton();
    }

    try {
        const data = await sendMessage(message, targetSessionId);

        // 检查请求完成时会话是否仍然有效
        const responseSessionKey = data.session_id || 'new';

        // 如果是新会话，需要迁移消息
        if (!targetSessionId && data.session_id) {
            if (state.messages['new'] && state.messages['new'].length > 0) {
                if (!state.messages[data.session_id]) {
                    state.messages[data.session_id] = [];
                }
                const userMsg = state.messages['new'].pop();
                if (userMsg && userMsg.role === 'user') {
                    state.messages[data.session_id].push(userMsg);
                }
            }
            state.currentSessionId = data.session_id;
            elements.currentSessionId.textContent = data.session_id.substring(0, 8) + '...';
        }

        // 确保会话消息数组存在
        if (!state.messages[data.session_id]) {
            state.messages[data.session_id] = [];
        }

        // 添加助手消息到正确的会话
        state.messages[data.session_id].push({
            role: 'assistant',
            content: data.answer,
            sources: data.sources,
            mode: data.mode  // 记录回复模式
        });

        // 刷新会话列表
        await fetchSessions();

    } catch (error) {
        const errorSessionKey = targetSessionId || 'new';
        if (!state.messages[errorSessionKey]) {
            state.messages[errorSessionKey] = [];
        }
        state.messages[errorSessionKey].push({
            role: 'assistant',
            content: `错误: ${error.message}`
        });
    } finally {
        // 清除加载状态
        state.pendingRequests.delete(targetSessionId);

        // 更新UI
        renderSessionList();
        renderMessages();
        updateSendButton();
    }
}

// 用户选择变更
elements.userSelect.addEventListener('change', async (e) => {
    const value = e.target.value;
    if (value === 'custom') {
        elements.customUserInput.style.display = 'inline';
        elements.customUserInput.focus();
    } else {
        elements.customUserInput.style.display = 'none';
        state.currentUserId = value;
        state.messages = {};
        state.pendingRequests.clear();
        newSession();
        await fetchSessions();
    }
});

elements.customUserInput.addEventListener('change', async (e) => {
    const value = e.target.value.trim();
    if (value) {
        state.currentUserId = value;
        state.messages = {};
        state.pendingRequests.clear();
        newSession();
        await fetchSessions();
    }
});

// 模式切换
elements.modeToggle.addEventListener('click', toggleMode);

// 发送按钮
elements.sendBtn.addEventListener('click', handleSend);

// 回车发送
elements.messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
    }
});

// 新建会话按钮
elements.newSessionBtn.addEventListener('click', newSession);

// ===== 工具函数 =====

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
    if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
    return date.toLocaleDateString();
}

// ===== 初始化 =====
async function init() {
    console.log('RAG Chat UI 初始化...');

    // 检查API连接
    try {
        const health = await apiCall('/health');
        console.log('API 连接正常:', health);
    } catch (error) {
        console.error('API 连接失败:', error);
        elements.chatMessages.innerHTML = `
            <div class="empty-state">
                <h3>API 连接失败</h3>
                <p>请确保后端服务已启动: python rag_api_server.py</p>
            </div>
        `;
        return;
    }

    // 初始化
    state.messages['new'] = [];
    updateModeUI();

    // 加载会话列表
    await fetchSessions();

    // 聚焦输入框
    elements.messageInput.focus();
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', init);

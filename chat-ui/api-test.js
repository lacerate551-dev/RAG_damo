// ===== 配置选项与认证体系复用 =====
const DEFAULT_API_BASE = 'http://localhost:5001';
let API_BASE = localStorage.getItem('rag_api_base') || DEFAULT_API_BASE;
const TOKEN_KEY = 'rag_auth_token';
const USER_KEY = 'rag_auth_user';

// 组件与状态
const state = {
    token: localStorage.getItem(TOKEN_KEY),
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
    currentEndpoint: null
};

// 各种待测试的 API 端点清单
const endpointGroups = [
    {
        group: '系统与权限 (System & Auth)',
        items: [
            { name: "获取当前用户", method: "GET", path: "/auth/me", desc: "返回网关注入到当前的 User 信息与权限标签", pathParams: [], bodyParams: [] },
            { name: "健康检查", method: "GET", path: "/health", desc: "检查 RAG 服务的健康状态", pathParams: [], bodyParams: [] },
            { name: "系统统计", method: "GET", path: "/stats", desc: "获取系统的整体运行与资源统计信息（仅管理员）", pathParams: [], bodyParams: [] }
        ]
    },
    {
        group: '多向量库与核心检索 (RAG Base)',
        items: [
            { name: "基础聊天", method: "POST", path: "/chat", desc: "普通对话模式（纯LLM）", pathParams: [], bodyParams: [ {key: "session_id", type: "string"}, {key: "message", type: "string", default: "你好"} ] },
            { name: "知识库问答", method: "POST", path: "/rag", desc: "SSE 流式返回 RAG 问答过程与结果", pathParams: [], bodyParams: [ {key: "session_id", type: "string"}, {key: "message", type: "string", default: "介绍一下公司考勤制度"} ], isStream: true },
            { name: "内部混合检索", method: "POST", path: "/search", desc: "Dify使用的高性能混合检索（RRF融合）", pathParams: [], bodyParams: [ {key: "query", type: "string", default: "请假流程"}, {key: "top_k", type: "number", default: 5} ] },
            { name: "版本感知检索", method: "POST", path: "/search/version-aware", desc: "检索指定知识库中存活的最新条款", pathParams: [], bodyParams: [ {key: "query", type: "string"}, {key: "collection", type: "string", default: "public_kb"}, {key: "top_k", type: "number", default: 5} ] },
            { name: "知识库路由查询", method: "POST", path: "/kb/route", desc: "根据查询内容智能路由到最合适的知识库", pathParams: [], bodyParams: [ {key: "query", type: "string", default: "财务报销流程"} ] }
        ]
    },
    {
        group: '会话管理 (Sessions)',
        items: [
            { name: "获取我的会话", method: "GET", path: "/sessions", desc: "获取当前用户的所有历史会话记录", pathParams: [], bodyParams: [] },
            { name: "查看会话详情", method: "GET", path: "/history/<session_id>", desc: "翻阅指定会话的历史记录", pathParams: ["session_id"], bodyParams: [] },
            { name: "删除单条会话", method: "DELETE", path: "/session/<session_id>", desc: "彻底移除一个会话", pathParams: ["session_id"], bodyParams: [] },
            { name: "清空历史上下文", method: "POST", path: "/clear/<session_id>", desc: "清空此会话历史但保留会话ID壳", pathParams: ["session_id"], bodyParams: [] }
        ]
    },
    {
        group: '多库集群 (Collections)',
        items: [
            { name: "获取所有知识库", method: "GET", path: "/collections", desc: "查询自己有权访问的所有多向量库", pathParams: [], bodyParams: [] },
            { name: "创建新部门库", method: "POST", path: "/collections", desc: "管理员新建物理隔离向量库", pathParams: [], bodyParams: [ {key:"name", type:"string", default:"dept_demo"}, {key:"display_name", type:"string", default:"演示部"}, {key:"department", type:"string", default:"demo"}, {key:"description", type:"string"} ] },
            { name: "删除整个知识库", method: "DELETE", path: "/collections/<kb_name>", desc: "直接干掉隔离向量库下所有数据", pathParams: ["kb_name"], bodyParams: [] },
            { name: "列出库内全量文档", method: "GET", path: "/collections/<kb_name>/documents", desc: "列出特定向量库下目前存在的文件清单", pathParams: ["kb_name"], bodyParams: [] }
        ]
    },
    {
        group: '文档生命周期 (Doc Lifecycle)',
        items: [
            { name: "系统可用文档汇编", method: "GET", path: "/documents/list", desc: "获取全系统被纳管的文档及状态", pathParams: [], bodyParams: [] },
            { name: "上传新文档", method: "POST", path: "/documents/upload", desc: "上传文档到指定知识库（需选择文件）", pathParams: [], bodyParams: [ {key: "collection", type: "string", default: "public_kb"}, {key: "security_level", type: "string", default: "public"} ], isUpload: true },
            { name: "查询已废止文档", method: "GET", path: "/documents/deprecated", desc: "罗列已经打上作废下划线的旧规章", pathParams: [], bodyParams: [] },
            { name: "彻底物理删除文档", method: "DELETE", path: "/documents/<path>", desc: "连根拔起向量及其物理文件", pathParams: ["path"], bodyParams: [] },
            { name: "废止指定文档", method: "POST", path: "/documents/<collection>/<path>/deprecate", desc: "仅打死不删，保留追溯期，标注为被取代", pathParams: ["collection", "path"], bodyParams: [ {key:"reason", type:"string", default:"因更新换代被取代"}, {key:"replaced_by", type:"string"} ] },
            { name: "恢复已废除文档", method: "POST", path: "/documents/<collection>/<path>/restore", desc: "重新将打下划线的文件拉入搜索结果", pathParams: ["collection", "path"], bodyParams: [] },
            { name: "查询文档版本树", method: "GET", path: "/documents/<collection>/<path>/versions", desc: "文档迭代版本日志溯源", pathParams: ["collection", "path"], bodyParams: [] },
            { name: "文档片段信息", method: "GET", path: "/documents/<collection>/<path>/info", desc: "检索切片(Chunks)分布及元数据情况", pathParams: ["collection", "path"], bodyParams: [] },
            { name: "双规对冲比较", method: "POST", path: "/documents/<collection>/<path>/diff", desc: "比较版本哈希并高亮更改之处", pathParams: ["collection", "path"], bodyParams: [ {key:"content1", type:"string", default:"老版报销制度内容"}, {key:"content2", type:"string", default:"新版报销制度大幅削减额度"} ] }
        ]
    },
    {
        group: '知识大纲与推荐 (Outline)',
        items: [
            { name: "获取大纲提纲", method: "GET", path: "/outline/<document_id>", desc: "抓取预生成好的大纲树结构", pathParams: ["document_id"], bodyParams: [] },
            { name: "手工排版大纲卡", method: "POST", path: "/outline", desc: "手动干预或添加大纲描述", pathParams: [], bodyParams: [ {key:"document_id", type:"string"}, {key:"title", type:"string"} ] },
            { name: "导出大纲脑图", method: "GET", path: "/outline/<document_id>/export", desc: "把思维导图通过 JSON 节点导出", pathParams: ["document_id"], bodyParams: [] },
            { name: "抓取所有大纲", method: "GET", path: "/outline/list", desc: "大纲中心管理", pathParams: [], bodyParams: [] },
            { name: "获取推荐知识卡", method: "GET", path: "/recommend/<document_id>", desc: "看后即推（推荐其他类似文档或词条）", pathParams: ["document_id"], bodyParams: [] },
            { name: "后台构建推荐池", method: "POST", path: "/recommend/compute-vectors", desc: "预热计算所有向量的距离矩阵", pathParams: [], bodyParams: [ {key:"max_documents", type:"number", default:50} ] }
        ]
    },
    {
        group: '增量同步订阅器 (Sync & Notification)',
        items: [
            { name: "全自动增量同步", method: "POST", path: "/sync", desc: "根据增删改时间戳对所有库执行对比入库", pathParams: [], bodyParams: [] },
            { name: "查看同步队列", method: "GET", path: "/sync/status", desc: "查看后台处理切片的存活状态", pathParams: [], bodyParams: [] },
            { name: "浏览同步历史", method: "GET", path: "/sync/history", desc: "最近几次入库的变更明细条目", pathParams: [], bodyParams: [] },
            { name: "发现待同步点", method: "GET", path: "/sync/changes", desc: "演练一次：列出哪些文档脏了但还没写", pathParams: [], bodyParams: [] },
            { name: "开始后台长轮询", method: "POST", path: "/sync/start", desc: "启动后台进程无限刷新同步机制", pathParams: [], bodyParams: [] },
            { name: "挂起后台同异步", method: "POST", path: "/sync/stop", desc: "停止并释放掉系统轮询", pathParams: [], bodyParams: [] },
            { name: "强行推送至特定库", method: "POST", path: "/documents/sync", desc: "（老接口遗留）单点触发更新", pathParams: [], bodyParams: [] }
        ]
    },
    {
        group: '评价与内测反馈 (Feedback & FAQ)',
        items: [
            { name: "查看答疑百库", method: "GET", path: "/faq", desc: "管理员维护的精品知识", pathParams: [], bodyParams: [] },
            { name: "贡献至答疑库", method: "POST", path: "/faq", desc: "写入标准问答", pathParams: [], bodyParams: [ {key:"question", type:"string", default:"如何开具证明？"}, {key:"answer", type:"string", default:"请提交OA流程。"} ] },
            { name: "获取大盘报表", method: "GET", path: "/feedback/stats", desc: "看最近点赞踩扁的统计占比", pathParams: [], bodyParams: [] },
            { name: "打回并吐槽", method: "POST", path: "/feedback", desc: "为刚才那句话打分并且附带槽点", pathParams: [], bodyParams: [ {key:"session_id", type:"string"}, {key:"action", type:"string", default:"downvote"}, {key:"feedback_text", type:"string", default:"完全没读懂你的瞎编内容"} ] }
        ]
    }
];

const $ = id => document.getElementById(id);

// ===== 生命核心 =====
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    initUI();
    bindEvents();
});

function checkAuth() {
    if (!state.token || !state.user) {
        window.location.href = "index.html"; // 未登录被挡
    } else {
        $('username').textContent = state.user.username;
        $('welcomeRole').textContent = getRoleLabel(state.user.role);
        $('userRole').textContent = getRoleLabel(state.user.role);
        $('userRole').className = `role ${state.user.role}`;
    }
}

function getRoleLabel(role) {
    const labels = { admin: '管理员', manager: '经理', user: '用户' };
    return labels[role] || role;
}

function initUI() {
    // 渲染侧边栏树结构
    const container = $('apiListContainer');
    let html = '';
    
    endpointGroups.forEach(group => {
        html += `<div class="api-group">
            <div class="api-group-title">${group.group}</div>
            <div class="api-group-items">`;
            
        group.items.forEach((item, index) => {
            const id = `api_${group.group}_${index}`.replace(/[^a-zA-Z0-9_]/g, '_');
            item.id = id;
            html += `
                <div class="api-item" data-id="${id}" onclick="selectApi('${id}')">
                    <span class="api-method method-${item.method}">${item.method}</span>
                    <span class="api-path" title="${item.path}">${item.path}</span>
                </div>
            `;
        });
        
        html += `</div></div>`;
    });
    
    container.innerHTML = html;
}

function bindEvents() {
    $('apiForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await invokeApi();
    });
}

function selectApi(id) {
    // 高亮移除
    document.querySelectorAll('.api-item').forEach(el => el.classList.remove('active'));
    document.querySelector(`.api-item[data-id="${id}"]`).classList.add('active');

    // 寻找数据
    let selected = null;
    for(const group of endpointGroups) {
        let found = group.items.find(i => i.id === id);
        if (found) { selected = found; break; }
    }

    if (!selected) return;
    state.currentEndpoint = selected;

    // UI 显示
    $('apiEmptyState').style.display = 'none';
    $('apiContentWrap').style.display = 'flex';
    
    $('apiMethodBadge').style.display = 'inline-block';
    $('apiMethodBadge').className = `api-method method-${selected.method}`;
    $('apiMethodBadge').textContent = selected.method;
    $('apiName').textContent = selected.name;
    $('apiDesc').textContent = selected.desc;
    
    // 初始化 URL 和 Form
    updateUrlPreview();
    buildForms(selected);
    
    // 清空上次的结果
    $('responseStatus').style.display = 'none';
    $('jsonOutput').textContent = '// 发送请求以检索结果...';
    $('jsonOutput').style.color = '#d4d4d4';
}

function buildForms(apiInfo) {
    const pCont = $('pathParamsContainer');
    const bCont = $('bodyParamsContainer');

    pCont.innerHTML = '';
    bCont.innerHTML = '';

    // 渲染路径参数
    if (apiInfo.pathParams && apiInfo.pathParams.length > 0) {
        let html = '<h4 style="margin:5px 0 10px 0; color:var(--primary-color);">路径参数 (URL Path)</h4>';
        apiInfo.pathParams.forEach(param => {
            html += `
                <div class="param-group">
                    <label>【${param}】</label>
                    <input type="text" class="path-param-input" data-param="${param}" placeholder="替换 /<${param}> 的值" required oninput="updateUrlPreview()">
                </div>
            `;
        });
        pCont.innerHTML = html;
    }

    // 渲染请求体参数
    if (apiInfo.method !== 'GET' && apiInfo.method !== 'DELETE' && apiInfo.bodyParams && apiInfo.bodyParams.length > 0) {
        let html = '<h4 style="margin:20px 0 10px 0; color:var(--primary-color);">请求体负载 (JSON Body)</h4>';

        // 文件上传特殊处理
        if (apiInfo.isUpload) {
            html += `
                <div class="param-group">
                    <label>选择文件 <span>(file)</span></label>
                    <input type="file" id="fileInput" accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md" style="padding: 8px;">
                </div>
            `;
        }

        apiInfo.bodyParams.forEach(param => {
            html += `
                <div class="param-group">
                    <label>${param.key} <span>(${param.type})</span></label>
                    ${param.type === 'string' && param.key.includes('content') ?
                        `<textarea class="body-param-input" data-param="${param.key}" required>${param.default || ''}</textarea>` :
                        `<input type="${param.type === 'number' ? 'number' : 'text'}" class="body-param-input" data-param="${param.key}" value="${param.default || ''}" required>`
                    }
                </div>
            `;
        });
        bCont.innerHTML = html;
    }

    // 特殊提示
    if (apiInfo.isSSE) {
        bCont.innerHTML += `
            <div style="margin-top: 15px; padding: 10px; background: rgba(33, 150, 243, 0.1); border-radius: 6px; font-size: 0.9rem;">
                <strong>ℹ️ SSE 说明：</strong>将建立 Server-Sent Events 连接，10秒后自动断开（演示用）。
            </div>
        `;
    }
    if (apiInfo.isStream) {
        bCont.innerHTML += `
            <div style="margin-top: 15px; padding: 10px; background: rgba(33, 150, 243, 0.1); border-radius: 6px; font-size: 0.9rem;">
                <strong>ℹ️ 流式响应：</strong>将实时显示 RAG 处理过程的各个阶段（决策、检索、生成等）。
            </div>
        `;
    }
}

function updateUrlPreview() {
    if (!state.currentEndpoint) return;
    
    let path = state.currentEndpoint.path;
    
    // 替换所有被填写的 path 变量
    document.querySelectorAll('.path-param-input').forEach(input => {
        const val = input.value.trim();
        if(val) {
            path = path.replace(`<${input.dataset.param}>`, encodeURIComponent(val));
        }
    });

    $('urlPreview').textContent = `${state.currentEndpoint.method} ${API_BASE}${path}`;
}

async function invokeApi() {
    const apiInfo = state.currentEndpoint;
    if (!apiInfo) return;

    // 1. 构建终极 URL
    let path = apiInfo.path;
    let urlValid = true;
    document.querySelectorAll('.path-param-input').forEach(input => {
        const val = input.value.trim();
        if(!val) urlValid = false;
        path = path.replace(`<${input.dataset.param}>`, encodeURIComponent(val));
    });

    if (!urlValid) {
        showToast("请填写完整的路径参数！", "error");
        return;
    }

    const url = `${API_BASE}${path}`;

    // 2. 特殊处理：SSE 订阅
    if (apiInfo.isSSE) {
        invokeSSE(url);
        return;
    }

    // 3. 特殊处理：文件上传
    if (apiInfo.isUpload) {
        invokeUpload(url, apiInfo);
        return;
    }

    // 4. 特殊处理：流式响应
    if (apiInfo.isStream) {
        invokeStream(url, apiInfo);
        return;
    }

    // 5. 构建 JSON Payload
    let payload = null;
    if (apiInfo.method !== 'GET' && apiInfo.method !== 'DELETE' && apiInfo.bodyParams && apiInfo.bodyParams.length > 0) {
        payload = {};
        document.querySelectorAll('.body-param-input').forEach(input => {
            const key = input.dataset.param;
            let val = input.value;
            // 对于 number 类型强制转换
            if (input.type === 'number') val = Number(val);
            payload[key] = val;
        });
    }

    // 6. UI 按钮锁定
    const btn = $('sendBtn');
    btn.disabled = true;
    btn.textContent = '请求中...';
    $('responseStatus').style.display = 'inline-block';
    $('responseStatus').className = 'status-badge status-loading';
    $('responseStatus').textContent = 'Loading...';

    // 7. 发起 Fetch
    try {
        const fetchOptions = {
            method: apiInfo.method,
            headers: {
                'Authorization': `Bearer ${state.token}`
            }
        };

        if (payload) {
            fetchOptions.headers['Content-Type'] = 'application/json';
            fetchOptions.body = JSON.stringify(payload);
        }

        const _start = performance.now();
        const response = await fetch(url, fetchOptions);
        const _duration = Math.round(performance.now() - _start);

        let data;
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            data = await response.json();
        } else {
            const textData = await response.text();
            data = { __rawText: textData }; // Handle non-JSON output carefully
        }

        // 渲染结果区域
        $('responseStatus').textContent = `HTTP ${response.status} | 耗时: ${_duration}ms`;
        if (response.ok) {
            $('responseStatus').className = 'status-badge status-ok';
            $('jsonOutput').style.color = '#4CAF50';
        } else {
            $('responseStatus').className = 'status-badge status-error';
            $('jsonOutput').style.color = '#F44336';
        }

        $('jsonOutput').textContent = JSON.stringify(data, null, 4);

    } catch (err) {
        $('responseStatus').className = 'status-badge status-error';
        $('responseStatus').textContent = 'Network Error / Cors Issue';
        $('jsonOutput').style.color = '#F44336';
        $('jsonOutput').textContent = JSON.stringify({ error: err.message }, null, 4);
    } finally {
        btn.disabled = false;
        btn.textContent = '发送请求 🚀';
    }
}

// SSE 订阅处理
function invokeSSE(url) {
    const btn = $('sendBtn');
    btn.disabled = true;
    btn.textContent = '订阅中...';
    $('responseStatus').style.display = 'inline-block';
    $('responseStatus').className = 'status-badge status-loading';
    $('responseStatus').textContent = 'SSE 连接中...';
    $('jsonOutput').textContent = '// SSE 事件流开始...\n';
    $('jsonOutput').style.color = '#4CAF50';

    const eventSource = new EventSource(`${url}?token=${encodeURIComponent(state.token)}`);

    eventSource.onopen = () => {
        $('responseStatus').className = 'status-badge status-ok';
        $('responseStatus').textContent = 'SSE 已连接';
    };

    eventSource.onmessage = (event) => {
        const line = `[${new Date().toLocaleTimeString()}] ${event.data}\n`;
        $('jsonOutput').textContent += line;
        $('jsonOutput').scrollTop = $('jsonOutput').scrollHeight;
    };

    eventSource.onerror = (err) => {
        $('responseStatus').className = 'status-badge status-error';
        $('responseStatus').textContent = 'SSE 连接错误或已关闭';
        eventSource.close();
        btn.disabled = false;
        btn.textContent = '发送请求 🚀';
    };

    // 10秒后自动关闭（演示用）
    setTimeout(() => {
        if (eventSource.readyState !== EventSource.CLOSED) {
            eventSource.close();
            $('jsonOutput').textContent += '\n// 10秒演示后自动断开\n';
            $('responseStatus').textContent = 'SSE 已断开（演示结束）';
            btn.disabled = false;
            btn.textContent = '发送请求 🚀';
        }
    }, 10000);
}

// 文件上传处理
async function invokeUpload(url, apiInfo) {
    const fileInput = $('fileInput');
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        showToast("请选择要上传的文件！", "error");
        return;
    }

    const btn = $('sendBtn');
    btn.disabled = true;
    btn.textContent = '上传中...';
    $('responseStatus').style.display = 'inline-block';
    $('responseStatus').className = 'status-badge status-loading';
    $('responseStatus').textContent = 'Uploading...';

    try {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        // 添加其他参数
        document.querySelectorAll('.body-param-input').forEach(input => {
            const key = input.dataset.param;
            if (key !== 'file') {
                formData.append(key, input.value);
            }
        });

        const _start = performance.now();
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${state.token}`
            },
            body: formData
        });
        const _duration = Math.round(performance.now() - _start);

        const data = await response.json();

        $('responseStatus').textContent = `HTTP ${response.status} | 耗时: ${_duration}ms`;
        if (response.ok) {
            $('responseStatus').className = 'status-badge status-ok';
            $('jsonOutput').style.color = '#4CAF50';
        } else {
            $('responseStatus').className = 'status-badge status-error';
            $('jsonOutput').style.color = '#F44336';
        }

        $('jsonOutput').textContent = JSON.stringify(data, null, 4);

    } catch (err) {
        $('responseStatus').className = 'status-badge status-error';
        $('responseStatus').textContent = 'Upload Error';
        $('jsonOutput').style.color = '#F44336';
        $('jsonOutput').textContent = JSON.stringify({ error: err.message }, null, 4);
    } finally {
        btn.disabled = false;
        btn.textContent = '发送请求 🚀';
    }
}

// 流式响应处理
async function invokeStream(url, apiInfo) {
    const btn = $('sendBtn');
    btn.disabled = true;
    btn.textContent = '流式请求中...';
    $('responseStatus').style.display = 'inline-block';
    $('responseStatus').className = 'status-badge status-loading';
    $('responseStatus').textContent = 'Streaming...';
    $('jsonOutput').textContent = '// 流式响应开始...\n';
    $('jsonOutput').style.color = '#4CAF50';

    // 构建 payload
    let payload = {};
    document.querySelectorAll('.body-param-input').forEach(input => {
        const key = input.dataset.param;
        let val = input.value;
        if (input.type === 'number') val = Number(val);
        payload[key] = val;
    });

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${state.token}`
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || `HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

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
                        const time = new Date().toLocaleTimeString();
                        $('jsonOutput').textContent += `[${time}] [${event.type}] ${JSON.stringify(event, null, 2)}\n`;
                        $('jsonOutput').scrollTop = $('jsonOutput').scrollHeight;
                    } catch (e) {
                        $('jsonOutput').textContent += `[${new Date().toLocaleTimeString()}] ${line}\n`;
                    }
                }
            }
        }

        $('responseStatus').className = 'status-badge status-ok';
        $('responseStatus').textContent = 'Streaming Complete';

    } catch (err) {
        $('responseStatus').className = 'status-badge status-error';
        $('responseStatus').textContent = 'Stream Error';
        $('jsonOutput').style.color = '#F44336';
        $('jsonOutput').textContent += `\n// Error: ${err.message}\n`;
    } finally {
        btn.disabled = false;
        btn.textContent = '发送请求 🚀';
    }
}

function showToast(message, type = 'info') {
    const toast = $('toast');
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

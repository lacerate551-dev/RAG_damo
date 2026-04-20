// 出题系统测试页面 JS
const DEFAULT_API_BASE = 'http://localhost:5001';
let API_BASE = localStorage.getItem('rag_api_base') || DEFAULT_API_BASE;
const TOKEN_KEY = 'rag_auth_token';
const USER_KEY = 'rag_auth_user';

// 状态
const state = {
    token: localStorage.getItem(TOKEN_KEY),
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
    currentExam: null,
    exams: [],
    reports: []
};

// DOM 快捷方式
const $ = id => document.getElementById(id);

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    if (state.token && state.user) {
        initTabs();
        initEvents();
        loadStats();
    }
});

function checkAuth() {
    if (!state.token || !state.user) {
        // 显示未登录提示，而不是直接跳转
        $('userInfo').innerHTML = `<span style="color:red;">未登录</span> <a href="index.html" style="color:#4a90d9;">去登录</a>`;
        // 禁用所有功能
        document.querySelectorAll('.exam-tab, button').forEach(el => {
            el.disabled = true;
            el.style.opacity = '0.5';
        });
        return;
    }
    $('userInfo').textContent = `${state.user.username} (${state.user.role})`;
}

// 标签页切换
function initTabs() {
    document.querySelectorAll('.exam-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabId = tab.dataset.tab;

            // 更新标签样式
            document.querySelectorAll('.exam-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // 显示对应面板
            document.querySelectorAll('.exam-panel').forEach(p => p.classList.remove('active'));
            $(`${tabId}Panel`).classList.add('active');

            // 加载数据
            if (tabId === 'list') loadExams();
            if (tabId === 'review') loadPendingExams();
            if (tabId === 'grade') loadApprovedExams();
            if (tabId === 'reports') loadReports();
        });
    });
}

// 事件绑定
function initEvents() {
    // 生成试卷
    $('generateForm').addEventListener('submit', handleGenerateExam);

    // 试卷列表
    $('statusFilter').addEventListener('change', loadExams);
    $('refreshListBtn').addEventListener('click', loadExams);

    // 批阅
    $('examSelect').addEventListener('change', handleExamSelect);
    $('submitGradeBtn').addEventListener('click', handleSubmitGrade);

    // 弹窗
    $('closeExamModal').addEventListener('click', () => $('examModal').style.display = 'none');
    $('modalCloseBtn').addEventListener('click', () => $('examModal').style.display = 'none');
    $('closeGradeResultModal').addEventListener('click', () => $('gradeResultModal').style.display = 'none');

    // 审核按钮（在生成面板中）
    if ($('approveBtn')) {
        $('approveBtn').addEventListener('click', handleQuickApprove);
    }
    if ($('rejectBtn')) {
        $('rejectBtn').addEventListener('click', handleQuickReject);
    }
    if ($('saveDraftBtn')) {
        $('saveDraftBtn').addEventListener('click', handleSaveDraft);
    }

    // 弹窗中的审核按钮
    if ($('modalApproveBtn')) {
        $('modalApproveBtn').addEventListener('click', handleModalApprove);
    }
    if ($('modalRejectBtn')) {
        $('modalRejectBtn').addEventListener('click', handleModalReject);
    }
    if ($('modalGradeBtn')) {
        $('modalGradeBtn').addEventListener('click', handleModalGrade);
    }

    // 点击弹窗外部关闭
    $('examModal').addEventListener('click', (e) => {
        if (e.target === $('examModal')) $('examModal').style.display = 'none';
    });
    $('gradeResultModal').addEventListener('click', (e) => {
        if (e.target === $('gradeResultModal')) $('gradeResultModal').style.display = 'none';
    });
}

// API 调用
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
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        setTimeout(() => window.location.href = 'index.html', 1500);
        throw new Error('Unauthorized');
    }

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

// 生成试卷
async function handleGenerateExam(e) {
    e.preventDefault();

    const topic = $('topic').value.trim();
    const examName = $('examName').value.trim();
    if (!topic) {
        showToast('请输入主题', 'error');
        return;
    }

    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = '生成中...';

    try {
        const exam = await api('/exam/generate', {
            method: 'POST',
            body: JSON.stringify({
                name: examName || `${topic}试卷`,
                topic,
                choice_count: parseInt($('choiceCount').value) || 3,
                blank_count: parseInt($('blankCount').value) || 2,
                short_answer_count: parseInt($('shortAnswerCount').value) || 2,
                difficulty: parseInt($('difficulty').value) || 3,
                choice_score: parseInt($('choiceScore').value) || 2,
                blank_score: parseInt($('blankScore').value) || 3,
                created_by: state.user.username
            })
        });

        state.currentExam = exam;
        renderExamPreview(exam);
        $('examPreview').style.display = 'block';
        $('quickReviewPanel').style.display = 'block';
        showToast('试卷生成成功！', 'success');

        // 刷新统计
        loadStats();

    } catch (err) {
        showToast('生成失败: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '生成试卷';
    }
}

// 渲染试卷预览
function renderExamPreview(exam) {
    let html = `
        <div class="exam-card">
            <div class="exam-card-header">
                <span class="exam-card-title">${exam.name || exam.topic || '试卷'}</span>
                <span class="exam-status status-${exam.status}">${getStatusText(exam.status)}</span>
            </div>
            <div class="exam-card-meta">
                题目数: ${exam.total_count || 0} | 总分: ${exam.total_score || 0} |
                创建时间: ${exam.created_at ? new Date(exam.created_at).toLocaleString() : '-'}
            </div>
        </div>
    `;

    // 选择题
    if (exam.choice_questions && exam.choice_questions.length > 0) {
        html += `<h4>选择题 (${exam.choice_questions.length}题)</h4>`;
        exam.choice_questions.forEach((q, i) => {
            html += renderQuestion('choice', q, i + 1);
        });
    }

    // 填空题
    if (exam.blank_questions && exam.blank_questions.length > 0) {
        html += `<h4>填空题 (${exam.blank_questions.length}题)</h4>`;
        exam.blank_questions.forEach((q, i) => {
            html += renderQuestion('blank', q, i + 1);
        });
    }

    // 简答题
    if (exam.short_answer_questions && exam.short_answer_questions.length > 0) {
        html += `<h4>简答题 (${exam.short_answer_questions.length}题)</h4>`;
        exam.short_answer_questions.forEach((q, i) => {
            html += renderQuestion('short_answer', q, i + 1);
        });
    }

    $('examContent').innerHTML = html;
}

// 渲染单个题目
function renderQuestion(type, q, index) {
    let html = `<div class="question-item">`;
    html += `<div class="question-header">`;
    html += `<span class="question-type">${getTypeText(type)}</span>`;
    html += `<span>分值: ${q.score || q.reference_answer?.total_score || '-'}</span>`;
    html += `</div>`;
    html += `<div class="question-content">${index}. ${q.content}</div>`;

    if (type === 'choice' && q.options) {
        html += `<div class="question-options">`;
        q.options.forEach(opt => {
            html += `<div class="question-option">${opt}</div>`;
        });
        html += `</div>`;
    }

    html += `<div class="question-answer">`;
    html += `<strong>答案:</strong> `;
    if (type === 'short_answer' && q.reference_answer) {
        html += `<div style="margin-top:5px;">`;
        q.reference_answer.points?.forEach(p => {
            html += `<div>- ${p.point} (${p.score}分)</div>`;
        });
        html += `</div>`;
    } else {
        html += `${q.answer || '-'}`;
    }
    html += `</div>`;

    if (q.analysis) {
        html += `<div style="margin-top:10px;color:#666;"><strong>解析:</strong> ${q.analysis}</div>`;
    }

    html += `</div>`;
    return html;
}

function getTypeText(type) {
    const types = { choice: '选择题', blank: '填空题', short_answer: '简答题' };
    return types[type] || type;
}

function getStatusText(status) {
    const statuses = {
        draft: '草稿',
        pending_review: '待审核',
        approved: '已通过',
        rejected: '已驳回'
    };
    return statuses[status] || status;
}

// 快速审核通过（生成面板）
async function handleQuickApprove() {
    if (!state.currentExam) return;
    if (!confirm('确定通过审核？')) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'approve' })
        });
        state.currentExam.status = 'approved';
        renderExamPreview(state.currentExam);
        $('quickReviewPanel').style.display = 'none';
        showToast('审核通过！试卷已加入题库', 'success');
        loadStats();
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 快速驳回（生成面板）
async function handleQuickReject() {
    if (!state.currentExam) return;
    if (!confirm('确定驳回此试卷？')) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'reject' })
        });
        state.currentExam.status = 'rejected';
        renderExamPreview(state.currentExam);
        $('quickReviewPanel').style.display = 'none';
        showToast('已驳回', 'success');
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 保存为草稿
async function handleSaveDraft() {
    if (!state.currentExam) return;

    try {
        // 更新试卷名称
        const examName = $('examName').value.trim();
        if (examName) {
            state.currentExam.name = examName;
            await api(`/exam/${state.currentExam.exam_id}`, {
                method: 'PUT',
                body: JSON.stringify({ name: examName })
            });
        }
        showToast('草稿已保存！', 'success');
        loadStats();
    } catch (err) {
        showToast('保存失败: ' + err.message, 'error');
    }
}

// 弹窗中审核通过
async function handleModalApprove() {
    if (!state.currentExam) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'approve' })
        });
        state.currentExam.status = 'approved';
        $('examModal').style.display = 'none';
        showToast('审核通过！', 'success');
        loadExams();
        loadStats();
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 弹窗中驳回
async function handleModalReject() {
    if (!state.currentExam) return;
    if (!confirm('确定驳回此试卷？')) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'reject' })
        });
        state.currentExam.status = 'rejected';
        $('examModal').style.display = 'none';
        showToast('已驳回！', 'success');
        loadExams();
        loadStats();
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 弹窗中去批阅
function handleModalGrade() {
    if (!state.currentExam) return;
    const examId = state.currentExam.exam_id;
    $('examModal').style.display = 'none';
    selectForGrade(examId);
}

// 保存试卷
async function handleSaveExam() {
    if (!state.currentExam) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}`, {
            method: 'PUT',
            body: JSON.stringify(state.currentExam)
        });
        showToast('试卷保存成功！', 'success');
    } catch (err) {
        showToast('保存失败: ' + err.message, 'error');
    }
}

// 提交审核
async function handleSubmitReview() {
    if (!state.currentExam) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}/submit`, {
            method: 'POST'
        });
        state.currentExam.status = 'pending_review';
        renderExamPreview(state.currentExam);
        showToast('已提交审核！', 'success');
    } catch (err) {
        showToast('提交失败: ' + err.message, 'error');
    }
}

// 加载试卷列表
async function loadExams() {
    const status = $('statusFilter').value;
    $('examList').innerHTML = '<div class="loading">加载中...</div>';

    try {
        const params = new URLSearchParams({ page: 1, limit: 20 });
        if (status) params.append('status', status);

        const result = await api(`/exam/list?${params}`);
        state.exams = result.exams || [];
        renderExamList();
    } catch (err) {
        $('examList').innerHTML = `<div class="empty-state">加载失败: ${err.message}</div>`;
    }
}

// 加载待审核试卷（显示草稿状态的试卷）
async function loadPendingExams() {
    $('pendingReviewList').innerHTML = '<div class="loading">加载中...</div>';

    // 调试信息
    console.log('当前用户:', state.user);
    console.log('用户角色:', state.user?.role);

    // 非管理员提示
    if (!state.user || state.user.role !== 'admin') {
        $('pendingReviewList').innerHTML = '<div class="empty-state">仅管理员可以审核试卷</div>';
        return;
    }

    try {
        // 获取草稿状态的试卷
        const result = await api('/exam/list?status=draft&limit=50');
        console.log('待审核试卷(草稿):', result);
        const exams = result.exams || [];

        if (!exams.length) {
            $('pendingReviewList').innerHTML = '<div class="empty-state">暂无待审核试卷</div>';
            return;
        }

        $('pendingReviewList').innerHTML = exams.map(exam => `
            <div class="exam-card">
                <div class="exam-card-header">
                    <span class="exam-card-title">${exam.name || exam.topic || '未命名试卷'}</span>
                    <span class="exam-status status-draft">草稿</span>
                </div>
                <div class="exam-card-meta">
                    题目: ${exam.total_count || 0} | 总分: ${exam.total_score || 0} |
                    创建: ${exam.created_at ? new Date(exam.created_at).toLocaleString() : '-'} |
                    创建者: ${exam.created_by || '-'}
                </div>
                <div class="exam-card-actions">
                    <button class="btn btn-primary btn-sm" onclick="viewExam('${exam.exam_id}')">查看详情</button>
                    <button class="btn btn-success btn-sm" onclick="quickApprove('${exam.exam_id}')">通过</button>
                    <button class="btn btn-danger btn-sm" onclick="quickReject('${exam.exam_id}')">驳回</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error('加载待审核试卷失败:', err);
        $('pendingReviewList').innerHTML = `<div class="empty-state">加载失败: ${err.message}</div>`;
    }
}

// 渲染试卷列表
function renderExamList() {
    if (!state.exams.length) {
        $('examList').innerHTML = '<div class="empty-state">暂无试卷</div>';
        return;
    }

    $('examList').innerHTML = state.exams.map(exam => `
        <div class="exam-card">
            <div class="exam-card-header">
                <span class="exam-card-title">${exam.name || exam.topic || '未命名试卷'}</span>
                <span class="exam-status status-${exam.status}">${getStatusText(exam.status)}</span>
            </div>
            <div class="exam-card-meta">
                题目: ${exam.total_count || 0} | 总分: ${exam.total_score || 0} |
                创建: ${exam.created_at ? new Date(exam.created_at).toLocaleString() : '-'} |
                创建者: ${exam.created_by || '-'}
            </div>
            <div class="exam-card-actions">
                <button class="btn btn-primary btn-sm" onclick="viewExam('${exam.exam_id}')">查看</button>
                ${exam.status === 'approved' ? `<button class="btn btn-success btn-sm" onclick="selectForGrade('${exam.exam_id}')">批阅</button>` : ''}
                ${state.user.role === 'admin' && exam.status === 'pending_review' ? `<button class="btn btn-success btn-sm" onclick="quickApprove('${exam.exam_id}')">通过</button>` : ''}
                ${state.user.role === 'admin' && exam.status === 'pending_review' ? `<button class="btn btn-warning btn-sm" onclick="quickReject('${exam.exam_id}')">驳回</button>` : ''}
                <button class="btn btn-danger btn-sm" onclick="deleteExam('${exam.exam_id}')">删除</button>
            </div>
        </div>
    `).join('');
}

// 查看试卷详情
async function viewExam(examId) {
    try {
        const exam = await api(`/exam/${examId}`);
        state.currentExam = exam;

        let content = renderExamDetail(exam);
        $('examModalContent').innerHTML = content;
        $('examModalTitle').textContent = exam.name || exam.topic || '试卷详情';
        $('examModal').style.display = 'flex';

        // 显示/隐藏按钮
        const isAdmin = state.user.role === 'admin';
        const isPending = exam.status === 'pending_review';
        const isApproved = exam.status === 'approved';

        $('modalApproveBtn').style.display = (isAdmin && isPending) ? 'inline-block' : 'none';
        $('modalRejectBtn').style.display = (isAdmin && isPending) ? 'inline-block' : 'none';
        $('modalGradeBtn').style.display = isApproved ? 'inline-block' : 'none';

    } catch (err) {
        showToast('加载失败: ' + err.message, 'error');
    }
}

// 渲染试卷详情
function renderExamDetail(exam) {
    let html = `<div class="exam-card-meta">ID: ${exam.exam_id}</div>`;
    html += renderExamPreview(exam);
    return html;
}

// 快速通过审核
async function quickApprove(examId) {
    if (!confirm('确定通过审核？')) return;

    try {
        await api(`/exam/${examId}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'approve' })
        });
        showToast('审核通过！', 'success');
        loadExams();
        loadStats();
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 快速驳回
async function quickReject(examId) {
    if (!confirm('确定驳回此试卷？')) return;

    try {
        await api(`/exam/${examId}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'reject' })
        });
        showToast('已驳回！', 'success');
        loadExams();
        loadStats();
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 审核通过
async function handleApproveExam() {
    if (!state.currentExam) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'approve' })
        });
        state.currentExam.status = 'approved';
        $('examModal').style.display = 'none';
        showToast('审核通过！', 'success');
        loadExams();
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 驳回试卷
async function handleRejectExam() {
    if (!state.currentExam) return;
    if (!confirm('确定驳回此试卷？')) return;

    try {
        await api(`/exam/${state.currentExam.exam_id}/review`, {
            method: 'POST',
            body: JSON.stringify({ action: 'reject' })
        });
        state.currentExam.status = 'rejected';
        $('examModal').style.display = 'none';
        showToast('已驳回！', 'success');
        loadExams();
    } catch (err) {
        showToast('操作失败: ' + err.message, 'error');
    }
}

// 删除试卷
async function deleteExam(examId) {
    if (!confirm('确定删除此试卷？')) return;

    try {
        await api(`/exam/${examId}`, { method: 'DELETE' });
        showToast('已删除', 'success');
        loadExams();
    } catch (err) {
        showToast('删除失败: ' + err.message, 'error');
    }
}

// 加载已通过审核的试卷（用于批阅）
async function loadApprovedExams() {
    try {
        const result = await api('/exam/list?status=approved&limit=100');
        const exams = result.exams || [];

        $('examSelect').innerHTML = '<option value="">请选择试卷...</option>' +
            exams.map(e => `<option value="${e.exam_id}">${e.name} (${e.total_count}题/${e.total_score}分)</option>`).join('');
    } catch (err) {
        console.error('加载试卷失败:', err);
    }
}

// 选择试卷批阅
async function handleExamSelect() {
    const examId = $('examSelect').value;
    if (!examId) {
        $('examQuestions').style.display = 'none';
        $('submitGradeBtn').style.display = 'none';
        return;
    }

    try {
        const exam = await api(`/exam/${examId}`);
        state.currentExam = exam;  // 保存到状态，供提交时使用
        renderGradeForm(exam);
        $('examQuestions').style.display = 'block';
        $('submitGradeBtn').style.display = 'inline-block';
    } catch (err) {
        showToast('加载试卷失败: ' + err.message, 'error');
    }
}

// 渲染批阅表单
function renderGradeForm(exam) {
    let html = `<h4>试卷: ${exam.name || exam.topic || '未命名'}</h4>`;

    // 选择题
    if (exam.choice_questions && exam.choice_questions.length > 0) {
        html += `<h5>选择题 (每题 ${exam.choice_questions[0]?.score || 2} 分)</h5>`;
        exam.choice_questions.forEach((q, i) => {
            html += `
                <div class="question-item">
                    <div class="question-content">${i + 1}. ${q.content}</div>
                    <div class="question-options">
                        ${q.options.map(opt => `
                            <label class="question-option">
                                <input type="radio" name="choice_${q.id}" value="${opt.charAt(0)}">
                                ${opt}
                            </label>
                        `).join('')}
                    </div>
                </div>
            `;
        });
    }

    // 填空题
    if (exam.blank_questions && exam.blank_questions.length > 0) {
        html += `<h5>填空题</h5>`;
        exam.blank_questions.forEach((q, i) => {
            html += `
                <div class="question-item">
                    <div class="question-content">${i + 1}. ${q.content}</div>
                    <input type="text" class="form-control" name="blank_${q.id}" placeholder="请输入答案" style="width:100%;padding:8px;margin-top:5px;border:1px solid #ddd;border-radius:4px;">
                </div>
            `;
        });
    }

    // 简答题
    if (exam.short_answer_questions && exam.short_answer_questions.length > 0) {
        html += `<h5>简答题</h5>`;
        exam.short_answer_questions.forEach((q, i) => {
            html += `
                <div class="question-item">
                    <div class="question-content">${i + 1}. ${q.content}</div>
                    <textarea name="short_answer_${q.id}" placeholder="请输入答案" rows="4" style="width:100%;padding:8px;margin-top:5px;border:1px solid #ddd;border-radius:4px;"></textarea>
                </div>
            `;
        });
    }

    $('examQuestions').innerHTML = html;
}

// 提交批阅
async function handleSubmitGrade() {
    const examId = $('examSelect').value;
    const studentName = $('studentName').value.trim() || '匿名';

    // 收集答案
    const answers = {};
    const exam = state.currentExam;

    if (exam.choice_questions) {
        exam.choice_questions.forEach(q => {
            const selected = document.querySelector(`input[name="choice_${q.id}"]:checked`);
            answers[`choice_${q.id}`] = selected ? selected.value : '';
        });
    }

    if (exam.blank_questions) {
        exam.blank_questions.forEach(q => {
            const input = document.querySelector(`input[name="blank_${q.id}"]`);
            answers[`blank_${q.id}`] = input ? input.value : '';
        });
    }

    if (exam.short_answer_questions) {
        exam.short_answer_questions.forEach(q => {
            const textarea = document.querySelector(`textarea[name="short_answer_${q.id}"]`);
            answers[`short_answer_${q.id}`] = textarea ? textarea.value : '';
        });
    }

    const btn = $('submitGradeBtn');
    btn.disabled = true;
    btn.textContent = '批阅中...';

    try {
        const report = await api(`/exam/${examId}/grade`, {
            method: 'POST',
            body: JSON.stringify({ student_name: studentName, answers })
        });

        showGradeResult(report);
        showToast('批阅完成！', 'success');

    } catch (err) {
        showToast('批阅失败: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '提交批阅';
    }
}

// 显示批阅结果
function showGradeResult(report) {
    let html = `
        <div class="score-display">
            <div class="score-value">${report.total_score}</div>
            <div class="score-rate">${report.score_rate}%</div>
            <div>得分 / ${report.max_score} 满分</div>
        </div>
    `;

    html += `<h4>各题得分</h4>`;
    report.questions.forEach((q, i) => {
        const resultClass = q.correct ? 'correct' : (q.score > 0 ? 'partial' : 'wrong');
        html += `
            <div class="question-result ${resultClass}">
                <div>
                    <strong>${getTypeText(q.type)} ${q.id}</strong>
                    <div style="font-size:13px;color:#666;">${q.content?.substring(0, 50)}...</div>
                </div>
                <div style="text-align:right;">
                    <div>${q.score} / ${q.max_score}</div>
                </div>
            </div>
        `;
    });

    $('gradeResultContent').innerHTML = html;
    $('gradeResultModal').style.display = 'flex';
}

// 选择试卷批阅（从列表页）
function selectForGrade(examId) {
    // 切换到批阅标签页
    document.querySelectorAll('.exam-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('.exam-tab[data-tab="grade"]').classList.add('active');
    document.querySelectorAll('.exam-panel').forEach(p => p.classList.remove('active'));
    $('gradePanel').classList.add('active');

    // 加载数据并选择试卷
    loadApprovedExams().then(() => {
        $('examSelect').value = examId;
        handleExamSelect();
    });
}

// 加载批阅报告
async function loadReports() {
    $('reportsList').innerHTML = '<div class="loading">加载中...</div>';

    try {
        const result = await api('/exam/report/list?page=1&limit=20');
        state.reports = result.reports || [];
        renderReportsList();
    } catch (err) {
        $('reportsList').innerHTML = `<div class="error">加载失败: ${err.message}</div>`;
    }
}

// 渲染报告列表
function renderReportsList() {
    if (!state.reports.length) {
        $('reportsList').innerHTML = '<div class="empty-state">暂无批阅报告</div>';
        return;
    }

    $('reportsList').innerHTML = state.reports.map(r => `
        <div class="exam-card">
            <div class="exam-card-header">
                <span class="exam-card-title">${r.student_name || '匿名学生'}</span>
                <span class="exam-status status-${r.score_rate >= 60 ? 'approved' : 'rejected'}">${r.score_rate}%</span>
            </div>
            <div class="exam-card-meta">
                试卷: ${r.exam_name || '未命名试卷'} |
                得分: ${r.total_score}/${r.max_score} |
                时间: ${r.graded_at ? new Date(r.graded_at).toLocaleString() : '-'}
            </div>
            <div class="exam-card-actions">
                <button class="btn btn-primary btn-sm" onclick="viewReport('${r.report_id}')">查看详情</button>
            </div>
        </div>
    `).join('');
}

// 查看报告详情
async function viewReport(reportId) {
    try {
        const report = await api(`/exam/report/${reportId}`);
        showGradeResult(report);
    } catch (err) {
        showToast('加载报告失败: ' + err.message, 'error');
    }
}

// Toast 提示
function showToast(message, type = 'info') {
    const toast = $('toast');
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

// 加载统计数据
async function loadStats() {
    try {
        // 并行加载试卷统计和报告统计
        const [examsResult, reportsResult] = await Promise.all([
            api('/exam/list?limit=100'),
            api('/exam/report/list?limit=100')
        ]);

        const exams = examsResult.exams || [];
        const reports = reportsResult.reports || [];

        $('totalExams').textContent = exams.length;
        $('approvedExams').textContent = exams.filter(e => e.status === 'approved').length;
        $('totalReports').textContent = reports.length;
    } catch (err) {
        console.error('加载统计失败:', err);
    }
}

// 全局函数（供 HTML onclick 调用）
window.viewExam = viewExam;
window.quickApprove = quickApprove;
window.quickReject = quickReject;
window.deleteExam = deleteExam;
window.selectForGrade = selectForGrade;
window.viewReport = viewReport;

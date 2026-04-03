"""
智能出题系统 - 整合管理器
整合出题工作流和批阅工作流
"""
import json
import os
import requests
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

# 导入配置
try:
    from config import DIFY_API_URL, DIFY_QUESTION_API_KEY, DIFY_GRADE_API_KEY
except ImportError:
    print("错误: 请创建config.py文件并配置API密钥")
    print("参考config.example.py")
    DIFY_API_URL = "https://api.dify.ai/v1"
    DIFY_QUESTION_API_KEY = ""
    DIFY_GRADE_API_KEY = ""

# 题库目录
QUESTION_BANK_DIR = "./题库"
REPORT_DIR = "./批阅报告"

# 试卷状态
EXAM_STATUS_DRAFT = "draft"           # 草稿
EXAM_STATUS_PENDING = "pending_review"  # 待审核
EXAM_STATUS_APPROVED = "approved"      # 已通过
EXAM_STATUS_REJECTED = "rejected"      # 已驳回


def call_dify_workflow(api_key: str, inputs: dict) -> dict:
    """调用Dify工作流"""
    url = f"{DIFY_API_URL}/workflows/run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": inputs,
        "response_mode": "blocking",
        "user": "exam-system"
    }

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()


def parse_json_response(result: dict) -> dict:
    """解析Dify返回结果，处理markdown包裹的JSON"""
    outputs = result.get("data", {}).get("outputs", {})

    # 处理返回结果，提取JSON
    if "result" in outputs:
        raw_result = outputs["result"]
        if isinstance(raw_result, str):
            # 去掉markdown代码块标记
            raw_result = raw_result.strip()
            if raw_result.startswith("```json"):
                raw_result = raw_result[7:]
            if raw_result.startswith("```"):
                raw_result = raw_result[3:]
            if raw_result.endswith("```"):
                raw_result = raw_result[:-3]
            raw_result = raw_result.strip()
            try:
                outputs["result"] = json.loads(raw_result)
            except:
                pass

    return outputs


def generate_exam(topic: str, choice_count: int = 3, blank_count: int = 2,
                  short_answer_count: int = 2, difficulty: int = 3,
                  choice_score: int = 2, blank_score: int = 3,
                  created_by: str = None, name: str = None) -> dict:
    """
    生成试卷

    Args:
        topic: 主题
        choice_count: 选择题数量
        blank_count: 填空题数量
        short_answer_count: 简答题数量
        difficulty: 难度(1-5)
        choice_score: 选择题每题分值（默认2分）
        blank_score: 填空题每题分值（默认3分）
        created_by: 创建者用户名
        name: 试卷名称（可选，默认为 "{topic}试卷"）

    Returns:
        试卷JSON（包含exam_id和status）
    """
    print(f"正在生成试卷: {topic}")

    inputs = {
        "topic": topic,
        "choice_count": choice_count,
        "blank_count": blank_count,
        "short_answer_count": short_answer_count,
        "difficulty": difficulty
    }

    result = call_dify_workflow(DIFY_QUESTION_API_KEY, inputs)

    # 打印完整响应用于调试
    print(f"API响应: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}...")

    # 解析返回结果
    outputs = result.get("data", {}).get("outputs", {})
    questions_json = outputs.get("questions", "{}")

    # 如果是字符串，解析为JSON
    if isinstance(questions_json, str):
        # 去掉可能的markdown代码块
        questions_json = questions_json.strip()
        if questions_json.startswith("```json"):
            questions_json = questions_json[7:]
        if questions_json.startswith("```"):
            questions_json = questions_json[3:]
        if questions_json.endswith("```"):
            questions_json = questions_json[:-3]
        questions_json = questions_json.strip()
        questions_json = json.loads(questions_json)

    # 添加分值字段
    for q in questions_json.get("choice_questions", []):
        q["score"] = choice_score
    for q in questions_json.get("blank_questions", []):
        q["score"] = blank_score
    # 简答题分值由LLM生成，保留reference_answer中的total_score

    # 重新计算总分
    total_score = 0
    total_score += len(questions_json.get("choice_questions", [])) * choice_score
    total_score += len(questions_json.get("blank_questions", [])) * blank_score
    for q in questions_json.get("short_answer_questions", []):
        total_score += q.get("reference_answer", {}).get("total_score", 0)
    questions_json["total_score"] = total_score

    # 添加元数据
    questions_json["exam_id"] = str(uuid.uuid4())
    questions_json["status"] = EXAM_STATUS_DRAFT
    questions_json["created_at"] = datetime.now().isoformat()
    questions_json["created_by"] = created_by
    questions_json["topic"] = topic
    questions_json["name"] = name or f"{topic}试卷"
    questions_json["total_count"] = (
        len(questions_json.get("choice_questions", [])) +
        len(questions_json.get("blank_questions", [])) +
        len(questions_json.get("short_answer_questions", []))
    )

    return questions_json


def save_exam(exam: dict, name: str = None) -> str:
    """
    保存试卷到题库

    Args:
        exam: 试卷JSON
        name: 文件名(不含扩展名)

    Returns:
        保存的文件路径
    """
    os.makedirs(QUESTION_BANK_DIR, exist_ok=True)

    # 使用 exam_id 作为文件名
    if name is None:
        exam_id = exam.get("exam_id", datetime.now().strftime('%Y%m%d_%H%M%S'))
        name = exam_id

    filepath = os.path.join(QUESTION_BANK_DIR, f"{name}.json")

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(exam, f, ensure_ascii=False, indent=2)

    print(f"试卷已保存: {filepath}")
    return filepath


def load_exam(filepath: str) -> dict:
    """加载试卷"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==================== 题库管理函数 ====================

def list_exams(status: str = None, page: int = 1, limit: int = 20) -> dict:
    """
    获取试卷列表

    Args:
        status: 状态过滤（draft/pending_review/approved/rejected）
        page: 页码
        limit: 每页数量

    Returns:
        {
            "exams": [...],
            "total": int,
            "page": int
        }
    """
    os.makedirs(QUESTION_BANK_DIR, exist_ok=True)

    exams = []
    for filename in os.listdir(QUESTION_BANK_DIR):
        if not filename.endswith('.json'):
            continue

        filepath = os.path.join(QUESTION_BANK_DIR, filename)
        try:
            exam = load_exam(filepath)
            # 状态过滤
            if status and exam.get("status") != status:
                continue
            # 只返回摘要信息
            exams.append({
                "exam_id": exam.get("exam_id", filename[:-5]),
                "name": exam.get("name") or exam.get("topic", "未命名试卷"),
                "topic": exam.get("topic", ""),
                "status": exam.get("status", "approved"),
                "total_count": exam.get("total_count", 0),
                "total_score": exam.get("total_score", 0),
                "created_at": exam.get("created_at", ""),
                "created_by": exam.get("created_by", ""),
                "filename": filename
            })
        except Exception as e:
            print(f"加载试卷失败 {filename}: {e}")
            continue

    # 按创建时间倒序
    exams.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # 分页
    total = len(exams)
    start = (page - 1) * limit
    end = start + limit

    return {
        "exams": exams[start:end],
        "total": total,
        "page": page
    }


def get_exam_by_id(exam_id: str) -> Optional[dict]:
    """
    根据 ID 获取试卷

    Args:
        exam_id: 试卷ID

    Returns:
        试卷JSON，如果不存在返回None
    """
    filepath = os.path.join(QUESTION_BANK_DIR, f"{exam_id}.json")
    if not os.path.exists(filepath):
        # 尝试遍历查找
        for filename in os.listdir(QUESTION_BANK_DIR):
            if not filename.endswith('.json'):
                continue
            fp = os.path.join(QUESTION_BANK_DIR, filename)
            try:
                exam = load_exam(fp)
                if exam.get("exam_id") == exam_id:
                    return exam
            except:
                continue
        return None

    return load_exam(filepath)


def update_exam(exam_id: str, exam_data: dict) -> Optional[dict]:
    """
    更新试卷

    Args:
        exam_id: 试卷ID
        exam_data: 新的试卷数据

    Returns:
        更新后的试卷，如果不存在返回None
    """
    exam = get_exam_by_id(exam_id)
    if not exam:
        return None

    # 保留不可修改的字段
    exam_data["exam_id"] = exam_id
    exam_data["created_at"] = exam.get("created_at")
    exam_data["created_by"] = exam.get("created_by")

    # 更新时间戳
    exam_data["updated_at"] = datetime.now().isoformat()

    # 重新计算统计
    exam_data["total_count"] = (
        len(exam_data.get("choice_questions", [])) +
        len(exam_data.get("blank_questions", [])) +
        len(exam_data.get("short_answer_questions", []))
    )

    # 保存
    filepath = os.path.join(QUESTION_BANK_DIR, f"{exam_id}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(exam_data, f, ensure_ascii=False, indent=2)

    return exam_data


def delete_exam(exam_id: str) -> bool:
    """
    删除试卷

    Args:
        exam_id: 试卷ID

    Returns:
        是否删除成功
    """
    filepath = os.path.join(QUESTION_BANK_DIR, f"{exam_id}.json")
    if os.path.exists(filepath):
        os.remove(filepath)
        return True

    # 尝试遍历查找
    for filename in os.listdir(QUESTION_BANK_DIR):
        if not filename.endswith('.json'):
            continue
        fp = os.path.join(QUESTION_BANK_DIR, filename)
        try:
            exam = load_exam(fp)
            if exam.get("exam_id") == exam_id:
                os.remove(fp)
                return True
        except:
            continue

    return False


# ==================== 审核函数 ====================

def review_exam(exam_id: str, action: str, questions: List[dict] = None,
                feedback: str = None) -> dict:
    """
    审核试卷

    Args:
        exam_id: 试卷ID
        action: 审核动作（approve/reject/partial）
        questions: 逐题审核时的题目修改（仅partial时使用）
        feedback: 审核意见

    Returns:
        审核结果
    """
    exam = get_exam_by_id(exam_id)
    if not exam:
        return {"success": False, "error": "试卷不存在"}

    if action == "approve":
        # 整体通过
        exam["status"] = EXAM_STATUS_APPROVED
        exam["reviewed_at"] = datetime.now().isoformat()
        if feedback:
            exam["review_feedback"] = feedback

        update_exam(exam_id, exam)
        return {"success": True, "status": EXAM_STATUS_APPROVED}

    elif action == "reject":
        # 整体驳回
        exam["status"] = EXAM_STATUS_REJECTED
        exam["reviewed_at"] = datetime.now().isoformat()
        if feedback:
            exam["review_feedback"] = feedback

        update_exam(exam_id, exam)
        return {"success": True, "status": EXAM_STATUS_REJECTED}

    elif action == "partial":
        # 逐题审核
        if not questions:
            return {"success": False, "error": "缺少题目审核信息"}

        approved_count = 0
        edited_count = 0
        deleted_count = 0

        for q_review in questions:
            q_type = q_review.get("type")
            q_id = q_review.get("id")

            # 找到对应题目列表
            if q_type == "choice":
                q_list = exam.get("choice_questions", [])
            elif q_type == "blank":
                q_list = exam.get("blank_questions", [])
            elif q_type == "short_answer":
                q_list = exam.get("short_answer_questions", [])
            else:
                continue

            # 找到题目索引
            q_idx = None
            for i, q in enumerate(q_list):
                if q.get("id") == q_id:
                    q_idx = i
                    break

            if q_idx is None:
                continue

            # 处理删除
            if q_review.get("delete"):
                q_list.pop(q_idx)
                deleted_count += 1
                continue

            # 处理编辑
            if q_review.get("edit"):
                q_list[q_idx].update(q_review["edit"])
                edited_count += 1

            # 处理通过
            if q_review.get("approved"):
                q_list[q_idx]["approved"] = True
                approved_count += 1

        # 更新试卷
        exam["status"] = EXAM_STATUS_PENDING
        exam["reviewed_at"] = datetime.now().isoformat()
        update_exam(exam_id, exam)

        return {
            "success": True,
            "status": EXAM_STATUS_PENDING,
            "approved_count": approved_count,
            "edited_count": edited_count,
            "deleted_count": deleted_count
        }

    return {"success": False, "error": "无效的审核动作"}


def submit_for_review(exam_id: str) -> dict:
    """
    提交试卷审核

    Args:
        exam_id: 试卷ID

    Returns:
        提交结果
    """
    exam = get_exam_by_id(exam_id)
    if not exam:
        return {"success": False, "error": "试卷不存在"}

    exam["status"] = EXAM_STATUS_PENDING
    exam["submitted_at"] = datetime.now().isoformat()

    update_exam(exam_id, exam)
    return {"success": True, "status": EXAM_STATUS_PENDING}


# ==================== 题目搜索 ====================

def search_questions(keyword: str, question_type: str = None,
                     difficulty: int = None, limit: int = 50) -> dict:
    """
    搜索题目

    Args:
        keyword: 搜索关键词
        question_type: 题型过滤（choice/blank/short_answer）
        difficulty: 难度过滤
        limit: 返回数量限制

    Returns:
        {
            "questions": [...],
            "total": int
        }
    """
    os.makedirs(QUESTION_BANK_DIR, exist_ok=True)

    results = []
    keyword_lower = keyword.lower()

    for filename in os.listdir(QUESTION_BANK_DIR):
        if not filename.endswith('.json'):
            continue

        filepath = os.path.join(QUESTION_BANK_DIR, filename)
        try:
            exam = load_exam(filepath)
            exam_id = exam.get("exam_id", filename[:-5])
            exam_name = exam.get("topic", filename[:-5])

            # 搜索选择题
            if not question_type or question_type == "choice":
                for q in exam.get("choice_questions", []):
                    if difficulty and q.get("difficulty") != difficulty:
                        continue
                    content = q.get("content", "").lower()
                    if keyword_lower in content:
                        results.append({
                            "exam_id": exam_id,
                            "exam_name": exam_name,
                            "type": "choice",
                            "question": q
                        })

            # 搜索填空题
            if not question_type or question_type == "blank":
                for q in exam.get("blank_questions", []):
                    if difficulty and q.get("difficulty") != difficulty:
                        continue
                    content = q.get("content", "").lower()
                    if keyword_lower in content:
                        results.append({
                            "exam_id": exam_id,
                            "exam_name": exam_name,
                            "type": "blank",
                            "question": q
                        })

            # 搜索简答题
            if not question_type or question_type == "short_answer":
                for q in exam.get("short_answer_questions", []):
                    if difficulty and q.get("difficulty") != difficulty:
                        continue
                    content = q.get("content", "").lower()
                    if keyword_lower in content:
                        results.append({
                            "exam_id": exam_id,
                            "exam_name": exam_name,
                            "type": "short_answer",
                            "question": q
                        })

        except Exception as e:
            print(f"搜索试卷失败 {filename}: {e}")
            continue

    return {
        "questions": results[:limit],
        "total": len(results)
    }


def grade_question(question: dict, student_answer: str) -> dict:
    """
    批阅单道题

    Args:
        question: 题目信息(含正确答案和分值)
        student_answer: 学生答案

    Returns:
        批阅结果
    """
    # 判断题型
    if 'options' in question:
        # 选择题
        question_type = "choice"
        correct_answer = question.get("answer", "")
        max_score = question.get("score", 2)  # 从试卷获取分值，默认2分
    elif 'reference_answer' in question:
        # 简答题 - 使用blank类型（填空和简答合并处理）
        question_type = "blank"
        correct_answer = json.dumps(question.get("reference_answer", {}), ensure_ascii=False)
        max_score = question.get("reference_answer", {}).get("total_score", 10)
    else:
        # 填空题
        question_type = "blank"
        correct_answer = question.get("answer", "")
        max_score = question.get("score", 3)  # 从试卷获取分值，默认3分

    inputs = {
        "question_id": question.get("id", 0),
        "question_type": question_type,
        "question_content": question.get("content", ""),
        "correct_answer": correct_answer,
        "student_answer": student_answer,
        "max_score": max_score
    }

    result = call_dify_workflow(DIFY_GRADE_API_KEY, inputs)
    outputs = parse_json_response(result)

    # 解析返回结果
    grade_result = outputs.get("result", {})

    # 如果是字符串，尝试解析JSON
    if isinstance(grade_result, str):
        grade_result = grade_result.strip()
        if grade_result.startswith("```json"):
            grade_result = grade_result[7:]
        if grade_result.startswith("```"):
            grade_result = grade_result[3:]
        if grade_result.endswith("```"):
            grade_result = grade_result[:-3]
        grade_result = grade_result.strip()
        try:
            grade_result = json.loads(grade_result)
        except:
            # 如果解析失败，返回默认结果
            grade_result = {"score": 0, "feedback": "批阅结果解析失败"}

    # 确保返回字典
    if not isinstance(grade_result, dict):
        grade_result = {"score": 0, "feedback": str(grade_result)}

    return grade_result


def grade_exam(exam_filepath: str, student_answers: dict, student_name: str = None) -> dict:
    """
    批阅整份试卷

    Args:
        exam_filepath: 试卷文件路径或exam_id
        student_answers: 学生答案，格式: {题型_题号: 答案}
                         例如: {"choice_1": "A", "blank_1": "答案", "short_answer_1": "学生作答"}
        student_name: 学生姓名

    Returns:
        批阅报告
    """
    # 支持 exam_id 或文件路径
    if not exam_filepath.endswith('.json'):
        exam = get_exam_by_id(exam_filepath)
        if not exam:
            raise ValueError(f"试卷不存在: {exam_filepath}")
    else:
        exam = load_exam(exam_filepath)

    report = {
        "report_id": str(uuid.uuid4()),
        "exam_id": exam.get("exam_id", ""),
        "exam_name": exam.get("topic", ""),
        "student_name": student_name or "匿名",
        "graded_at": datetime.now().isoformat(),
        "total_score": 0,
        "max_score": 0,
        "questions": []
    }

    # 批阅选择题
    for q in exam.get("choice_questions", []):
        qid = q.get("id", 0)
        key = f"choice_{qid}"
        student_answer = student_answers.get(key, "")

        result = grade_question(q, student_answer)

        q_score = result.get("score", 0)
        q_max = q.get("score", 2)  # 从试卷获取分值

        report["total_score"] += q_score
        report["max_score"] += q_max
        report["questions"].append({
            "type": "choice",
            "id": qid,
            "content": q.get("content", ""),
            "student_answer": student_answer,
            "correct_answer": q.get("answer", ""),
            "score": q_score,
            "max_score": q_max,
            "feedback": result.get("feedback", ""),
            "correct": result.get("correct", False)
        })

    # 批阅填空题
    for q in exam.get("blank_questions", []):
        qid = q.get("id", 0)
        key = f"blank_{qid}"
        student_answer = student_answers.get(key, "")

        result = grade_question(q, student_answer)

        q_score = result.get("score", 0)
        q_max = q.get("score", 3)  # 从试卷获取分值

        report["total_score"] += q_score
        report["max_score"] += q_max
        report["questions"].append({
            "type": "blank",
            "id": qid,
            "content": q.get("content", ""),
            "student_answer": student_answer,
            "correct_answer": q.get("answer", ""),
            "score": q_score,
            "max_score": q_max,
            "feedback": result.get("feedback", ""),
            "highlights": result.get("highlights", []),
            "shortcomings": result.get("shortcomings", [])
        })

    # 批阅简答题
    for q in exam.get("short_answer_questions", []):
        qid = q.get("id", 0)
        key = f"short_answer_{qid}"
        student_answer = student_answers.get(key, "")

        result = grade_question(q, student_answer)

        q_score = result.get("score", 0)
        q_max = q.get("reference_answer", {}).get("total_score", 10)

        report["total_score"] += q_score
        report["max_score"] += q_max
        report["questions"].append({
            "type": "short_answer",
            "id": qid,
            "content": q.get("content", ""),
            "student_answer": student_answer,
            "reference_answer": q.get("reference_answer", {}),
            "score": q_score,
            "max_score": q_max,
            "feedback": result.get("feedback", ""),
            "highlights": result.get("highlights", []),
            "shortcomings": result.get("shortcomings", []),
            "suggestions": result.get("suggestions", []),
            "score_details": result.get("score_details", [])
        })

    # 计算得分率
    report["score_rate"] = round(report["total_score"] / report["max_score"] * 100, 1) if report["max_score"] > 0 else 0

    return report


def save_grade_report(report: dict, student_name: str = None) -> str:
    """保存批阅报告"""
    os.makedirs(REPORT_DIR, exist_ok=True)

    # 使用 report_id 作为文件名
    report_id = report.get("report_id", datetime.now().strftime('%Y%m%d_%H%M%S'))
    student = student_name or report.get("student_name", "student")

    filename = f"{student}_{report_id[:8]}.json"
    filepath = os.path.join(REPORT_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"批阅报告已保存: {filepath}")
    return filepath


def get_report_by_id(report_id: str) -> Optional[dict]:
    """
    根据ID获取批阅报告

    Args:
        report_id: 报告ID

    Returns:
        报告内容
    """
    os.makedirs(REPORT_DIR, exist_ok=True)

    for filename in os.listdir(REPORT_DIR):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(REPORT_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                report = json.load(f)
            if report.get("report_id") == report_id:
                return report
        except:
            continue

    return None


def list_reports(page: int = 1, limit: int = 20) -> dict:
    """
    获取批阅报告列表

    Args:
        page: 页码
        limit: 每页数量

    Returns:
        {"reports": [...], "total": int, "page": int}
    """
    os.makedirs(REPORT_DIR, exist_ok=True)

    reports = []
    for filename in os.listdir(REPORT_DIR):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(REPORT_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                report = json.load(f)
            reports.append({
                "report_id": report.get("report_id", ""),
                "exam_id": report.get("exam_id", ""),
                "exam_name": report.get("exam_name", ""),
                "student_name": report.get("student_name", ""),
                "total_score": report.get("total_score", 0),
                "max_score": report.get("max_score", 0),
                "score_rate": report.get("score_rate", 0),
                "graded_at": report.get("graded_at", ""),
                "filename": filename
            })
        except:
            continue

    # 按时间倒序
    reports.sort(key=lambda x: x.get("graded_at", ""), reverse=True)

    total = len(reports)
    start = (page - 1) * limit
    end = start + limit

    return {
        "reports": reports[start:end],
        "total": total,
        "page": page
    }


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 示例1: 生成并保存试卷
    # exam = generate_exam(
    #     topic="国家社科基金项目申报",
    #     choice_count=3,
    #     blank_count=2,
    #     short_answer_count=2,
    #     difficulty=3
    # )
    # save_exam(exam, "test1")

    # 示例2: 批阅试卷
    # exam_file = "./题库/test1.json"
    # student_answers = {
    #     "choice_1": "A",
    #     "choice_2": "B",
    #     "choice_3": "C",
    #     "blank_1": "重点课题",
    #     "blank_2": "申请人",
    #     "short_answer_1": "国家社科基金项目包括重点项目、一般项目和青年项目等类别",
    #     "short_answer_2": "申报流程包括提交申请书、专家评审、立项审批等步骤"
    # }
    # report = grade_exam(exam_file, student_answers)
    # save_grade_report(report, "张三")

    print("请先配置DIFY_QUESTION_API_KEY和DIFY_GRADE_API_KEY环境变量")
    print("然后取消注释示例代码运行")

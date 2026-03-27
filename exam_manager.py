"""
智能出题系统 - 整合管理器
整合出题工作流和批阅工作流
"""
import json
import os
import requests
from datetime import datetime

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
                  choice_score: int = 2, blank_score: int = 3) -> dict:
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

    Returns:
        试卷JSON
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

    if name is None:
        name = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    filepath = os.path.join(QUESTION_BANK_DIR, f"{name}.json")

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(exam, f, ensure_ascii=False, indent=2)

    print(f"试卷已保存: {filepath}")
    return filepath


def load_exam(filepath: str) -> dict:
    """加载试卷"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


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


def grade_exam(exam_filepath: str, student_answers: dict) -> dict:
    """
    批阅整份试卷

    Args:
        exam_filepath: 试卷文件路径
        student_answers: 学生答案，格式: {题型_题号: 答案}
                         例如: {"choice_1": "A", "blank_1": "答案", "short_answer_1": "学生作答"}

    Returns:
        批阅报告
    """
    exam = load_exam(exam_filepath)

    report = {
        "exam_file": exam_filepath,
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
    reports_dir = "./批阅报告"
    os.makedirs(reports_dir, exist_ok=True)

    if student_name is None:
        student_name = "student"

    filename = f"{student_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(reports_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"批阅报告已保存: {filepath}")
    return filepath


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

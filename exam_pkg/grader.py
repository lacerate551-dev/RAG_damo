"""
批题器 - 本地批阅逻辑（后续可迁移到 Dify 工作流）

核心功能：
1. 本地批阅选择题/判断题
2. 填空题模糊匹配
3. 主观题 LLM 评分
4. 并发批阅 + 限流 + 顺序保持

使用方式：
    from exam_pkg.grader import AnswerGrader

    grader = AnswerGrader()
    results = grader.grade_answers(answers)
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from typing import List, Dict, Any, Optional

# 导入 LLM 配置
try:
    from config import API_KEY, BASE_URL, MODEL
    LLM_AVAILABLE = True
except ImportError:
    API_KEY = None
    BASE_URL = None
    MODEL = None
    LLM_AVAILABLE = False


# ==================== 装饰器 ====================

def retry(times: int = 2, delay: float = 1.0):
    """
    🔥 P1 改进：重试装饰器

    Args:
        times: 重试次数
        delay: 重试间隔（秒）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if i < times - 1:
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


# ==================== 限流 ====================

# 🔥 P2 改进：限流信号量
MAX_CONCURRENT_GRADING = 3
grading_semaphore = threading.Semaphore(MAX_CONCURRENT_GRADING)


# ==================== 本地批阅函数 ====================

def grade_objective(answer: Dict) -> Dict:
    """
    批阅客观题（选择/判断）

    🔥 本地直接判断，无 LLM 调用
    """
    q_type = answer['question_type']
    question_content = answer.get('question_content', {})
    correct_answer = question_content.get('answer')
    student_answer = answer.get('student_answer')
    max_score = answer.get('max_score', 2.0)

    # 判断正确性
    if q_type == 'single_choice':
        correct = student_answer == correct_answer
    elif q_type == 'multiple_choice':
        # 多选题：答案顺序无关
        correct = set(student_answer) == set(correct_answer) if isinstance(student_answer, list) else False
    elif q_type == 'true_false':
        correct = student_answer == correct_answer
    else:
        correct = False

    return {
        "question_id": answer.get('question_id'),
        "score": max_score if correct else 0,
        "max_score": max_score,
        "correct": correct,
        "feedback": f"正确答案: {correct_answer}" if not correct else "正确！"
    }


def grade_fill_blank(answer: Dict) -> Dict:
    """
    批阅填空题 - 支持同义词匹配

    填空题答案格式：[["答案1", "同义词1", ...], ["答案2", ...], ...]
    学生答案格式：["学生答案1", "学生答案2", ...]
    """
    question_content = answer.get('question_content', {})
    correct_answers = question_content.get('answer', [])  # [[答案1, 同义词...], ...]
    student_answers = answer.get('student_answer', [])
    max_score = answer.get('max_score', 4.0)

    if not correct_answers or not student_answers:
        return {
            "question_id": answer.get('question_id'),
            "score": 0,
            "max_score": max_score,
            "details": {"error": "答案格式错误"}
        }

    # 计算每空分数
    score_per_blank = max_score / len(correct_answers)

    blank_scores = []
    total_score = 0

    for i, correct_list in enumerate(correct_answers):
        if i >= len(student_answers):
            blank_scores.append(0)
            continue

        student_ans = student_answers[i]

        # 检查是否匹配任一正确答案
        matched = any(
            fuzzy_match(student_ans, correct)
            for correct in correct_list
        )

        blank_score = score_per_blank if matched else 0
        blank_scores.append(blank_score)
        total_score += blank_score

    return {
        "question_id": answer.get('question_id'),
        "score": round(total_score, 1),
        "max_score": max_score,
        "details": {
            "blank_scores": blank_scores,
            "correct_answers": correct_answers
        }
    }


def fuzzy_match(student_answer: str, correct_answer: str) -> bool:
    """
    模糊匹配（支持同义词）

    当前实现：精确匹配（忽略前后空格、大小写）
    TODO: 可以扩展为语义相似度匹配
    """
    if not student_answer or not correct_answer:
        return False

    # 标准化：去空格、转小写
    s = student_answer.strip().lower()
    c = correct_answer.strip().lower()

    return s == c


# ==================== AnswerGrader 类 ====================

class AnswerGrader:
    """本地批题器 - 使用本地 OpenAI 客户端"""

    def __init__(self):
        self.client = None
        if LLM_AVAILABLE and API_KEY:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
            except ImportError:
                pass
        self.model = MODEL

    def grade_answers(self, answers: List[Dict]) -> List[Dict]:
        """
        批阅答案列表

        🔥 P1 改进：
        - 本地批阅选择题/判断题
        - 填空题本地模糊匹配
        - 主观题调用 LLM 评分
        - 结果顺序保持
        """
        results_map = {}

        # 分离题型
        local_questions = []  # 选择题、判断题
        fill_blank_questions = []  # 填空题
        llm_questions = []  # 主观题

        for ans in answers:
            q_type = ans.get('question_type')
            if q_type in ['single_choice', 'multiple_choice', 'true_false']:
                local_questions.append(ans)
            elif q_type == 'fill_blank':
                fill_blank_questions.append(ans)
            else:
                llm_questions.append(ans)

        # 本地批阅选择题/判断题
        for ans in local_questions:
            result = grade_objective(ans)
            results_map[ans.get('question_id')] = result

        # 本地批阅填空题
        for ans in fill_blank_questions:
            result = grade_fill_blank(ans)
            results_map[ans.get('question_id')] = result

        # 🔥 P1 改进：并发调用 LLM 批阅主观题
        if llm_questions:
            self._grade_subjective_concurrently(llm_questions, results_map)

        # 🔥 P1 改进：按原始顺序重组结果
        results = [results_map.get(ans.get('question_id')) for ans in answers]

        return results

    def _grade_subjective_concurrently(self, questions: List[Dict], results_map: Dict):
        """并发批阅主观题"""
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_GRADING) as executor:
            # 建立映射关系
            future_to_qid = {
                executor.submit(self._grade_subjective, ans): ans.get('question_id')
                for ans in questions
            }

            # 收集结果
            for future in as_completed(future_to_qid, timeout=60):
                qid = future_to_qid[future]
                try:
                    result = future.result(timeout=15)
                    results_map[qid] = result
                except Exception as e:
                    # 失败时返回默认结果
                    results_map[qid] = {
                        "question_id": qid,
                        "score": 0,
                        "max_score": next(
                            (a.get('max_score', 10) for a in questions if a.get('question_id') == qid),
                            10
                        ),
                        "error": str(e)
                    }

    @retry(times=2, delay=1)
    def _grade_subjective(self, answer: Dict) -> Dict:
        """
        批阅主观题 - 调用 LLM 评分

        🔥 P1 改进：带重试
        """
        with grading_semaphore:  # 限流
            prompt = self._build_grading_prompt(answer)
            response = self._call_llm(prompt)
            return self._parse_grading_result(response, answer)

    def _build_grading_prompt(self, answer: Dict) -> str:
        """构造评分 Prompt"""
        question_content = answer.get('question_content', {})
        scoring_points = question_content.get('data', {}).get('scoring_points', [])

        return f"""请批阅以下简答题。

## 题目
{question_content.get('stem', '')}

## 参考答案
{question_content.get('answer', '')}

## 评分标准
{json.dumps(scoring_points, ensure_ascii=False, indent=2)}

## 学生答案
{answer.get('student_answer', '')}

## 满分
{answer.get('max_score', 10)} 分

## 输出约束
1. 必须输出合法 JSON
2. score 不能超过满分
3. achieved 为 0-1 之间的比例

## 输出格式（JSON）
{{
  "score": 得分,
  "scoring_breakdown": [
    {{"point": "要点名称", "weight": 权重, "achieved": 实际得分比例, "comment": "评语"}}
  ],
  "highlights": ["亮点1", "亮点2"],
  "shortcomings": ["不足1"],
  "overall_feedback": "整体评价"
}}

请直接输出 JSON："""

    def _call_llm(self, prompt: str) -> str:
        """调用本地 LLM"""
        if not self.client:
            # 无 LLM 客户端，返回默认评分
            return json.dumps({"score": 0, "overall_feedback": "LLM 未配置"})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的阅卷老师，请严格按照JSON格式输出评分结果。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            return response.choices[0].message.content

        except Exception as e:
            raise Exception(f"LLM 调用失败: {e}")

    def _parse_grading_result(self, response: str, answer: Dict) -> Dict:
        """解析评分结果"""
        max_score = answer.get('max_score', 10)

        try:
            # 尝试解析 JSON
            result = json.loads(response)
            score = min(result.get('score', 0), max_score)  # 不能超过满分

            return {
                "question_id": answer.get('question_id'),
                "score": score,
                "max_score": max_score,
                "details": {
                    "scoring_breakdown": result.get('scoring_breakdown', []),
                    "highlights": result.get('highlights', []),
                    "shortcomings": result.get('shortcomings', []),
                    "overall_feedback": result.get('overall_feedback', '')
                }
            }
        except:
            # 解析失败，返回默认
            return {
                "question_id": answer.get('question_id'),
                "score": 0,
                "max_score": max_score,
                "details": {"error": "评分结果解析失败"}
            }


# ==================== 批题入口函数 ====================

def grade_answers(answers: List[Dict], request_id: str = None) -> Dict:
    """
    批阅答案入口函数

    🔥 P1/P2 改进：
    - 加 timeout + retry
    - 结果顺序保持
    - 限流控制

    Args:
        answers: 答案列表
        request_id: 请求 ID（幂等性支持）

    Returns:
        批阅结果
    """
    grader = AnswerGrader()
    results = grader.grade_answers(answers)

    # 计算总分
    total_score = sum(r.get('score', 0) for r in results if r)
    total_max = sum(r.get('max_score', 0) for r in results if r)

    return {
        "success": True,
        "request_id": request_id,
        "results": results,
        "total_score": round(total_score, 1),
        "total_max_score": total_max,
        "score_rate": round(total_score / total_max * 100, 1) if total_max > 0 else 0
    }

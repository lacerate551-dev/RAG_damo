"""
智能出题系统 - 自动演示

自动演示完整的出题→答题→批阅流程
"""
import json
import sys
import os

# 解决Windows控制台编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from exam_manager import generate_exam, save_exam, grade_exam, save_grade_report


def demo():
    """完整流程演示"""

    print("=" * 60)
    print("智能出题系统 - 完整流程演示")
    print("=" * 60)

    # ==================== 第一步：生成试卷 ====================
    print("\n【第一步】生成试卷")
    print("-" * 60)

    topic = "科研项目管理制度"
    choice_score = 2  # 选择题每题分值
    blank_score = 3   # 填空题每题分值

    print(f"主题: {topic}")
    print(f"选择题: 2 道，每题 {choice_score} 分")
    print(f"填空题: 1 道，每题 {blank_score} 分")
    print(f"简答题: 1 道（分值由AI生成）")
    print(f"难度: 2 (基础理解)")

    print("\n正在调用Dify出题工作流...")
    exam = generate_exam(
        topic=topic,
        choice_count=2,
        blank_count=1,
        short_answer_count=1,
        difficulty=2,
        choice_score=choice_score,
        blank_score=blank_score
    )

    filepath = save_exam(exam, "demo_exam")
    print(f"\n试卷已保存: {filepath}")

    # 显示试卷
    print("\n" + "=" * 60)
    print("生成的试卷")
    print("=" * 60)

    for q in exam.get("choice_questions", []):
        print(f"\n【选择题{q['id']}】{q['content']}")
        for opt in q.get("options", []):
            print(f"  {opt}")
        print(f"  ★ 正确答案: {q['answer']}")

    for q in exam.get("blank_questions", []):
        print(f"\n【填空题{q['id']}】{q['content']}")
        print(f"  ★ 正确答案: {q['answer']}")

    for q in exam.get("short_answer_questions", []):
        print(f"\n【简答题{q['id']}】{q['content']}")
        ref = q.get("reference_answer", {})
        print(f"  ★ 参考答案:")
        for p in ref.get("points", []):
            print(f"      - {p['point']} ({p['score']}分)")

    # ==================== 第二步：模拟学生答题 ====================
    print("\n" + "=" * 60)
    print("【第二步】模拟学生答题")
    print("=" * 60)

    # 构造学生答案（模拟学生作答）
    student_answers = {}

    print("\n学生答案:")

    # 选择题答案
    for i, q in enumerate(exam.get("choice_questions", [])):
        qid = q["id"]
        # 模拟：第一题答对，第二题答错
        if i == 0:
            ans = q["answer"]  # 正确答案
            print(f"  选择题{qid}: {ans} (正确)")
        else:
            ans = "A"  # 随机错误答案
            print(f"  选择题{qid}: {ans} (错误，正确答案是{q['answer']})")
        student_answers[f"choice_{qid}"] = ans

    # 填空题答案
    for q in exam.get("blank_questions", []):
        qid = q["id"]
        correct = q["answer"]
        # 模拟：部分正确
        ans = correct[:len(correct)//2] if len(correct) > 2 else "错误答案"
        print(f"  填空题{qid}: {ans} (部分正确，正确答案是'{correct}')")
        student_answers[f"blank_{qid}"] = ans

    # 简答题答案
    for q in exam.get("short_answer_questions", []):
        qid = q["id"]
        # 模拟：用自己的话回答部分要点
        ans = "根据项目管理制度的要求，科研项目需要按照规定的流程进行申报、执行和验收。项目经费需要专款专用，不得挪作他用。"
        print(f"  简答题{qid}: {ans[:50]}...")
        student_answers[f"short_answer_{qid}"] = ans

    # ==================== 第三步：自动批阅 ====================
    print("\n" + "=" * 60)
    print("【第三步】自动批阅")
    print("=" * 60)

    print("\n正在调用Dify批阅工作流...")
    print("(每道题都会调用Dify API进行批阅)")

    report = grade_exam(filepath, student_answers)

    # ==================== 第四步：显示结果 ====================
    print("\n" + "=" * 60)
    print("【第四步】批阅结果")
    print("=" * 60)

    print(f"\n总成绩: {report['total_score']}/{report['max_score']} 分")
    print(f"得分率: {report['score_rate']}%")

    print("\n详细得分:")
    print("-" * 60)

    for q in report["questions"]:
        qtype = {"choice": "选择题", "blank": "填空题", "short_answer": "简答题"}[q["type"]]

        if qtype == "选择题":
            status = "✓ 正确" if q.get("correct") else "✗ 错误"
        else:
            status = f"{q['score']}/{q['max_score']}分"

        print(f"\n{qtype}{q['id']}: {status}")
        print(f"  学生答案: {q['student_answer']}")

        if qtype == "选择题":
            print(f"  正确答案: {q['correct_answer']}")
        else:
            print(f"  参考答案: {str(q.get('reference_answer', q.get('correct_answer', '')))[:60]}...")

        if q.get("feedback"):
            print(f"  评语: {q['feedback'][:100]}...")

    # 保存报告
    report_path = save_grade_report(report, "演示学生")

    print("\n" + "=" * 60)
    print("演示完成！")
    print("=" * 60)

    print(f"\n生成的文件:")
    print(f"  📄 试卷: {filepath}")
    print(f"  📊 报告: {report_path}")

    print("\n提示:")
    print("  - 试卷文件保存在 '题库/' 目录")
    print("  - 批阅报告保存在 '批阅报告/' 目录")
    print("  - 可以直接运行 'python run_exam.py' 进行交互式操作")


if __name__ == "__main__":
    demo()

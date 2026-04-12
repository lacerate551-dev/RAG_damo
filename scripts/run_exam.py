"""
智能出题系统 - 完整使用示例

演示从出题到批阅的完整流程
"""
import json
import sys
import os

# 解决Windows控制台编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from exam_manager import generate_exam, save_exam, grade_exam, save_grade_report, load_exam


def interactive_mode():
    """交互式模式 - 完整的出题批阅流程"""

    print("=" * 60)
    print("智能出题系统 - 交互式模式")
    print("=" * 60)

    # ==================== 第一步：生成试卷 ====================
    print("\n【第一步】生成试卷")
    print("-" * 60)

    topic = input("请输入出题主题（如：国家社科基金项目申报）: ").strip()
    if not topic:
        topic = "国家社科基金项目申报"
        print(f"使用默认主题: {topic}")

    try:
        choice_count = int(input("选择题数量（默认3）: ") or "3")
        blank_count = int(input("填空题数量（默认2）: ") or "2")
        short_answer_count = int(input("简答题数量（默认2）: ") or "2")
        difficulty = int(input("难度（1-5，默认3）: ") or "3")
        choice_score = int(input("选择题每题分值（默认2）: ") or "2")
        blank_score = int(input("填空题每题分值（默认3）: ") or "3")
    except ValueError:
        choice_count, blank_count, short_answer_count, difficulty = 3, 2, 2, 3
        choice_score, blank_score = 2, 3

    print(f"\n正在生成试卷...")
    print(f"  主题: {topic}")
    print(f"  选择题: {choice_count} 道，每题 {choice_score} 分")
    print(f"  填空题: {blank_count} 道，每题 {blank_score} 分")
    print(f"  简答题: {short_answer_count} 道（分值由AI生成）")
    print(f"  难度: {difficulty}")

    # 生成试卷
    exam = generate_exam(
        topic=topic,
        choice_count=choice_count,
        blank_count=blank_count,
        short_answer_count=short_answer_count,
        difficulty=difficulty,
        choice_score=choice_score,
        blank_score=blank_score
    )

    # 保存试卷
    exam_name = input(f"\n试卷名称（默认: {topic}）: ").strip() or topic
    filepath = save_exam(exam, exam_name)

    # 显示试卷预览
    print("\n" + "=" * 60)
    print("试卷预览")
    print("=" * 60)

    for q in exam.get("choice_questions", []):
        print(f"\n【选择题{q['id']}】（{q.get('score', 2)}分）{q['content']}")
        for opt in q.get("options", []):
            print(f"  {opt}")
        print(f"  ★ 答案: {q['answer']}")

    for q in exam.get("blank_questions", []):
        print(f"\n【填空题{q['id']}】（{q.get('score', 3)}分）{q['content']}")
        print(f"  ★ 答案: {q['answer']}")

    for q in exam.get("short_answer_questions", []):
        ref = q.get("reference_answer", {})
        total = ref.get("total_score", 0)
        print(f"\n【简答题{q['id']}】（{total}分）{q['content']}")
        print(f"  ★ 参考答案:")
        for p in ref.get("points", []):
            print(f"      - {p['point']} ({p['score']}分)")

    # ==================== 第二步：学生答题 ====================
    print("\n" + "=" * 60)
    print("【第二步】学生答题")
    print("=" * 60)

    student_name = input("\n学生姓名: ").strip() or "学生"
    student_answers = {}

    print("\n请依次输入答案（直接回车跳过）:")

    # 选择题
    print("\n--- 选择题 ---")
    for q in exam.get("choice_questions", []):
        qid = q["id"]
        ans = input(f"第{qid}题答案（A/B/C/D）: ").strip().upper()
        if ans in ["A", "B", "C", "D"]:
            student_answers[f"choice_{qid}"] = ans

    # 填空题
    print("\n--- 填空题 ---")
    for q in exam.get("blank_questions", []):
        qid = q["id"]
        ans = input(f"第{qid}题答案: ").strip()
        if ans:
            student_answers[f"blank_{qid}"] = ans

    # 简答题
    print("\n--- 简答题 ---")
    for q in exam.get("short_answer_questions", []):
        qid = q["id"]
        print(f"\n第{qid}题: {q['content']}")
        ans = input("答案: ").strip()
        if ans:
            student_answers[f"short_answer_{qid}"] = ans

    # ==================== 第三步：自动批阅 ====================
    print("\n" + "=" * 60)
    print("【第三步】自动批阅")
    print("=" * 60)

    print("\n正在批阅试卷...")
    report = grade_exam(filepath, student_answers)

    # ==================== 第四步：显示结果 ====================
    print("\n" + "=" * 60)
    print("【第四步】批阅结果")
    print("=" * 60)

    print(f"\n学生: {student_name}")
    print(f"总分: {report['total_score']}/{report['max_score']} 分")
    print(f"得分率: {report['score_rate']}%")

    print("\n各题得分:")
    for q in report["questions"]:
        qtype = {"choice": "选择题", "blank": "填空题", "short_answer": "简答题"}[q["type"]]
        status = "✓" if q.get("correct", q["score"] > 0) else "✗"
        print(f"  {status} {qtype}{q['id']}: {q['score']}/{q['max_score']} 分")
        if q.get("feedback"):
            fb = q["feedback"][:80] + "..." if len(q.get("feedback", "")) > 80 else q.get("feedback", "")
            print(f"      评语: {fb}")

    # 保存报告
    report_path = save_grade_report(report, student_name)

    print("\n" + "=" * 60)
    print("完成！")
    print("=" * 60)
    print(f"\n文件保存位置:")
    print(f"  试卷: {filepath}")
    print(f"  报告: {report_path}")


def batch_mode():
    """批处理模式 - 使用已有试卷批阅"""

    print("=" * 60)
    print("智能出题系统 - 批处理模式")
    print("=" * 60)

    # 选择试卷
    exam_dir = "./题库"
    if not os.path.exists(exam_dir):
        print("题库目录不存在，请先使用交互模式生成试卷")
        return

    exams = [f for f in os.listdir(exam_dir) if f.endswith(".json")]
    if not exams:
        print("题库中没有试卷，请先使用交互模式生成试卷")
        return

    print("\n可用的试卷:")
    for i, exam_file in enumerate(exams, 1):
        print(f"  {i}. {exam_file}")

    choice = input("\n选择试卷编号: ").strip()
    try:
        exam_file = exams[int(choice) - 1]
        exam_path = os.path.join(exam_dir, exam_file)
    except (ValueError, IndexError):
        print("无效的选择")
        return

    # 加载试卷
    exam = load_exam(exam_path)
    print(f"\n已加载试卷: {exam_file}")
    print(f"  选择题: {len(exam.get('choice_questions', []))} 道")
    print(f"  填空题: {len(exam.get('blank_questions', []))} 道")
    print(f"  简答题: {len(exam.get('short_answer_questions', []))} 道")

    # 输入答案
    student_name = input("\n学生姓名: ").strip() or "学生"
    student_answers = {}

    print("\n请依次输入答案:")

    for q in exam.get("choice_questions", []):
        ans = input(f"选择题{q['id']}（A/B/C/D）: ").strip().upper()
        if ans in ["A", "B", "C", "D"]:
            student_answers[f"choice_{q['id']}"] = ans

    for q in exam.get("blank_questions", []):
        ans = input(f"填空题{q['id']}: ").strip()
        if ans:
            student_answers[f"blank_{q['id']}"] = ans

    for q in exam.get("short_answer_questions", []):
        print(f"\n简答题{q['id']}: {q['content']}")
        ans = input("答案: ").strip()
        if ans:
            student_answers[f"short_answer_{q['id']}"] = ans

    # 批阅
    print("\n正在批阅...")
    report = grade_exam(exam_path, student_answers)

    # 显示结果
    print(f"\n批阅结果:")
    print(f"  总分: {report['total_score']}/{report['max_score']} 分")
    print(f"  得分率: {report['score_rate']}%")

    # 保存报告
    save_grade_report(report, student_name)


def main():
    """主入口"""
    print("\n请选择模式:")
    print("  1. 交互模式 - 完整流程（出题→答题→批阅）")
    print("  2. 批处理模式 - 使用已有试卷批阅")
    print("  3. 仅生成试卷")
    print("  0. 退出")

    choice = input("\n请选择（0-3）: ").strip()

    if choice == "1":
        interactive_mode()
    elif choice == "2":
        batch_mode()
    elif choice == "3":
        # 仅生成试卷
        topic = input("请输入出题主题: ").strip()
        if not topic:
            print("主题不能为空")
            return
        print("正在生成试卷...")
        exam = generate_exam(topic)
        name = input("试卷名称: ").strip() or topic
        save_exam(exam, name)
    elif choice == "0":
        print("再见！")
    else:
        print("无效的选择")


if __name__ == "__main__":
    main()

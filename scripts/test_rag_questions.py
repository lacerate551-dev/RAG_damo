# -*- coding: utf-8 -*-
"""
RAG 系统测试脚本

自动执行 40 个测试问题并记录结果
"""

import sys
import os
import json
import time
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 测试问题列表
TEST_QUESTIONS = [
    # 一、精确匹配测试（10题）
    {"id": 1, "category": "精确匹配", "question": "智启科技成立于哪一年？", "expected": "2015年3月", "source": "公司简介.txt / 员工手册.txt"},
    {"id": 2, "category": "精确匹配", "question": "公司的客服热线是多少？", "expected": "400-888-8888", "source": "公司简介.txt"},
    {"id": 3, "category": "精确匹配", "question": "公司总部位于哪里？", "expected": "北京市海淀区中关村大街1号科技大厦15层", "source": "公司简介.txt"},
    {"id": 4, "category": "精确匹配", "question": "ZDAP平台标准版支持多少并发用户？", "expected": "50人", "source": "产品手册.txt"},
    {"id": 5, "category": "精确匹配", "question": "企业版单表最大支持多少行数据？", "expected": "1亿行", "source": "产品手册.txt"},
    {"id": 6, "category": "精确匹配", "question": "年假满10年不满20年可以休多少天？", "expected": "10天", "source": "员工手册.txt / 常见问题.txt"},
    {"id": 7, "category": "精确匹配", "question": "产假可以休多少天？", "expected": "158天", "source": "员工手册.txt / 常见问题.txt"},
    {"id": 8, "category": "精确匹配", "question": "技术研发中心的负责人是谁？", "expected": "张明远（技术总监）", "source": "公司简介.txt / 组织架构说明.txt"},
    {"id": 9, "category": "精确匹配", "question": "市场营销部有多少人？", "expected": "120人", "source": "公司简介.txt / 组织架构说明.txt"},
    {"id": 10, "category": "精确匹配", "question": "上海分公司的负责人是谁？", "expected": "华东区总经理 张华", "source": "组织架构说明.txt"},

    # 二、语义理解测试（6题）
    {"id": 11, "category": "语义理解", "question": "公司的愿景是什么？", "expected": "成为全球领先的智能数据服务提供商", "source": "公司简介.txt / 员工手册.txt"},
    {"id": 12, "category": "语义理解", "question": "ZDAP的智能预警功能有哪些通知方式？", "expected": "邮件、短信、企业微信、钉钉", "source": "产品手册.txt"},
    {"id": 13, "category": "语义理解", "question": "什么是直连数据集？", "expected": "直接查询源数据库，实时性强", "source": "产品手册.txt"},
    {"id": 14, "category": "语义理解", "question": "入职当天需要做什么？", "expected": "签订劳动合同、领取工牌、开通账号、参观、培训等", "source": "常见问题.txt"},
    {"id": 15, "category": "语义理解", "question": "请假4天需要谁审批？", "expected": "部门负责人 + 人力资源部审批", "source": "常见问题.txt"},
    {"id": 16, "category": "语义理解", "question": "如何申请外部培训？", "expected": "OA系统提交申请→填写信息→部门负责人审批→人力资源部审批→超5000元签服务协议", "source": "常见问题.txt"},

    # 三、跨文档关联测试（4题）
    {"id": 17, "category": "跨文档关联", "question": "公司有哪些分公司，分别在哪些城市？", "expected": "上海、深圳、成都、武汉四家分公司", "source": "公司简介.txt + 组织架构说明.txt"},
    {"id": 18, "category": "跨文档关联", "question": "技术研发中心下设哪些团队，各自的职责是什么？", "expected": "AI算法组、数据工程组、平台开发组、前端开发组、测试组", "source": "公司简介.txt + 组织架构说明.txt"},
    {"id": 19, "category": "跨文档关联", "question": "公司的薪酬由哪些部分组成？绩效奖金的范围是多少？", "expected": "基本工资+绩效奖金+年终奖金+津贴补贴，绩效奖金0-30%基本工资", "source": "员工手册.txt + 常见问题.txt"},
    {"id": 20, "category": "跨文档关联", "question": "病假工资怎么算？不同工龄有什么区别？", "expected": "按工龄60%-100%发放", "source": "常见问题.txt"},

    # 四、复杂推理测试（3题）
    {"id": 21, "category": "复杂推理", "question": "一个入职3年的员工，累计病假1个月，能拿到多少病假工资？", "expected": "工龄2-4年按基本工资70%发放", "source": "常见问题.txt"},
    {"id": 22, "category": "复杂推理", "question": "如果我绩效考核连续两个月是D级会怎样？", "expected": "进入绩效改进期(PIP)，1-3个月改进期，仍不达标可调岗或解除合同", "source": "常见问题.txt"},
    {"id": 23, "category": "复杂推理", "question": "ZDAP企业版的简单查询响应时间要求是多少？", "expected": "<1秒", "source": "产品手册.txt"},

    # 五、表格数据测试（3题）
    {"id": 24, "category": "表格数据", "question": "P4级工程师的年薪范围是多少？", "expected": "25-35万元", "source": "组织架构说明.txt"},
    {"id": 25, "category": "表格数据", "question": "M3级经理对应的职称是什么？", "expected": "高级经理", "source": "组织架构说明.txt"},
    {"id": 26, "category": "表格数据", "question": "数据工程组有多少人？负责人是谁？", "expected": "80人，负责人王工", "source": "组织架构说明.txt"},

    # 六、否定性测试（3题）
    {"id": 27, "category": "否定性测试", "question": "公司有员工宿舍吗？", "expected": "没有员工宿舍，但为外地新员工提供15天免费过渡住宿", "source": "常见问题.txt"},
    {"id": 28, "category": "否定性测试", "question": "公司的股票代码是什么？", "expected": "文档中未提及", "source": "无"},
    {"id": 29, "category": "否定性测试", "question": "公司有食堂吗？", "expected": "没有食堂，但提供早餐和午餐", "source": "常见问题.txt"},

    # 七、关键词检索测试（3题）
    {"id": 30, "category": "关键词检索", "question": "五险一金缴纳比例是多少？", "expected": "养老保险个人8%公司16%，医疗保险个人2%公司10%等", "source": "常见问题.txt"},
    {"id": 31, "category": "关键词检索", "question": "Kong Gateway在系统架构中的作用是什么？", "expected": "API网关层，JWT认证、限流熔断", "source": "产品手册.txt"},
    {"id": 32, "category": "关键词检索", "question": "ClickHouse用于什么用途？", "expected": "分析引擎", "source": "产品手册.txt"},

    # 八、长文档/分块测试（2题）
    {"id": 33, "category": "长文档测试", "question": "三峡工程2024年发电量是多少？", "expected": "需从三峡公报PDF中检索", "source": "三峡公报_*.pdf"},
    {"id": 34, "category": "长文档测试", "question": "三峡水库的水位调节范围是多少？", "expected": "需从三峡公报PDF中检索", "source": "三峡公报_*.pdf"},

    # 九、学术论文测试（2题）
    {"id": 35, "category": "学术论文", "question": "这篇论文的主要贡献是什么？", "expected": "需从论文PDF中提取", "source": "2604.09205v1.pdf"},
    {"id": 36, "category": "学术论文", "question": "论文使用了什么方法或模型？", "expected": "需从论文PDF中提取", "source": "2604.09205v1.pdf"},

    # 十、边缘案例测试（4题）
    {"id": 37, "category": "边缘案例", "question": "如果我要报销5000元以内的费用，需要谁审批？", "expected": "主管审批，备案即可", "source": "组织架构说明.txt"},
    {"id": 38, "category": "边缘案例", "question": "公司的核心工作时间是什么时候？", "expected": "10:00-16:00（必须到岗）", "source": "常见问题.txt"},
    {"id": 39, "category": "边缘案例", "question": "ZDAP支持哪些图表类型？", "expected": "柱状图、折线图、饼图、散点图、热力图、地图、雷达图、漏斗图", "source": "产品手册.txt"},
    {"id": 40, "category": "边缘案例", "question": "技术支持热线的服务时间是怎样的？", "expected": "工作日9:00-21:00，周末及节假日10:00-18:00", "source": "产品手册.txt"},
]


def call_rag_api(question: str, kb_name: str = "public", top_k: int = 5) -> dict:
    """
    调用 RAG API 进行问答

    Args:
        question: 问题内容
        kb_name: 知识库名称
        top_k: 返回结果数量

    Returns:
        包含答案和检索上下文的字典
    """
    import requests

    url = "http://localhost:5001/rag"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer mock-token-admin"
    }
    data = {
        "message": question  # 使用 message 字段
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=120)
        response.raise_for_status()
        result = response.json()
        return {
            "answer": result.get("answer"),
            "sources": result.get("sources", []),
            "contexts": []  # /rag 接口不返回 contexts，但有 sources
        }
    except requests.exceptions.RequestException as e:
        return {"error": str(e), "answer": None, "sources": [], "contexts": []}


def evaluate_answer(actual: str, expected: str) -> dict:
    """
    评估答案准确性

    Args:
        actual: 实际答案
        expected: 预期答案

    Returns:
        评估结果字典
    """
    if not actual:
        return {"score": 0, "grade": "不合格", "reason": "未获取到答案", "matched_keywords": []}

    actual_lower = actual.lower()
    expected_lower = expected.lower()

    # 使用 jieba 分词（中文友好）
    try:
        import jieba
        expected_keywords = set(jieba.cut(expected_lower))
        actual_keywords = set(jieba.cut(actual_lower))
    except ImportError:
        # jieba 未安装时的降级方案
        expected_keywords = set(expected_lower.replace("，", " ").replace("、", " ").replace("。", " ").split())
        actual_keywords = set(actual_lower.replace("，", " ").replace("、", " ").replace("。", " ").split())

    # 过滤停用词和短词
    stop_words = {"的", "是", "有", "在", "和", "与", "或", "等", "了", "到", "为", "按", "以", "可以", "需要", "应该"}
    expected_keywords = {w for w in expected_keywords if len(w) >= 2 and w not in stop_words}
    actual_keywords = {w for w in actual_keywords if len(w) >= 2 and w not in stop_words}

    matched_keywords = expected_keywords & actual_keywords

    if len(expected_keywords) == 0:
        keyword_score = 50
    else:
        keyword_score = int(len(matched_keywords) / len(expected_keywords) * 100)

    # 完全匹配加分
    if expected_lower in actual_lower:
        keyword_score = min(100, keyword_score + 20)

    # 评分等级
    if keyword_score >= 80:
        grade = "优秀"
    elif keyword_score >= 60:
        grade = "良好"
    elif keyword_score >= 40:
        grade = "合格"
    else:
        grade = "不合格"

    return {
        "score": keyword_score,
        "grade": grade,
        "matched_keywords": list(matched_keywords),
        "reason": f"关键词匹配度 {keyword_score}%"
    }


def run_tests():
    """执行所有测试"""
    print("=" * 80)
    print("RAG 系统测试开始")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试问题数量: {len(TEST_QUESTIONS)}")
    print("=" * 80)
    print()

    results = []

    for i, test in enumerate(TEST_QUESTIONS):
        print(f"[{i+1}/{len(TEST_QUESTIONS)}] 测试类别: {test['category']}")
        print(f"问题: {test['question']}")

        # 调用 API
        start_time = time.time()
        response = call_rag_api(test['question'])
        elapsed_time = time.time() - start_time

        # 提取答案和上下文
        answer = response.get("answer", "")
        sources = response.get("sources", [])

        # 评估答案
        evaluation = evaluate_answer(answer, test['expected'])

        result = {
            "id": test['id'],
            "category": test['category'],
            "question": test['question'],
            "expected": test['expected'],
            "expected_source": test['source'],
            "actual_answer": answer,
            "actual_sources": sources,
            "response_time": round(elapsed_time, 2),
            "evaluation": evaluation
        }
        results.append(result)

        # 打印结果
        print(f"预期答案: {test['expected']}")
        # 过滤 emoji 和特殊字符，避免编码问题
        import re
        def sanitize_text(text):
            if not text:
                return "无答案"
            # 移除 emoji 和特殊 Unicode 字符
            text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
            return text[:200] + "..." if len(text) > 200 else text
        answer_display = sanitize_text(answer)
        print(f"实际答案: {answer_display}")
        print(f"检索来源: {sources[:3]}..." if len(sources) > 3 else f"检索来源: {sources}")
        print(f"评分: {evaluation['score']} ({evaluation['grade']}) - {evaluation['reason']}")
        print(f"响应时间: {elapsed_time:.2f}s")
        print("-" * 80)

    return results


def generate_report(results: list) -> str:
    """生成测试报告"""
    # 统计各类别得分
    category_stats = {}
    for r in results:
        cat = r['category']
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "scores": [], "times": []}
        category_stats[cat]['total'] += 1
        category_stats[cat]['scores'].append(r['evaluation']['score'])
        category_stats[cat]['times'].append(r['response_time'])

    # 计算总体统计
    all_scores = [r['evaluation']['score'] for r in results]
    all_times = [r['response_time'] for r in results]

    # 生成报告
    report = []
    report.append("# RAG 系统测试报告")
    report.append("")
    report.append(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"**测试问题数量**: {len(results)}")
    report.append("")

    # 总体统计
    report.append("## 一、总体统计")
    report.append("")
    report.append(f"- **平均得分**: {sum(all_scores)/len(all_scores):.1f} 分")
    report.append(f"- **最高得分**: {max(all_scores)} 分")
    report.append(f"- **最低得分**: {min(all_scores)} 分")
    report.append(f"- **平均响应时间**: {sum(all_times)/len(all_times):.2f} 秒")
    report.append(f"- **优秀率 (≥80分)**: {len([s for s in all_scores if s >= 80])/len(all_scores)*100:.1f}%")
    report.append(f"- **合格率 (≥40分)**: {len([s for s in all_scores if s >= 40])/len(all_scores)*100:.1f}%")
    report.append("")

    # 分类统计
    report.append("## 二、分类统计")
    report.append("")
    report.append("| 测试类别 | 题数 | 平均分 | 最高分 | 最低分 | 平均响应时间 |")
    report.append("|----------|------|--------|--------|--------|--------------|")
    for cat, stats in category_stats.items():
        avg_score = sum(stats['scores']) / len(stats['scores'])
        avg_time = sum(stats['times']) / len(stats['times'])
        report.append(f"| {cat} | {stats['total']} | {avg_score:.1f} | {max(stats['scores'])} | {min(stats['scores'])} | {avg_time:.2f}s |")
    report.append("")

    # 详细结果
    report.append("## 三、详细测试结果")
    report.append("")

    for r in results:
        report.append(f"### Q{r['id']}: {r['question']}")
        report.append("")
        report.append(f"- **测试类别**: {r['category']}")
        report.append(f"- **预期答案**: {r['expected']}")
        report.append(f"- **预期来源**: {r['expected_source']}")
        report.append(f"- **实际答案**: {r['actual_answer']}")
        # 处理 sources 格式（可能是 dict 列表或 str 列表）
        sources = r['actual_sources']
        if sources and isinstance(sources[0], dict):
            sources_str = ', '.join([s.get('source', str(s)) for s in sources[:5]])
        else:
            sources_str = ', '.join([str(s) for s in sources[:5]]) if sources else '无'
        report.append(f"- **检索来源**: {sources_str}")
        report.append(f"- **评分**: {r['evaluation']['score']} ({r['evaluation']['grade']})")
        report.append(f"- **响应时间**: {r['response_time']}s")
        report.append("")

    # 问题与建议
    report.append("## 四、问题分析")
    report.append("")

    # 低分问题
    low_score_questions = [r for r in results if r['evaluation']['score'] < 40]
    if low_score_questions:
        report.append("### 低分问题 (< 40分)")
        report.append("")
        for r in low_score_questions:
            report.append(f"- Q{r['id']}: {r['question']} (得分: {r['evaluation']['score']})")
        report.append("")

    return "\n".join(report)


def main():
    """主函数"""
    # Windows 控制台编码处理
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    # 执行测试
    results = run_tests()

    # 生成报告
    report = generate_report(results)

    # 保存报告
    report_file = "rag_test_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    print("\n" + "=" * 80)
    print("测试完成！")
    print(f"报告已保存到: {report_file}")
    print("=" * 80)

    # 保存详细结果 JSON
    json_file = "rag_test_results.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"详细结果已保存到: {json_file}")


if __name__ == "__main__":
    main()

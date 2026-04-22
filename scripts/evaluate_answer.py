#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 答案层评测脚本

评测指标：
- LLM Score: 使用LLM对答案质量打分 (0-1)
- ROUGE-L: 最长公共子序列相似度
- Semantic Similarity: 语义相似度（使用embedding）

用法:
    python scripts/evaluate_answer.py --eval_dataset data/eval_dataset.json
    python scripts/evaluate_answer.py --topk 5 --output results/answer_results.json
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AnswerEvaluator:
    """答案层评测器"""

    def __init__(self, engine=None):
        """
        初始化评测器

        Args:
            engine: RAG引擎实例，如果为None则自动创建
        """
        self.engine = engine
        self._llm_client = None
        self._embedding_model = None

    def _get_engine(self):
        """延迟加载引擎"""
        if self.engine is None:
            from core.engine import get_engine
            self.engine = get_engine()
        return self.engine

    def _get_llm_client(self):
        """延迟加载LLM客户端"""
        if self._llm_client is None:
            try:
                from openai import OpenAI
                from config import API_KEY, BASE_URL, MODEL
                self._llm_client = OpenAI(
                    api_key=API_KEY,
                    base_url=BASE_URL
                )
                self._llm_model = MODEL
            except Exception as e:
                logger.warning(f"LLM客户端初始化失败: {e}")
                self._llm_client = None
        return self._llm_client

    def _get_embedding_model(self):
        """延迟加载embedding模型"""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                from config import EMBEDDING_MODEL_PATH
                self._embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
            except Exception as e:
                logger.warning(f"Embedding模型初始化失败: {e}")
                self._embedding_model = None
        return self._embedding_model

    def rouge_l(self, generated: str, reference: str) -> float:
        """
        计算 ROUGE-L 分数

        Args:
            generated: 生成的答案
            reference: 参考答案

        Returns:
            ROUGE-L F1 分数 (0-1)
        """
        if not generated or not reference:
            return 0.0

        # 简单分词（按字符）
        gen_tokens = list(generated)
        ref_tokens = list(reference)

        # 计算最长公共子序列长度
        m, n = len(gen_tokens), len(ref_tokens)
        if m == 0 or n == 0:
            return 0.0

        # DP计算LCS
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if gen_tokens[i - 1] == ref_tokens[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        lcs_len = dp[m][n]

        # 计算Precision和Recall
        precision = lcs_len / m if m > 0 else 0.0
        recall = lcs_len / n if n > 0 else 0.0

        # F1分数
        if precision + recall == 0:
            return 0.0
        f1 = 2 * precision * recall / (precision + recall)

        return f1

    def semantic_similarity(self, generated: str, reference: str) -> float:
        """
        计算语义相似度

        Args:
            generated: 生成的答案
            reference: 参考答案

        Returns:
            语义相似度 (0-1)
        """
        model = self._get_embedding_model()
        if model is None:
            return 0.0

        try:
            embeddings = model.encode([generated, reference])
            # 余弦相似度
            similarity = np.dot(embeddings[0], embeddings[1]) / (
                np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
            )
            return float(max(0, min(1, similarity)))  # 确保在0-1范围内
        except Exception as e:
            logger.warning(f"计算语义相似度失败: {e}")
            return 0.0

    def llm_score(self, query: str, generated: str, reference: str) -> float:
        """
        使用LLM对答案质量打分

        Args:
            query: 用户问题
            generated: 生成的答案
            reference: 参考答案

        Returns:
            LLM评分 (0-1)
        """
        client = self._get_llm_client()
        if client is None:
            logger.warning("LLM客户端不可用，跳过LLM评分")
            return 0.0

        prompt = f"""请作为专业评测员，对RAG系统的回答质量进行评分。

【用户问题】
{query}

【参考答案】
{reference}

【系统回答】
{generated}

【评分标准】
请从以下维度评分（每项0-10分）：
1. 准确性：回答是否与参考答案的核心信息一致
2. 完整性：回答是否覆盖了参考答案的关键要点
3. 相关性：回答是否直接回答了用户问题
4. 流畅性：回答是否通顺、易于理解

请以JSON格式返回评分：
{{"accuracy": X, "completeness": X, "relevance": X, "fluency": X, "overall": X}}

只返回JSON，不要其他内容。"""

        try:
            response = client.chat.completions.create(
                model=self._llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200
            )

            result_text = response.choices[0].message.content.strip()

            # 尝试解析JSON
            import re
            json_match = re.search(r'\{[^}]+\}', result_text)
            if json_match:
                scores = json.loads(json_match.group())
                overall = scores.get('overall', 0)
                return min(1.0, max(0.0, overall / 10.0))
            else:
                # 尝试从文本中提取数字
                numbers = re.findall(r'\d+', result_text)
                if numbers:
                    return min(1.0, max(0.0, int(numbers[-1]) / 10.0))
                return 0.5

        except Exception as e:
            logger.warning(f"LLM评分失败: {e}")
            return 0.0

    def generate_answer(self, query: str, top_k: int = 5, collections: list = None) -> str:
        """
        使用RAG引擎生成答案

        Args:
            query: 用户问题
            top_k: 检索数量
            collections: 目标向量库列表

        Returns:
            生成的答案
        """
        engine = self._get_engine()

        try:
            # 先检索
            results = engine.search_knowledge(
                query=query,
                top_k=top_k,
                collections=collections
            )

            # 提取文档内容
            if isinstance(results, dict):
                documents = results.get('documents', [])
                if documents and isinstance(documents[0], list):
                    documents = documents[0]
            else:
                documents = []

            if not documents:
                return "抱歉，未找到相关信息。"

            # 简单拼接作为答案（实际应该用LLM生成）
            # 这里为了评测，我们用检索到的内容拼接
            context = "\n\n".join(documents[:3])

            # 使用LLM生成答案
            client = self._get_llm_client()
            if client:
                prompt = f"""基于以下检索到的信息回答用户问题。请简洁准确地回答。

【用户问题】
{query}

【检索到的信息】
{context}

请直接回答问题，不要重复问题本身："""

                response = client.chat.completions.create(
                    model=self._llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=500
                )
                return response.choices[0].message.content.strip()
            else:
                # 没有LLM时，直接返回最相关的文档片段
                return documents[0] if documents else "无法生成答案"

        except Exception as e:
            logger.error(f"生成答案失败: {e}")
            return f"生成答案时出错: {str(e)}"

    def evaluate_query(
        self,
        query: str,
        reference_answer: str,
        top_k: int = 5,
        collections: list = None,
        use_llm: bool = True
    ) -> dict:
        """
        评估单个查询的答案质量

        Args:
            query: 用户问题
            reference_answer: 参考答案
            top_k: 检索数量
            collections: 目标向量库列表
            use_llm: 是否使用LLM评分

        Returns:
            评测结果字典
        """
        # 生成答案
        generated_answer = self.generate_answer(query, top_k=top_k, collections=collections)

        # 计算各项指标
        metrics = {
            'rouge_l': self.rouge_l(generated_answer, reference_answer),
            'semantic_similarity': self.semantic_similarity(generated_answer, reference_answer),
            'generated_answer': generated_answer[:500],  # 截断保存
            'reference_answer': reference_answer[:500]
        }

        # LLM评分（可选，因为较慢）
        if use_llm:
            metrics['llm_score'] = self.llm_score(query, generated_answer, reference_answer)

        return metrics

    def evaluate_dataset(
        self,
        eval_dataset_path: str,
        top_k: int = 5,
        collections: list = None,
        use_llm: bool = True,
        sample_size: int = None
    ) -> dict:
        """
        评估整个数据集

        Args:
            eval_dataset_path: 评测数据集路径
            top_k: 检索数量
            collections: 目标向量库列表
            use_llm: 是否使用LLM评分
            sample_size: 采样数量（用于快速测试）

        Returns:
            汇总评测结果
        """
        # 加载数据集
        with open(eval_dataset_path, 'r', encoding='utf-8') as f:
            dataset = json.load(f)

        queries = dataset.get('queries', [])

        # 采样（如果指定）
        if sample_size and sample_size < len(queries):
            import random
            queries = random.sample(queries, sample_size)

        # 存储每个查询的结果
        all_metrics = {
            'rouge_l': [],
            'semantic_similarity': [],
            'llm_score': []
        }

        # 按查询类型分组
        by_type = {}
        # 按难度分组
        by_difficulty = {}

        logger.info(f"开始答案层评测，共 {len(queries)} 条查询...")

        for i, q in enumerate(queries, 1):
            query_text = q['query']
            query_type = q.get('query_type', 'unknown')
            difficulty = q.get('difficulty', 'medium')
            reference_answer = q.get('reference_answer', '')

            if not reference_answer:
                logger.warning(f"查询 {q['id']} 没有参考答案，跳过")
                continue

            # 执行评测
            metrics = self.evaluate_query(
                query=query_text,
                reference_answer=reference_answer,
                top_k=top_k,
                collections=collections,
                use_llm=use_llm
            )

            # 收集结果
            all_metrics['rouge_l'].append(metrics['rouge_l'])
            all_metrics['semantic_similarity'].append(metrics['semantic_similarity'])
            if 'llm_score' in metrics:
                all_metrics['llm_score'].append(metrics['llm_score'])

            # 按类型分组
            if query_type not in by_type:
                by_type[query_type] = {k: [] for k in all_metrics}
            by_type[query_type]['rouge_l'].append(metrics['rouge_l'])
            by_type[query_type]['semantic_similarity'].append(metrics['semantic_similarity'])
            if 'llm_score' in metrics:
                by_type[query_type]['llm_score'].append(metrics['llm_score'])

            # 按难度分组
            if difficulty not in by_difficulty:
                by_difficulty[difficulty] = {k: [] for k in all_metrics}
            by_difficulty[difficulty]['rouge_l'].append(metrics['rouge_l'])
            by_difficulty[difficulty]['semantic_similarity'].append(metrics['semantic_similarity'])
            if 'llm_score' in metrics:
                by_difficulty[difficulty]['llm_score'].append(metrics['llm_score'])

            # 打印进度
            llm_str = f", LLM={metrics.get('llm_score', 0):.2f}" if 'llm_score' in metrics else ""
            logger.info(f"  [{i}/{len(queries)}] {q['id']}: ROUGE-L={metrics['rouge_l']:.2f}, SemSim={metrics['semantic_similarity']:.2f}{llm_str}")

        # 计算平均值
        results = {
            'overall': {
                key: np.mean(values) if values else 0.0
                for key, values in all_metrics.items()
            },
            'by_type': {
                qtype: {key: np.mean(vals) if vals else 0.0 for key, vals in metrics.items()}
                for qtype, metrics in by_type.items()
            },
            'by_difficulty': {
                diff: {key: np.mean(vals) if vals else 0.0 for key, vals in metrics.items()}
                for diff, metrics in by_difficulty.items()
            },
            'total_queries': len(queries),
            'evaluated_queries': len(all_metrics['rouge_l'])
        }

        return results

    def print_results(self, results: dict):
        """打印评测结果"""
        print("\n" + "=" * 60)
        print("           RAG 答案层评测结果")
        print("=" * 60)

        # 整体结果
        print("\n【整体指标】")
        overall = results.get('overall', {})
        print(f"  ROUGE-L:           {overall.get('rouge_l', 0):.4f}")
        print(f"  Semantic Sim:      {overall.get('semantic_similarity', 0):.4f}")
        if overall.get('llm_score'):
            print(f"  LLM Score:         {overall.get('llm_score', 0):.4f}")

        # 按查询类型
        print("\n【按查询类型】")
        by_type = results.get('by_type', {})
        for qtype, metrics in sorted(by_type.items()):
            print(f"  {qtype}:")
            print(f"    ROUGE-L: {metrics.get('rouge_l', 0):.4f}")
            print(f"    SemSim:  {metrics.get('semantic_similarity', 0):.4f}")

        # 按难度
        print("\n【按难度】")
        by_difficulty = results.get('by_difficulty', {})
        for diff, metrics in sorted(by_difficulty.items()):
            print(f"  {diff}:")
            print(f"    ROUGE-L: {metrics.get('rouge_l', 0):.4f}")
            print(f"    SemSim:  {metrics.get('semantic_similarity', 0):.4f}")

        # 统计信息
        print("\n【统计信息】")
        print(f"  总查询数: {results.get('total_queries', 0)}")
        print(f"  已评测数: {results.get('evaluated_queries', 0)}")

        print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description='RAG 答案层评测脚本')
    parser.add_argument(
        '--eval_dataset',
        type=str,
        default='data/eval_dataset.json',
        help='评测数据集路径'
    )
    parser.add_argument(
        '--topk',
        type=int,
        default=5,
        help='检索返回数量 (默认: 5)'
    )
    parser.add_argument(
        '--collections',
        type=str,
        nargs='+',
        default=None,
        help='目标向量库列表'
    )
    parser.add_argument(
        '--no_llm',
        action='store_true',
        help='跳过LLM评分（更快但指标较少）'
    )
    parser.add_argument(
        '--sample',
        type=int,
        default=None,
        help='采样数量（用于快速测试）'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='结果输出文件路径 (JSON格式)'
    )

    args = parser.parse_args()

    # 检查数据集文件
    eval_path = PROJECT_ROOT / args.eval_dataset
    if not eval_path.exists():
        logger.error(f"评测数据集不存在: {eval_path}")
        sys.exit(1)

    # 创建评测器
    logger.info("初始化答案层评测器...")
    evaluator = AnswerEvaluator()

    # 执行评测
    start_time = time.time()
    results = evaluator.evaluate_dataset(
        eval_dataset_path=str(eval_path),
        top_k=args.topk,
        collections=args.collections,
        use_llm=not args.no_llm,
        sample_size=args.sample
    )
    elapsed_time = time.time() - start_time

    # 打印结果
    evaluator.print_results(results)
    print(f"\n评测耗时: {elapsed_time:.2f} 秒")

    # 保存结果
    if args.output:
        output_path = PROJECT_ROOT / args.output
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"结果已保存到: {output_path}")


if __name__ == '__main__':
    main()

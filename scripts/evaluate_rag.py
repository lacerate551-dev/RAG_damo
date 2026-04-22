#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 检索层评测脚本

评测指标：
- Recall@k: 召回率 - 命中相关切片数 / 相关切片总数
- MRR: 平均倒数排名 - 1 / 第一命中的排名
- Hit Rate: 命中率 - 命中查询数 / 总查询数
- nDCG: 归一化折损累积增益 - 考虑位置的加权得分

用法:
    python scripts/evaluate_rag.py --topk 5 --embedding bge-base --rerank on
    python scripts/evaluate_rag.py --eval_dataset data/eval_dataset.json
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

from core.engine import get_engine, RAGEngine

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RetrievalEvaluator:
    """检索层评测器"""

    def __init__(self, engine: Optional[RAGEngine] = None):
        """
        初始化评测器

        Args:
            engine: RAG引擎实例，如果为None则自动创建
        """
        self.engine = engine or get_engine()

    def recall_at_k(self, retrieved_ids: list, relevant_ids: list, k: int) -> float:
        """
        计算 Recall@k

        Args:
            retrieved_ids: 检索返回的切片ID列表
            relevant_ids: 相关切片ID列表
            k: 截断位置

        Returns:
            Recall@k 值 (0-1)
        """
        if not relevant_ids:
            return 0.0

        retrieved_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)

        hits = len(retrieved_set & relevant_set)
        return hits / len(relevant_set)

    def mrr(self, retrieved_ids: list, relevant_ids: list) -> float:
        """
        计算 MRR (Mean Reciprocal Rank)

        Args:
            retrieved_ids: 检索返回的切片ID列表
            relevant_ids: 相关切片ID列表

        Returns:
            MRR 值 (0-1)
        """
        if not relevant_ids:
            return 0.0

        relevant_set = set(relevant_ids)

        for rank, rid in enumerate(retrieved_ids, start=1):
            if rid in relevant_set:
                return 1.0 / rank

        return 0.0

    def hit_rate(self, retrieved_ids: list, relevant_ids: list, k: int) -> float:
        """
        计算 Hit Rate@k

        Args:
            retrieved_ids: 检索返回的切片ID列表
            relevant_ids: 相关切片ID列表
            k: 截断位置

        Returns:
            Hit Rate 值 (0-1)
        """
        if not relevant_ids:
            return 0.0

        retrieved_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)

        return 1.0 if retrieved_set & relevant_set else 0.0

    def ndcg_at_k(self, retrieved_ids: list, relevant_ids: list, k: int) -> float:
        """
        计算 nDCG@k (Normalized Discounted Cumulative Gain)

        Args:
            retrieved_ids: 检索返回的切片ID列表
            relevant_ids: 相关切片ID列表
            k: 截断位置

        Returns:
            nDCG@k 值 (0-1)
        """
        if not relevant_ids:
            return 0.0

        relevant_set = set(relevant_ids)

        # 计算 DCG
        dcg = 0.0
        for i, rid in enumerate(retrieved_ids[:k], start=1):
            if rid in relevant_set:
                dcg += 1.0 / np.log2(i + 1)

        # 计算 IDCG (理想情况)
        idcg = 0.0
        for i in range(1, min(len(relevant_ids), k) + 1):
            idcg += 1.0 / np.log2(i + 1)

        return dcg / idcg if idcg > 0 else 0.0

    def retrieve(self, query: str, top_k: int = 5, collections: list = None) -> list:
        """
        执行检索

        Args:
            query: 查询文本
            top_k: 返回数量
            collections: 目标向量库列表

        Returns:
            检索结果列表，每个元素包含 id, score, content 等
        """
        try:
            results = self.engine.search_knowledge(
                query=query,
                top_k=top_k,
                collections=collections
            )
            return results
        except Exception as e:
            logger.error(f"检索失败: {e}")
            return []

    def evaluate_query(
        self,
        query: str,
        relevant_ids: list,
        top_k: int = 5,
        collections: list = None
    ) -> dict:
        """
        评估单个查询

        Args:
            query: 查询文本
            relevant_ids: 相关切片ID列表
            top_k: 检索数量
            collections: 目标向量库列表

        Returns:
            评测结果字典
        """
        # 执行检索
        results = self.retrieve(query, top_k=top_k, collections=collections)

        # 提取检索到的ID
        # search_knowledge 返回格式: {'ids': [[...]], 'documents': [[...]], 'metadatas': [[...]], 'distances': [[...]]}
        # 注意：ids 是嵌套列表，需要展平
        if isinstance(results, dict):
            ids = results.get('ids', [])
            # 展平嵌套列表
            if ids and isinstance(ids[0], list):
                retrieved_ids = ids[0] if ids else []
            else:
                retrieved_ids = ids
        elif isinstance(results, list):
            retrieved_ids = [r.get('id', r.get('chunk_id', '')) if isinstance(r, dict) else str(r) for r in results]
        else:
            retrieved_ids = []

        # 计算各项指标
        metrics = {
            'recall@k': self.recall_at_k(retrieved_ids, relevant_ids, top_k),
            'mrr': self.mrr(retrieved_ids, relevant_ids),
            f'hit_rate@{top_k}': self.hit_rate(retrieved_ids, relevant_ids, top_k),
            f'ndcg@{top_k}': self.ndcg_at_k(retrieved_ids, relevant_ids, top_k),
            'retrieved_count': len(retrieved_ids),
            'relevant_count': len(relevant_ids)
        }

        return metrics

    def get_chunk_ids_by_doc(self, doc_name: str, collection: str = "public_kb") -> list:
        """
        获取指定文档的所有切片ID

        Args:
            doc_name: 文档名称
            collection: 向量库名称

        Returns:
            切片ID列表
        """
        try:
            # 使用向量库管理器查询
            from knowledge.manager import get_kb_manager
            manager = get_kb_manager()

            # 获取collection对象
            coll = manager.get_collection(collection)
            if not coll:
                logger.warning(f"向量库不存在: {collection}")
                return []

            # 查询指定source的所有切片
            results = coll.get(
                where={"source": doc_name},
                include=['metadatas']
            )

            return results.get('ids', [])
        except Exception as e:
            logger.warning(f"获取文档切片ID失败: {e}")
            return []

    def evaluate_dataset(
        self,
        eval_dataset_path: str,
        top_k: int = 5,
        collections: list = None
    ) -> dict:
        """
        评估整个数据集

        Args:
            eval_dataset_path: 评测数据集路径
            top_k: 检索数量
            collections: 目标向量库列表

        Returns:
            汇总评测结果
        """
        # 加载数据集
        with open(eval_dataset_path, 'r', encoding='utf-8') as f:
            dataset = json.load(f)

        queries = dataset.get('queries', [])

        # 存储每个查询的结果
        all_metrics = {
            'recall@k': [],
            'mrr': [],
            f'hit_rate@{top_k}': [],
            f'ndcg@{top_k}': []
        }

        # 按查询类型分组
        by_type = {}
        # 按难度分组
        by_difficulty = {}

        logger.info(f"开始评测，共 {len(queries)} 条查询...")

        for i, q in enumerate(queries, 1):
            query_text = q['query']
            query_type = q.get('query_type', 'unknown')
            difficulty = q.get('difficulty', 'medium')
            relevant_docs = q.get('relevant_docs', [])

            # 获取相关文档的切片ID作为 ground truth
            # 注意：这里简化处理，实际应该根据具体业务逻辑
            # 如果数据集有 relevant_chunks 字段则直接使用
            relevant_ids = q.get('relevant_chunks', [])

            # 如果没有 relevant_chunks，尝试根据 relevant_docs 获取
            if not relevant_ids and relevant_docs:
                for doc in relevant_docs:
                    ids = self.get_chunk_ids_by_doc(doc)
                    relevant_ids.extend(ids)

            if not relevant_ids:
                logger.warning(f"查询 {q['id']} 没有相关切片ID，跳过")
                continue

            # 执行评测
            metrics = self.evaluate_query(
                query=query_text,
                relevant_ids=relevant_ids,
                top_k=top_k,
                collections=collections
            )

            # 收集结果
            for key in all_metrics:
                if key in metrics:
                    all_metrics[key].append(metrics[key])

            # 按类型分组
            if query_type not in by_type:
                by_type[query_type] = {k: [] for k in all_metrics}
            for key in all_metrics:
                if key in metrics:
                    by_type[query_type][key].append(metrics[key])

            # 按难度分组
            if difficulty not in by_difficulty:
                by_difficulty[difficulty] = {k: [] for k in all_metrics}
            for key in all_metrics:
                if key in metrics:
                    by_difficulty[difficulty][key].append(metrics[key])

            logger.info(f"  [{i}/{len(queries)}] {q['id']}: Recall@{top_k}={metrics['recall@k']:.2f}, Hit={metrics[f'hit_rate@{top_k}']:.2f}")

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
            'evaluated_queries': len(all_metrics['recall@k'])
        }

        return results

    def print_results(self, results: dict):
        """打印评测结果"""
        print("\n" + "=" * 60)
        print("           RAG 检索层评测结果")
        print("=" * 60)

        # 整体结果
        print("\n【整体指标】")
        overall = results.get('overall', {})
        print(f"  Recall@k:    {overall.get('recall@k', 0):.4f}")
        print(f"  MRR:         {overall.get('mrr', 0):.4f}")
        print(f"  Hit Rate:    {overall.get('hit_rate@5', overall.get('hit_rate@k', 0)):.4f}")
        print(f"  nDCG:        {overall.get('ndcg@5', overall.get('ndcg@k', 0)):.4f}")

        # 按查询类型
        print("\n【按查询类型】")
        by_type = results.get('by_type', {})
        for qtype, metrics in sorted(by_type.items()):
            print(f"  {qtype}:")
            print(f"    Recall@k: {metrics.get('recall@k', 0):.4f}")
            print(f"    Hit Rate: {metrics.get('hit_rate@5', metrics.get('hit_rate@k', 0)):.4f}")

        # 按难度
        print("\n【按难度】")
        by_difficulty = results.get('by_difficulty', {})
        for diff, metrics in sorted(by_difficulty.items()):
            print(f"  {diff}:")
            print(f"    Recall@k: {metrics.get('recall@k', 0):.4f}")
            print(f"    Hit Rate: {metrics.get('hit_rate@5', metrics.get('hit_rate@k', 0)):.4f}")

        # 统计信息
        print("\n【统计信息】")
        print(f"  总查询数: {results.get('total_queries', 0)}")
        print(f"  已评测数: {results.get('evaluated_queries', 0)}")

        print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description='RAG 检索层评测脚本')
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
    logger.info("初始化评测器...")
    evaluator = RetrievalEvaluator()

    # 执行评测
    start_time = time.time()
    results = evaluator.evaluate_dataset(
        eval_dataset_path=str(eval_path),
        top_k=args.topk,
        collections=args.collections
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

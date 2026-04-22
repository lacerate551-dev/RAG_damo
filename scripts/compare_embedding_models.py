#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
向量模型对比评估脚本

比较不同嵌入模型的检索效果：
- bge-base-zh-v1.5 (当前使用)
- bge-large-zh-v1.5 (可选升级)
- bge-m3 (多语言支持)

用法:
    python scripts/compare_embedding_models.py --models bge-base-zh-v1.5 bge-large-zh-v1.5
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# 模型配置
MODEL_CONFIGS = {
    "bge-base-zh-v1.5": {
        "path": "BAAI/bge-base-zh-v1.5",
        "dimension": 768,
        "description": "中文基础模型，768维",
        "size_mb": 390
    },
    "bge-large-zh-v1.5": {
        "path": "BAAI/bge-large-zh-v1.5",
        "dimension": 1024,
        "description": "中文大模型，1024维，精度更高",
        "size_mb": 1300
    },
    "bge-m3": {
        "path": "BAAI/bge-m3",
        "dimension": 1024,
        "description": "多语言模型，支持100+语言",
        "size_mb": 2200
    }
}


def evaluate_model(model_name: str, eval_dataset_path: str, sample_size: int = None) -> dict:
    """
    评估单个模型

    Args:
        model_name: 模型名称
        eval_dataset_path: 评测数据集路径
        sample_size: 采样数量

    Returns:
        评测结果
    """
    from sentence_transformers import SentenceTransformer
    import numpy as np

    config = MODEL_CONFIGS.get(model_name)
    if not config:
        raise ValueError(f"未知模型: {model_name}")

    logger.info(f"加载模型: {model_name} ({config['description']})")

    # 加载模型
    start_time = time.time()
    model = SentenceTransformer(config["path"])
    load_time = time.time() - start_time
    logger.info(f"模型加载耗时: {load_time:.2f}秒")

    # 加载评测数据集
    with open(eval_dataset_path, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    queries = dataset.get('queries', [])
    if sample_size and sample_size < len(queries):
        import random
        queries = random.sample(queries, sample_size)

    # 简单评测：计算查询与相关文档的相似度
    results = {
        "model": model_name,
        "dimension": config["dimension"],
        "load_time": load_time,
        "queries_evaluated": len(queries),
        "avg_similarity": 0.0,
        "embedding_times": []
    }

    similarities = []
    for q in queries:
        query_text = q['query']
        reference_answer = q.get('reference_answer', '')

        # 计算查询和参考答案的相似度
        start = time.time()
        embeddings = model.encode([query_text, reference_answer])
        embed_time = time.time() - start
        results["embedding_times"].append(embed_time)

        similarity = np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        )
        similarities.append(similarity)

    results["avg_similarity"] = float(np.mean(similarities))
    results["avg_embed_time"] = float(np.mean(results["embedding_times"]))

    return results


def compare_models(models: list, eval_dataset_path: str, sample_size: int = None) -> dict:
    """
    对比多个模型

    Args:
        models: 模型列表
        eval_dataset_path: 评测数据集路径
        sample_size: 采样数量

    Returns:
        对比结果
    """
    results = {}

    for model_name in models:
        try:
            result = evaluate_model(model_name, eval_dataset_path, sample_size)
            results[model_name] = result

            logger.info(f"\n{'='*50}")
            logger.info(f"模型: {model_name}")
            logger.info(f"维度: {result['dimension']}")
            logger.info(f"加载时间: {result['load_time']:.2f}秒")
            logger.info(f"平均相似度: {result['avg_similarity']:.4f}")
            logger.info(f"平均编码时间: {result['avg_embed_time']*1000:.2f}ms")

        except Exception as e:
            logger.error(f"评估模型 {model_name} 失败: {e}")
            results[model_name] = {"error": str(e)}

    return results


def print_comparison(results: dict):
    """打印对比结果"""
    print("\n" + "=" * 70)
    print("                    向量模型对比结果")
    print("=" * 70)

    # 表头
    print(f"\n{'模型':<25} {'维度':<8} {'加载时间':<12} {'平均相似度':<12} {'编码时间':<12}")
    print("-" * 70)

    for model_name, result in results.items():
        if "error" in result:
            print(f"{model_name:<25} 错误: {result['error']}")
        else:
            print(f"{model_name:<25} {result['dimension']:<8} {result['load_time']:.2f}秒{'':<4} "
                  f"{result['avg_similarity']:.4f}{'':<4} {result['avg_embed_time']*1000:.2f}ms")

    # 推荐
    print("\n" + "-" * 70)
    print("推荐建议:")
    print("-" * 70)

    # 找出最佳模型
    valid_results = {k: v for k, v in results.items() if "error" not in v}
    if valid_results:
        best_sim = max(valid_results.items(), key=lambda x: x[1].get('avg_similarity', 0))
        fastest = min(valid_results.items(), key=lambda x: x[1].get('avg_embed_time', float('inf')))

        print(f"• 最高相似度: {best_sim[0]} ({best_sim[1]['avg_similarity']:.4f})")
        print(f"• 最快编码: {fastest[0]} ({fastest[1]['avg_embed_time']*1000:.2f}ms)")

        # 给出建议
        current = "bge-base-zh-v1.5"
        if current in valid_results:
            current_sim = valid_results[current]['avg_similarity']
            improvement = best_sim[1]['avg_similarity'] - current_sim
            if improvement > 0.05:
                print(f"\n💡 建议升级到 {best_sim[0]}，预期相似度提升: {improvement:.4f}")
            else:
                print(f"\n✓ 当前模型 {current} 表现良好，升级收益有限")


def main():
    parser = argparse.ArgumentParser(description='向量模型对比评估')
    parser.add_argument(
        '--models',
        nargs='+',
        default=['bge-base-zh-v1.5'],
        choices=list(MODEL_CONFIGS.keys()),
        help='要评估的模型列表'
    )
    parser.add_argument(
        '--eval_dataset',
        type=str,
        default='data/eval_dataset.json',
        help='评测数据集路径'
    )
    parser.add_argument(
        '--sample',
        type=int,
        default=10,
        help='采样数量（快速测试）'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='结果输出路径'
    )

    args = parser.parse_args()

    eval_path = PROJECT_ROOT / args.eval_dataset
    if not eval_path.exists():
        logger.error(f"评测数据集不存在: {eval_path}")
        sys.exit(1)

    # 运行对比
    results = compare_models(args.models, str(eval_path), args.sample)

    # 打印结果
    print_comparison(results)

    # 保存结果
    if args.output:
        output_path = PROJECT_ROOT / args.output
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"结果已保存到: {output_path}")


if __name__ == '__main__':
    main()

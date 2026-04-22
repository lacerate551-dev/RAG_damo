"""
文档版本自动清理任务

定期清理 superseded 状态的旧版本，控制存储成本。

使用方式:
    from knowledge.cleanup import cleanup_superseded_versions

    # 清理超过 7 天的 superseded 版本
    cleaned = cleanup_superseded_versions(days_to_keep=7)
"""

import logging
from datetime import datetime, timedelta
from typing import List

logger = logging.getLogger(__name__)


def cleanup_superseded_versions(days_to_keep: int = 7) -> int:
    """
    清理超过指定天数的 superseded 版本

    Args:
        days_to_keep: 保留天数，默认7天

    Returns:
        清理的 chunk 数量
    """
    from knowledge.manager import get_kb_manager

    kb_manager = get_kb_manager()
    cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()

    logger.info(f"开始清理 superseded 版本（保留 {days_to_keep} 天内的）")

    # 获取所有向量库
    try:
        kb_names = kb_manager.list_collections()
    except Exception as e:
        logger.error(f"获取向量库列表失败: {e}")
        return 0

    total_cleaned = 0

    for kb_name in kb_names:
        try:
            collection = kb_manager.get_collection(kb_name)
            if not collection:
                continue

            # 查询超过保留期的 superseded chunks
            # 注意：ChromaDB 的 where 过滤可能不支持 $lt 操作符
            # 所以我们先获取所有 superseded chunks，然后在 Python 中过滤
            result = collection.get(
                where={"status": "superseded"}
            )

            if not result['ids']:
                continue

            # 在 Python 中过滤超过保留期的 chunks
            ids_to_delete = []
            for i, meta in enumerate(result['metadatas']):
                superseded_time = meta.get('superseded_time', '')
                if superseded_time and superseded_time < cutoff_date:
                    ids_to_delete.append(result['ids'][i])

            if ids_to_delete:
                # 删除这些 chunks
                collection.delete(ids=ids_to_delete)
                total_cleaned += len(ids_to_delete)
                logger.info(f"清理 {kb_name}: {len(ids_to_delete)} chunks")

                # 重建 BM25 索引
                kb_manager.rebuild_bm25_index(kb_name)

        except Exception as e:
            logger.error(f"清理 {kb_name} 失败: {e}")
            continue

    logger.info(f"清理完成，共删除 {total_cleaned} 个 superseded chunks")
    return total_cleaned


def cleanup_deprecated_versions(days_to_keep: int = 30) -> int:
    """
    清理超过指定天数的 deprecated 版本

    Args:
        days_to_keep: 保留天数，默认30天

    Returns:
        清理的 chunk 数量
    """
    from knowledge.manager import get_kb_manager

    kb_manager = get_kb_manager()
    cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()

    logger.info(f"开始清理 deprecated 版本（保留 {days_to_keep} 天内的）")

    try:
        kb_names = kb_manager.list_collections()
    except Exception as e:
        logger.error(f"获取向量库列表失败: {e}")
        return 0

    total_cleaned = 0

    for kb_name in kb_names:
        try:
            collection = kb_manager.get_collection(kb_name)
            if not collection:
                continue

            # 获取所有 deprecated chunks
            result = collection.get(
                where={"status": "deprecated"}
            )

            if not result['ids']:
                continue

            # 在 Python 中过滤超过保留期的 chunks
            ids_to_delete = []
            for i, meta in enumerate(result['metadatas']):
                deprecated_date = meta.get('deprecated_date', '')
                if deprecated_date and deprecated_date < cutoff_date:
                    ids_to_delete.append(result['ids'][i])

            if ids_to_delete:
                # 删除这些 chunks
                collection.delete(ids=ids_to_delete)
                total_cleaned += len(ids_to_delete)
                logger.info(f"清理 {kb_name}: {len(ids_to_delete)} deprecated chunks")

                # 重建 BM25 索引
                kb_manager.rebuild_bm25_index(kb_name)

        except Exception as e:
            logger.error(f"清理 {kb_name} 失败: {e}")
            continue

    logger.info(f"清理完成，共删除 {total_cleaned} 个 deprecated chunks")
    return total_cleaned


def cleanup_all_old_versions(
    superseded_days: int = 7,
    deprecated_days: int = 30
) -> dict:
    """
    清理所有旧版本

    Args:
        superseded_days: superseded 版本保留天数
        deprecated_days: deprecated 版本保留天数

    Returns:
        清理统计信息
    """
    logger.info("开始清理所有旧版本")

    superseded_cleaned = cleanup_superseded_versions(superseded_days)
    deprecated_cleaned = cleanup_deprecated_versions(deprecated_days)

    result = {
        "superseded_cleaned": superseded_cleaned,
        "deprecated_cleaned": deprecated_cleaned,
        "total_cleaned": superseded_cleaned + deprecated_cleaned
    }

    logger.info(f"清理完成: {result}")
    return result


# ==================== 定时任务（可选） ====================

def start_cleanup_scheduler(
    superseded_days: int = 7,
    deprecated_days: int = 30,
    schedule_time: str = "03:00"
):
    """
    启动清理调度器（每天定时执行）

    Args:
        superseded_days: superseded 版本保留天数
        deprecated_days: deprecated 版本保留天数
        schedule_time: 执行时间（24小时制，如 "03:00"）

    注意：需要安装 schedule 库：pip install schedule
    """
    try:
        import schedule
        import threading
        import time
    except ImportError:
        logger.error("schedule 库未安装，无法启动定时任务。请运行: pip install schedule")
        return

    def job():
        """清理任务"""
        try:
            cleanup_all_old_versions(superseded_days, deprecated_days)
        except Exception as e:
            logger.error(f"定时清理任务失败: {e}")

    # 设置定时任务
    schedule.every().day.at(schedule_time).do(job)
    logger.info(f"清理调度器已启动，每天 {schedule_time} 执行")

    def run_scheduler():
        """调度器运行循环"""
        while True:
            schedule.run_pending()
            time.sleep(3600)  # 每小时检查一次

    # 在后台线程中运行
    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()
    logger.info("清理调度器后台线程已启动")


if __name__ == "__main__":
    # 测试清理功能
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if len(sys.argv) > 1:
        days = int(sys.argv[1])
    else:
        days = 7

    print(f"清理超过 {days} 天的 superseded 版本...")
    result = cleanup_all_old_versions(superseded_days=days)
    print(f"清理完成: {result}")

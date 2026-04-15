# -*- coding: utf-8 -*-
"""
图片服务 API

路由:
- GET /images/<image_id>     - 获取图片
- GET /images/<image_id>/info - 获取图片信息
- GET /images/list            - 列出所有图片
"""

import os
from flask import Blueprint, send_file, jsonify, current_app

image_bp = Blueprint('images', __name__)


def get_images_base_path():
    """获取图片存储路径"""
    try:
        from config import DOCUMENTS_PATH
        return os.path.join(DOCUMENTS_PATH, "images")
    except ImportError:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "documents", "images")


@image_bp.route('/images/<image_id>', methods=['GET'])
def get_image(image_id: str):
    """
    获取图片

    Args:
        image_id: 图片 ID（如 "制度汇编_p5_img1"）

    Returns:
        图片文件
    """
    # 安全检查：防止路径遍历攻击
    if '..' in image_id or '/' in image_id or '\\' in image_id:
        return jsonify({"error": "无效的图片 ID"}), 400

    images_path = get_images_base_path()

    # 支持多种格式
    supported_formats = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']

    for ext in supported_formats:
        image_path = os.path.join(images_path, f"{image_id}{ext}")
        if os.path.exists(image_path):
            try:
                mimetype = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.bmp': 'image/bmp',
                    '.webp': 'image/webp'
                }.get(ext, 'image/octet-stream')

                return send_file(image_path, mimetype=mimetype)
            except Exception as e:
                return jsonify({"error": f"读取图片失败: {str(e)}"}), 500

    return jsonify({"error": "图片不存在", "image_id": image_id}), 404


@image_bp.route('/images/<image_id>/info', methods=['GET'])
def get_image_info(image_id: str):
    """
    获取图片元信息

    Args:
        image_id: 图片 ID

    Returns:
        图片元信息（宽度、高度、格式等）
    """
    # 安全检查
    if '..' in image_id or '/' in image_id or '\\' in image_id:
        return jsonify({"error": "无效的图片 ID"}), 400

    images_path = get_images_base_path()
    supported_formats = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']

    for ext in supported_formats:
        image_path = os.path.join(images_path, f"{image_id}{ext}")
        if os.path.exists(image_path):
            try:
                # 使用 PIL 获取图片信息
                from PIL import Image

                with Image.open(image_path) as img:
                    return jsonify({
                        "image_id": image_id,
                        "width": img.width,
                        "height": img.height,
                        "format": img.format,
                        "mode": img.mode,
                        "size_bytes": os.path.getsize(image_path),
                        "url": f"/images/{image_id}"
                    })
            except ImportError:
                # PIL 未安装，返回基本信息
                return jsonify({
                    "image_id": image_id,
                    "size_bytes": os.path.getsize(image_path),
                    "url": f"/images/{image_id}"
                })
            except Exception as e:
                return jsonify({"error": f"读取图片信息失败: {str(e)}"}), 500

    return jsonify({"error": "图片不存在", "image_id": image_id}), 404


@image_bp.route('/images/list', methods=['GET'])
def list_images():
    """
    列出所有图片

    Query Parameters:
        limit: 最大返回数量（默认 50）
        offset: 偏移量（默认 0）

    Returns:
        图片列表
    """
    from flask import request

    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    images_path = get_images_base_path()

    if not os.path.exists(images_path):
        return jsonify({"images": [], "total": 0})

    supported_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    images = []

    try:
        for filename in os.listdir(images_path):
            ext = os.path.splitext(filename)[1].lower()
            if ext in supported_extensions:
                image_id = os.path.splitext(filename)[0]
                filepath = os.path.join(images_path, filename)
                images.append({
                    "image_id": image_id,
                    "url": f"/images/{image_id}",
                    "size_bytes": os.path.getsize(filepath)
                })

        # 排序
        images.sort(key=lambda x: x['image_id'])

        # 分页
        total = len(images)
        images = images[offset:offset + limit]

        return jsonify({
            "images": images,
            "total": total,
            "limit": limit,
            "offset": offset
        })

    except Exception as e:
        return jsonify({"error": f"列出图片失败: {str(e)}"}), 500


@image_bp.route('/images/stats', methods=['GET'])
def image_stats():
    """
    获取图片统计信息

    Returns:
        图片总数、总大小等统计信息
    """
    images_path = get_images_base_path()

    if not os.path.exists(images_path):
        return jsonify({
            "total_images": 0,
            "total_size_bytes": 0,
            "supported_formats": ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']
        })

    supported_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    total_count = 0
    total_size = 0
    format_counts = {}

    try:
        for filename in os.listdir(images_path):
            ext = os.path.splitext(filename)[1].lower()
            if ext in supported_extensions:
                total_count += 1
                filepath = os.path.join(images_path, filename)
                total_size += os.path.getsize(filepath)
                format_counts[ext] = format_counts.get(ext, 0) + 1

        return jsonify({
            "total_images": total_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "format_counts": format_counts,
            "supported_formats": list(supported_extensions)
        })

    except Exception as e:
        return jsonify({"error": f"获取统计信息失败: {str(e)}"}), 500

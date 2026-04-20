# -*- coding: utf-8 -*-
"""
PDF 图片提取模块

从 PDF 文档中提取图片，支持：
- 使用 PyMuPDF (fitz) 提取嵌入式图片
- 保存到指定目录
- 生成图片元数据供 RAG 系统使用
"""

import os
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict


@dataclass
class ImageInfo:
    """图片信息"""
    image_id: str              # 图片唯一 ID
    original_name: str         # 原始文件名
    storage_path: str          # 存储路径（相对路径）
    page: int                  # 所在页码
    width: int                 # 宽度
    height: int                # 高度
    format: str                # 格式 (png, jpg, etc.)
    size_bytes: int            # 文件大小
    caption: str = ""          # 图片说明（可选）
    bbox: Optional[List[float]] = None  # 边界框坐标


def extract_images_from_pdf(
    pdf_path: str,
    output_dir: str,
    min_width: int = 100,
    min_height: int = 100,
    max_width: int = 2000,   # 新增：最大宽度阈值（过滤跨页底纹）
    max_height: int = 2000,  # 新增：最大高度阈值
    max_images: int = 50
) -> List[ImageInfo]:
    """
    从 PDF 中提取图片

    Args:
        pdf_path: PDF 文件路径
        output_dir: 图片输出目录
        min_width: 最小宽度阈值（过滤小图标）
        min_height: 最小高度阈值
        max_width: 最大宽度阈值（过滤跨页底纹、背景横幅）
        max_height: 最大高度阈值
        max_images: 最大提取图片数量

    Returns:
        图片信息列表
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[警告] PyMuPDF 未安装，无法提取图片。请运行: pip install PyMuPDF")
        return []

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    # 创建输出目录
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    images = []
    image_count = 0

    try:
        doc = fitz.open(str(pdf_path))
        filename = pdf_path.stem

        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                if image_count >= max_images:
                    break

                try:
                    # 获取图片引用
                    xref = img_info[0]

                    # 提取图片
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue

                    image_bytes = base_image.get("image")
                    if not image_bytes:
                        continue

                    # 获取图片属性
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    image_ext = base_image.get("ext", "png")

                    # 过滤太小的图片（通常是图标）
                    if width < min_width or height < min_height:
                        continue

                    # 过滤太大的图片（跨页底纹、背景横幅）
                    if width > max_width or height > max_height:
                        continue

                    # 生成唯一 ID
                    image_id = f"{filename}_p{page_num + 1}_img{img_index + 1}"

                    # 确定文件扩展名
                    if image_ext in ["jpeg", "jpg"]:
                        ext = ".jpg"
                    elif image_ext == "png":
                        ext = ".png"
                    else:
                        ext = f".{image_ext}"

                    # 保存图片
                    image_filename = f"{image_id}{ext}"
                    image_path = output_dir / image_filename

                    with open(image_path, "wb") as f:
                        f.write(image_bytes)

                    # 记录图片信息
                    images.append(ImageInfo(
                        image_id=image_id,
                        original_name=filename,
                        storage_path=f"images/{image_filename}",
                        page=page_num + 1,
                        width=width,
                        height=height,
                        format=image_ext,
                        size_bytes=len(image_bytes),
                        caption=f"图片 {img_index + 1}"
                    ))

                    image_count += 1

                except Exception as e:
                    # 单个图片提取失败不影响其他图片
                    print(f"[警告] 提取图片失败 (页 {page_num + 1}, 图片 {img_index + 1}): {e}")
                    continue

            if image_count >= max_images:
                break

        doc.close()

    except Exception as e:
        print(f"[错误] PDF 图片提取失败: {e}")
        return []

    return images


def extract_images_batch(
    pdf_dir: str,
    output_dir: str,
    **kwargs
) -> Dict[str, List[ImageInfo]]:
    """
    批量提取 PDF 目录下所有文件的图片

    Args:
        pdf_dir: PDF 文件目录
        output_dir: 图片输出目录
        **kwargs: 传递给 extract_images_from_pdf 的参数

    Returns:
        {文件名: [ImageInfo, ...], ...}
    """
    pdf_dir = Path(pdf_dir)
    output_dir = Path(output_dir)

    results = {}

    for pdf_file in pdf_dir.glob("**/*.pdf"):
        try:
            # 为每个 PDF 创建子目录
            pdf_output_dir = output_dir / pdf_file.stem

            images = extract_images_from_pdf(
                str(pdf_file),
                str(pdf_output_dir),
                **kwargs
            )

            if images:
                results[pdf_file.name] = images
                print(f"[OK] {pdf_file.name}: 提取 {len(images)} 张图片")

        except Exception as e:
            print(f"[错误] {pdf_file.name}: {e}")

    return results


def get_images_base_path() -> str:
    """获取图片存储的基础路径"""
    try:
        from config import DOCUMENTS_PATH
        return os.path.join(DOCUMENTS_PATH, "images")
    except ImportError:
        return "documents/images"


# ==================== 集成到现有解析器 ====================

def filter_noise_images(
    images: List[Any],
    min_size: int = 100,
    max_size: int = 2000,
    enable_hash_dedup: bool = True,
    enable_content_check: bool = True,
    max_aspect_ratio: float = 10.0
) -> List[Any]:
    """
    三级噪音图片过滤管道

    Level 1: 尺寸过滤（过滤图标、跨页底纹）
    Level 2: Hash 去重（过滤重复图片）
    Level 3: 内容检测（过滤纯色背景、装饰横幅）

    Args:
        images: 图片列表（ImageInfo 或 dict）
        min_size: 最小尺寸阈值（像素），过滤图标
        max_size: 最大尺寸阈值（像素），过滤跨页底纹
        enable_hash_dedup: 启用 Hash 去重
        enable_content_check: 启用内容相关性检测
        max_aspect_ratio: 最大宽高比阈值，过滤装饰横幅

    Returns:
        过滤后的图片列表
    """
    if not images:
        return images

    filtered = []
    seen_hashes = set()

    for img in images:
        # 支持 dataclass 和 dict 两种格式
        if hasattr(img, 'width'):
            width, height = img.width, img.height
            storage_path = getattr(img, 'storage_path', '')
        else:
            width = img.get('width', 0)
            height = img.get('height', 0)
            storage_path = img.get('storage_path', '')

        # Level 1: 尺寸过滤
        if width < min_size or height < min_size:
            continue  # 图标、装饰线条
        if width > max_size or height > max_size:
            continue  # 跨页底纹、背景横幅

        # Level 2: Hash 去重
        if enable_hash_dedup and storage_path:
            try:
                img_hash = _compute_image_hash(storage_path)
                if img_hash in seen_hashes:
                    continue  # 重复图片
                seen_hashes.add(img_hash)
            except Exception:
                pass  # Hash 计算失败时跳过去重

        # Level 3: 内容相关性检测
        if enable_content_check:
            aspect_ratio = max(width, height) / max(min(width, height), 1)

            # 过滤极端宽高比（装饰横幅）
            if aspect_ratio > max_aspect_ratio:
                continue

            # 过滤纯色/渐变背景
            if storage_path and _is_solid_color_image(storage_path):
                continue

        filtered.append(img)

    return filtered


def _compute_image_hash(image_path: str) -> str:
    """
    计算图片文件的 Hash 值

    Args:
        image_path: 图片文件路径

    Returns:
        MD5 Hash 字符串
    """
    hash_md5 = hashlib.md5()
    with open(image_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def _is_solid_color_image(image_path: str, threshold: float = 0.95) -> bool:
    """
    检测图片是否为纯色/渐变背景（装饰性横幅）

    使用简单的颜色分布检测：
    - 如果图片 95% 以上像素属于同一颜色范围，判定为纯色背景

    Args:
        image_path: 图片文件路径
        threshold: 纯色判定阈值

    Returns:
        True 表示是纯色背景图片
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        # PIL/numpy 未安装，跳过检测
        return False

    try:
        img = Image.open(image_path)
        # 缩小图片加速处理
        img.thumbnail((100, 100))
        img_array = np.array(img)

        if img_array.ndim == 2:
            # 灰度图
            unique, counts = np.unique(img_array, return_counts=True)
        elif img_array.ndim == 3:
            # 彩色图，计算颜色直方图
            pixels = img_array.reshape(-1, img_array.shape[-1])
            # 量化颜色（减少颜色数量）
            quantized = (pixels // 32) * 32
            unique, counts = np.unique(quantized, axis=0, return_counts=True)
        else:
            return False

        # 如果主颜色占比超过阈值，判定为纯色背景
        max_color_ratio = max(counts) / sum(counts)
        return max_color_ratio > threshold

    except Exception:
        return False


def enrich_chunks_with_images(
    chunks: List[Any],
    images: List[ImageInfo],
    source_file: str
) -> List[Any]:
    """
    为分块添加图片信息

    根据页码将图片关联到对应的分块

    Args:
        chunks: 分块列表（ChunkMetadata 或 dict）
        images: 图片信息列表
        source_file: 源文件名

    Returns:
        添加了图片信息的分块列表
    """
    if not images:
        return chunks

    # 按页码分组图片
    page_to_images = {}
    for img in images:
        page = img.page
        if page not in page_to_images:
            page_to_images[page] = []
        page_to_images[page].append({
            "id": img.image_id,
            "caption": img.caption,
            "page": img.page,
            "width": img.width,
            "height": img.height
        })

    # 为每个分块添加图片信息
    for chunk in chunks:
        # 支持 dataclass 和 dict 两种格式
        if hasattr(chunk, 'page_start'):
            page_start = chunk.page_start
            page_end = getattr(chunk, 'page_end', page_start)
        else:
            page_start = chunk.get('page_start', 1)
            page_end = chunk.get('page_end', page_start)

        # 单页绑定：仅在切片不跨页时绑定图片
        chunk_images = []
        if page_start == page_end and page_start in page_to_images:
            chunk_images = page_to_images[page_start]

        # 应用噪音过滤
        chunk_images = filter_noise_images(chunk_images)

        # 限制每切片最多 3 张图片
        chunk_images = chunk_images[:3]

        # 添加到分块
        if chunk_images:
            if hasattr(chunk, '__dict__'):
                # dataclass
                chunk.images = chunk_images
            else:
                # dict
                chunk['images'] = chunk_images

    return chunks


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("PDF 图片提取模块测试")
    print("=" * 60)

    # 检查依赖
    try:
        import fitz
        print("[OK] PyMuPDF 已安装")
    except ImportError:
        print("[错误] PyMuPDF 未安装，请运行: pip install PyMuPDF")
        sys.exit(1)

    # 测试提取
    if len(sys.argv) >= 2:
        pdf_path = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) >= 3 else "documents/images"

        print(f"\n提取图片: {pdf_path}")
        print(f"输出目录: {output_dir}")

        images = extract_images_from_pdf(pdf_path, output_dir)

        print(f"\n提取结果: {len(images)} 张图片")
        for img in images[:10]:
            print(f"  - {img.image_id}: {img.width}x{img.height}, {img.size_bytes} bytes, 页码 {img.page}")
    else:
        print("\n用法: python image_extractor.py <pdf_path> [output_dir]")
        print("\n功能演示: 创建模拟图片信息")

        # 创建模拟数据演示功能
        mock_images = [
            ImageInfo(
                image_id="test_p1_img1",
                original_name="test.pdf",
                storage_path="images/test_p1_img1.png",
                page=1,
                width=800,
                height=600,
                format="png",
                size_bytes=45000,
                caption="流程图"
            ),
            ImageInfo(
                image_id="test_p3_img1",
                original_name="test.pdf",
                storage_path="images/test_p3_img1.jpg",
                page=3,
                width=1200,
                height=900,
                format="jpg",
                size_bytes=120000,
                caption="组织架构图"
            )
        ]

        print("\n模拟图片信息:")
        for img in mock_images:
            print(f"  ID: {img.image_id}")
            print(f"  页码: {img.page}")
            print(f"  尺寸: {img.width}x{img.height}")
            print(f"  格式: {img.format}")
            print(f"  大小: {img.size_bytes} bytes")
            print()

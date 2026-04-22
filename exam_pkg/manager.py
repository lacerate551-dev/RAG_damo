"""
出题与批题系统管理器

核心功能：
1. 题目生成（调用 generator.py）
2. 答案批阅（调用 grader.py）
3. 题库管理（保存/加载/搜索）

职责边界：
- RAG 服务负责：生成题目 + 批阅答案
- 后端服务负责：审核入库 + 状态管理

使用方式：
    from exam_pkg.manager import generate_questions_from_file, grade_answers
"""
import json
import os
import re
import requests
import uuid
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# 状态常量
EXAM_STATUS_DRAFT = "draft"
EXAM_STATUS_APPROVED = "approved"

# 导入新的生成器和批题器
from exam_pkg.generator import (
    QuestionGenerator,
    build_semantic_query,
    build_source_context,
    safe_parse_questions,
    validate_questions_schema
)
from exam_pkg.grader import (
    AnswerGrader,
    grade_answers as grade_answers_v2,
    grade_objective,
    grade_fill_blank
)

# MinerU 解析器（可选）
try:
    from parsers import parse_document, MINERU_AVAILABLE
    if MINERU_AVAILABLE:
        from parsers.mineru_parser import MinerUChunk
    PARSE_AVAILABLE = MINERU_AVAILABLE
except ImportError:
    PARSE_AVAILABLE = False

# 导入配置
try:
    from config import DIFY_API_URL, DIFY_QUESTION_API_KEY, DIFY_GRADE_API_KEY, ENABLE_DIFY_WORKFLOW
except ImportError:
    print("错误: 请创建config.py文件并配置API密钥")
    print("参考config.example.py")
    ENABLE_DIFY_WORKFLOW = False
    DIFY_API_URL = "https://api.dify.ai/v1"
    DIFY_QUESTION_API_KEY = ""
    DIFY_GRADE_API_KEY = ""

# 题库目录
QUESTION_BANK_DIR = "./题库"
DRAFT_DIR = "./题库/草稿"
REPORT_DIR = "./批阅报告"


# ==================== 新版出题接口 ====================

def generate_questions_from_file(
    file_path: str,
    collection: str,
    question_types: Dict[str, int],
    difficulty: int = 3,
    options: Dict = None,
    request_id: str = None
) -> Dict:
    """
    从文件生成题目（结构化出题）

    🔥 Structure-aware RAG 出题架构：
    - 按章节分组 → 提取知识点 → 按知识点出题 → 合并去重

    Args:
        file_path: 文件路径
        collection: 向量库名称
        question_types: 题型及数量 {"single_choice": 3, "fill_blank": 2, ...}
        difficulty: 难度 1-5
        options: 可选配置
            - max_source_chunks: 最大切片数（默认 30）
        request_id: 请求 ID（幂等性支持）

    Returns:
        {
            "success": True,
            "request_id": "...",
            "questions": [...],
            "total": 10,
            "source_chunks_used": 15
        }
    """
    options = options or {}

    # 1. 检索文件的所有切片
    chunks = retrieve_file_chunks(
        file_path=file_path,
        collection=collection,
        question_types=question_types,
        top_k=options.get('max_source_chunks', 30)
    )
    print(f"[DEBUG] generate_questions_from_file: chunks 数量 = {len(chunks)}")

    # 2. 结构化出题：按章节提取知识点 → 按知识点出题
    generator = QuestionGenerator()
    questions = generator.generate_questions_structured(
        chunks=chunks,
        document_name=file_path,
        question_types=question_types,
        difficulty=difficulty
    )

    return {
        "success": True,
        "request_id": request_id,
        "questions": questions,
        "total": len(questions),
        "source_chunks_used": len(chunks)
    }


def retrieve_file_chunks(
    file_path: str,
    collection,  # 支持字符串或列表
    question_types: Dict[str, int],
    top_k: int = None
) -> List[Dict]:
    """
    检索文件相关切片

    Args:
        file_path: 文件路径
        collection: 向量库名称（支持字符串或列表，列表时按优先级顺序检索）
        question_types: 题型及数量
        top_k: 最大切片数

    Returns:
        切片列表
    """
    # 动态计算 top_k：题型数量 × 3，上限 50
    if top_k is None:
        total_questions = sum(question_types.values())
        top_k = min(50, total_questions * 3)

    # 根据题型构建语义 query
    query = build_semantic_query(question_types)

    # 提取文件名（向量库存储的是文件名，不含路径前缀）
    filename = os.path.basename(file_path)

    # 统一处理为列表
    if isinstance(collection, str):
        collections = [collection]
    else:
        collections = list(collection) if collection else []

    if not collections:
        print("[ERROR] 未指定向量库")
        return []

    try:
        from core.engine import get_engine
        engine = get_engine()

        # 按优先级遍历 collections，找到文件即停止
        for coll in collections:
            # 尝试两种格式：文件名和完整路径
            for source_filter in [filename, file_path]:
                results = engine.search_knowledge(
                    query=query,
                    collections=[coll],
                    source_filter=source_filter,
                    top_k=top_k
                )

                # 检查是否有结果
                if results.get('documents') and results['documents'][0]:
                    print(f"[DEBUG] 在向量库 [{coll}] 中找到文件 [{filename}]")
                    break
            else:
                continue
            break  # 外层循环跳出

        chunks = []
        if results.get('documents') and results['documents'][0]:
            for i, (doc, meta, score) in enumerate(zip(
                results['documents'][0],
                results['metadatas'][0],
                results['distances'][0]
            )):
                chunks.append({
                    "chunk_id": results['ids'][0][i],
                    "content": doc,
                    "source": meta.get('source'),
                    "page": meta.get('page'),
                    "section": meta.get('section', ''),
                    "score": score
                })

        print(f"[DEBUG] retrieve_file_chunks: 检索到 {len(chunks)} 个切片")
        return chunks

    except Exception as e:
        print(f"[ERROR] 检索切片失败: {e}")
        return []


# ==================== 新版批题接口 ====================

def grade_answers(answers: List[Dict], request_id: str = None) -> Dict:
    """
    批阅答案入口函数

    🔥 改进：
    - 本地批阅选择题/判断题
    - 填空题模糊匹配
    - 主观题 LLM 评分
    - 并发 + 限流 + 顺序保持
    """
    return grade_answers_v2(answers, request_id)


# ==================== Dify 工作流接口（保留作为后续迁移参考） ====================
# 以下函数用于后续将出题/批卷功能迁移到 Dify 工作流时参考
# 当前使用本地 LLM 实现，这些函数暂未被 API 调用


def call_dify_workflow(api_key: str, inputs: dict) -> dict:
    """
    调用 Dify 工作流

    [保留作为后续迁移参考]
    后续如需迁移到 Dify 工作流，可参考此函数的实现方式。
    需要在 config.py 中配置 DIFY_API_URL 和对应的 API_KEY。
    """
    url = f"{DIFY_API_URL}/workflows/run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": inputs,
        "response_mode": "blocking",
        "user": "exam-system"
    }

    print(f"[DEBUG] 调用 Dify 工作流: {url}")
    print(f"[DEBUG] inputs: {json.dumps(inputs, ensure_ascii=False)[:500]}...")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        result = response.json()
        print(f"[DEBUG] Dify 响应成功")
        return result
    except requests.exceptions.Timeout:
        print(f"[ERROR] Dify API 请求超时")
        raise Exception("Dify API 请求超时，请检查网络连接或稍后重试")
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Dify API 连接失败: {e}")
        raise Exception(f"Dify API 连接失败，请检查网络或 API 地址: {DIFY_API_URL}")
    except requests.exceptions.HTTPError as e:
        error_detail = ""
        try:
            error_detail = response.json().get("message", str(e))
        except:
            error_detail = str(e)
        print(f"[ERROR] Dify API 返回错误: {error_detail}")
        raise Exception(f"Dify API 返回错误: {error_detail}")
    except Exception as e:
        print(f"[ERROR] Dify API 调用失败: {str(e)}")
        raise Exception(f"Dify API 调用失败: {str(e)}")


def parse_json_response(result: dict) -> dict:
    """解析Dify返回结果，处理markdown包裹的JSON"""
    outputs = result.get("data", {}).get("outputs", {})

    # 处理返回结果，提取JSON
    if "result" in outputs:
        raw_result = outputs["result"]
        if isinstance(raw_result, str):
            # 去掉markdown代码块标记
            raw_result = raw_result.strip()
            if raw_result.startswith("```json"):
                raw_result = raw_result[7:]
            if raw_result.startswith("```"):
                raw_result = raw_result[3:]
            if raw_result.endswith("```"):
                raw_result = raw_result[:-3]
            raw_result = raw_result.strip()
            try:
                outputs["result"] = json.loads(raw_result)
            except:
                pass

    return outputs


def generate_exam(topic: str, choice_count: int = 3, blank_count: int = 2,
                  short_answer_count: int = 2, difficulty: int = 3,
                  choice_score: int = 2, blank_score: int = 3,
                  created_by: str = None, name: str = None) -> dict:
    """
    生成试卷

    Args:
        topic: 主题
        choice_count: 选择题数量
        blank_count: 填空题数量
        short_answer_count: 简答题数量
        difficulty: 难度(1-5)
        choice_score: 选择题每题分值（默认2分）
        blank_score: 填空题每题分值（默认3分）
        created_by: 创建者用户名
        name: 试卷名称（可选，默认为 "{topic}试卷"）

    Returns:
        试卷JSON（包含exam_id和status）
    """
    print(f"正在生成试卷: {topic}")

    inputs = {
        "topic": topic,
        "choice_count": choice_count,
        "blank_count": blank_count,
        "short_answer_count": short_answer_count,
        "difficulty": difficulty
    }

    result = call_dify_workflow(DIFY_QUESTION_API_KEY, inputs)

    # 打印完整响应用于调试
    print(f"API响应: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}...")

    # 解析返回结果
    outputs = result.get("data", {}).get("outputs", {})
    questions_json = outputs.get("questions", "{}")

    # 如果是字符串，解析为JSON
    if isinstance(questions_json, str):
        # 去掉可能的markdown代码块
        questions_json = questions_json.strip()
        if questions_json.startswith("```json"):
            questions_json = questions_json[7:]
        if questions_json.startswith("```"):
            questions_json = questions_json[3:]
        if questions_json.endswith("```"):
            questions_json = questions_json[:-3]
        questions_json = questions_json.strip()
        questions_json = json.loads(questions_json)

    # 添加分值字段
    for q in questions_json.get("choice_questions", []):
        q["score"] = choice_score
    for q in questions_json.get("blank_questions", []):
        q["score"] = blank_score
    # 简答题分值由LLM生成，保留reference_answer中的total_score

    # 重新计算总分
    total_score = 0
    total_score += len(questions_json.get("choice_questions", [])) * choice_score
    total_score += len(questions_json.get("blank_questions", [])) * blank_score
    for q in questions_json.get("short_answer_questions", []):
        total_score += q.get("reference_answer", {}).get("total_score", 0)
    questions_json["total_score"] = total_score

    # 添加元数据
    questions_json["exam_id"] = str(uuid.uuid4())
    questions_json["status"] = EXAM_STATUS_DRAFT
    questions_json["created_at"] = datetime.now().isoformat()
    questions_json["created_by"] = created_by
    questions_json["topic"] = topic
    questions_json["name"] = name or f"{topic}试卷"
    questions_json["total_count"] = (
        len(questions_json.get("choice_questions", [])) +
        len(questions_json.get("blank_questions", [])) +
        len(questions_json.get("short_answer_questions", []))
    )

    return questions_json


def generate_exam_by_file(
    file_path: str,
    collection: str,
    user_id: str = None,
    user_role: str = None,
    user_department: str = None,
    choice_count: int = 3,
    blank_count: int = 2,
    short_answer_count: int = 2,
    difficulty: int = 3,
    choice_score: int = 2,
    blank_score: int = 3,
    created_by: str = None,
    name: str = None
) -> dict:
    """
    按文件生成题目（带溯源信息）

    Args:
        file_path: 来源文件路径（如 "public/产品手册.pdf"）
        collection: 向量库名称（如 "public_kb"）
        user_id: 用户ID（用于工作流认证）
        user_role: 用户角色（admin/manager/user）
        user_department: 用户部门
        choice_count: 选择题数量
        blank_count: 填空题数量
        short_answer_count: 简答题数量
        difficulty: 难度(1-5)
        choice_score: 选择题每题分值（默认2分）
        blank_score: 填空题每题分值（默认3分）
        created_by: 创建者用户名
        name: 试卷名称（可选，默认为 "{文件名}试卷"）

    Returns:
        {
            "source_file": {"path": "...", "collection": "..."},
            "choice_questions": [...],  # 每题含 source_file, source_snippet
            "blank_questions": [...],
            "short_answer_questions": [...],
            "total_count": 9,
            "total_score": 22
        }
    """
    print(f"正在按文件生成题目: {file_path}")

    # 提取文件名作为默认试卷名
    if name is None:
        filename = os.path.basename(file_path)
        name = os.path.splitext(filename)[0] + "试卷"

    inputs = {
        "file_path": file_path,
        "collection": collection,
        "user_id": user_id or "exam-system",
        "user_role": user_role or "admin",
        "user_department": user_department or "",
        "choice_count": choice_count,
        "blank_count": blank_count,
        "short_answer_count": short_answer_count,
        "difficulty": difficulty
    }

    result = call_dify_workflow(DIFY_QUESTION_API_KEY, inputs)

    # 打印完整响应用于调试
    print(f"API响应: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}...")

    # 解析返回结果
    outputs = result.get("data", {}).get("outputs", {})
    questions_json = outputs.get("questions", "{}")

    # 如果是字符串，解析为JSON
    if isinstance(questions_json, str):
        # 去掉可能的markdown代码块
        questions_json = questions_json.strip()
        if questions_json.startswith("```json"):
            questions_json = questions_json[7:]
        if questions_json.startswith("```"):
            questions_json = questions_json[3:]
        if questions_json.endswith("```"):
            questions_json = questions_json[:-3]
        questions_json = questions_json.strip()
        questions_json = json.loads(questions_json)

    # 添加分值字段和溯源信息
    for q in questions_json.get("choice_questions", []):
        q["score"] = choice_score
        q["source_file"] = file_path
        q["source_collection"] = collection
        # 如果 Dify 返回了 source_snippet，保留；否则设为空
        if "source_snippet" not in q:
            q["source_snippet"] = ""

    for q in questions_json.get("blank_questions", []):
        q["score"] = blank_score
        q["source_file"] = file_path
        q["source_collection"] = collection
        if "source_snippet" not in q:
            q["source_snippet"] = ""

    # 简答题分值由LLM生成，保留reference_answer中的total_score
    for q in questions_json.get("short_answer_questions", []):
        q["source_file"] = file_path
        q["source_collection"] = collection
        if "source_snippet" not in q:
            q["source_snippet"] = ""

    # 重新计算总分
    total_score = 0
    total_score += len(questions_json.get("choice_questions", [])) * choice_score
    total_score += len(questions_json.get("blank_questions", [])) * blank_score
    for q in questions_json.get("short_answer_questions", []):
        total_score += q.get("reference_answer", {}).get("total_score", 0)
    questions_json["total_score"] = total_score

    # 添加元数据
    questions_json["source_file"] = {
        "path": file_path,
        "collection": collection
    }
    questions_json["generated_at"] = datetime.now().isoformat()
    questions_json["created_by"] = created_by
    questions_json["name"] = name
    questions_json["total_count"] = (
        len(questions_json.get("choice_questions", [])) +
        len(questions_json.get("blank_questions", [])) +
        len(questions_json.get("short_answer_questions", []))
    )

    return questions_json


def generate_exam_by_file_with_chapters(
    file_path: str,
    keywords: List[str] = None,
    choice_count: int = 3,
    blank_count: int = 2,
    short_answer_count: int = 2,
    difficulty: int = 3,
    choice_score: int = 2,
    blank_score: int = 3,
    created_by: str = None,
    name: str = None,
    max_chapters: int = 5
) -> dict:
    """
    按文件生成题目（使用完整章节内容，无信息缺失）

    使用 MinerU 解析文档，获取完整章节内容作为出题素材。
    相比向量片段检索，可以获取完整的上下文，避免信息缺失。

    Args:
        file_path: 文档文件完整路径（支持 PDF/DOCX/PPTX）
        keywords: 关键词列表，用于定位相关章节（可选）
        choice_count: 选择题数量
        blank_count: 填空题数量
        short_answer_count: 简答题数量
        difficulty: 难度(1-5)
        choice_score: 选择题每题分值（默认2分）
        blank_score: 填空题每题分值（默认3分）
        created_by: 创建者用户名
        name: 试卷名称（可选）
        max_chapters: 最多使用多少个章节（默认5个）

    Returns:
        {
            "source_file": {"path": "...", "chapters": [...]},
            "choice_questions": [...],
            "blank_questions": [...],
            "short_answer_questions": [...],
            "total_count": 9,
            "total_score": 22
        }
    """
    if not PARSE_AVAILABLE:
        raise ImportError("MinerU 解析器不可用，请运行: pip install \"mineru[all]\"")

    print(f"正在解析文档文件: {file_path}")

    # 使用统一解析入口
    result = parse_document(
        file_path,
        output_base=".data/mineru_temp",
        images_output=".data/images",
        cleanup_after_image_move=True
    )
    chunks = result.get('chunks', [])

    print(f"解析完成: {len(chunks)} 个内容块")

    # 构建章节内容列表
    chapter_contents = []
    for chunk in chunks:
        content = chunk.content if hasattr(chunk, 'content') else str(chunk)
        if not content.strip():
            continue

        chapter_contents.append({
            "title": chunk.title if hasattr(chunk, 'title') else '',
            "content": content.strip(),
            "section_path": chunk.section_path if hasattr(chunk, 'section_path') else '',
            "page_range": f"{chunk.page_start}-{chunk.page_end}" if hasattr(chunk, 'page_start') else '',
            "source_file": chunk.source_file if hasattr(chunk, 'source_file') else os.path.basename(file_path)
        })

    # 如果有关键词，筛选相关章节
    if keywords:
        # 简单的关键词匹配筛选
        relevant = []
        for c in chapter_contents:
            content_lower = c['content'].lower()
            if any(kw.lower() in content_lower for kw in keywords):
                relevant.append(c)
        chapter_contents = relevant[:max_chapters]
        print(f"根据关键词筛选出 {len(chapter_contents)} 个相关章节")

    # 按内容长度排序，取前N个
    chapter_contents = sorted(chapter_contents, key=lambda x: len(x['content']), reverse=True)[:max_chapters]

    if not chapter_contents:
        raise ValueError("未找到有效的章节内容用于出题")

    # 构建出题素材
    materials_text = "\n\n---\n\n".join([
        f"【章节：{c['section_path']}】（页码：{c['page_range']}）\n{c['content']}"
        for c in chapter_contents
    ])

    # 提取文件名作为默认试卷名
    if name is None:
        filename = os.path.basename(file_path)
        name = os.path.splitext(filename)[0] + "试卷"

    # 调用 Dify 工作流出题（传入完整章节内容）
    inputs = {
        "material_content": materials_text,
        "choice_count": choice_count,
        "blank_count": blank_count,
        "short_answer_count": short_answer_count,
        "difficulty": difficulty
    }

    result = call_dify_workflow(DIFY_QUESTION_API_KEY, inputs)

    # 解析返回结果
    outputs = result.get("data", {}).get("outputs", {})
    questions_json = outputs.get("questions", "{}")

    # 如果是字符串，解析为JSON
    if isinstance(questions_json, str):
        questions_json = questions_json.strip()
        if questions_json.startswith("```json"):
            questions_json = questions_json[7:]
        if questions_json.startswith("```"):
            questions_json = questions_json[3:]
        if questions_json.endswith("```"):
            questions_json = questions_json[:-3]
        questions_json = questions_json.strip()
        questions_json = json.loads(questions_json)

    # 添加分值字段和溯源信息
    for q in questions_json.get("choice_questions", []):
        q["score"] = choice_score
        q["source_file"] = file_path
        q["source_type"] = "chapter"
        if "source_snippet" not in q:
            q["source_snippet"] = ""

    for q in questions_json.get("blank_questions", []):
        q["score"] = blank_score
        q["source_file"] = file_path
        q["source_type"] = "chapter"
        if "source_snippet" not in q:
            q["source_snippet"] = ""

    for q in questions_json.get("short_answer_questions", []):
        q["source_file"] = file_path
        q["source_type"] = "chapter"
        if "source_snippet" not in q:
            q["source_snippet"] = ""

    # 计算总分
    total_score = 0
    total_score += len(questions_json.get("choice_questions", [])) * choice_score
    total_score += len(questions_json.get("blank_questions", [])) * blank_score
    for q in questions_json.get("short_answer_questions", []):
        total_score += q.get("reference_answer", {}).get("total_score", 0)
    questions_json["total_score"] = total_score

    # 添加元数据
    questions_json["source_file"] = {
        "path": file_path,
        "chapters": [c["section_path"] for c in chapter_contents],
        "page_ranges": [c["page_range"] for c in chapter_contents]
    }
    questions_json["generated_at"] = datetime.now().isoformat()
    questions_json["created_by"] = created_by
    questions_json["name"] = name
    questions_json["generation_mode"] = "chapter_based"  # 标记为章节模式
    questions_json["total_count"] = (
        len(questions_json.get("choice_questions", [])) +
        len(questions_json.get("blank_questions", [])) +
        len(questions_json.get("short_answer_questions", []))
    )

    return questions_json


def get_source_chapters_for_question(
    file_path: str,
    question_topic: str,
    top_k: int = 3
) -> List[Dict[str, Any]]:
    """
    获取与问题主题相关的章节内容（用于出题或批阅参考）

    Args:
        file_path: 文档文件路径（支持 PDF/DOCX/PPTX）
        question_topic: 问题主题或关键词
        top_k: 返回的章节数量

    Returns:
        [
            {
                "title": "章节标题",
                "content": "完整内容",
                "section_path": "章节路径",
                "page_range": "1-2"
            }
        ]
    """
    if not PARSE_AVAILABLE:
        raise ImportError("MinerU 解析器不可用")

    result = parse_document(
        file_path,
        output_base=".data/mineru_temp",
        images_output=".data/images",
        cleanup_after_image_move=True
    )
    chunks = result.get('chunks', [])

    # 构建章节内容列表
    chapter_contents = []
    for chunk in chunks:
        content = chunk.content if hasattr(chunk, 'content') else str(chunk)
        if not content.strip():
            continue

        chapter_contents.append({
            "title": chunk.title if hasattr(chunk, 'title') else '',
            "content": content.strip(),
            "section_path": chunk.section_path if hasattr(chunk, 'section_path') else '',
            "page_range": f"{chunk.page_start}-{chunk.page_end}" if hasattr(chunk, 'page_start') else '',
            "source_file": chunk.source_file if hasattr(chunk, 'source_file') else os.path.basename(file_path)
        })

    # 使用关键词检索相关章节
    keywords = question_topic.split() if question_topic else []

    # 简单的关键词匹配筛选
    relevant = []
    for c in chapter_contents:
        content_lower = c['content'].lower()
        if any(kw.lower() in content_lower for kw in keywords):
            relevant.append(c)

    return relevant[:top_k]


def sanitize_filename(name: str) -> str:
    # 移除或替换非法字符
    illegal_chars = r'[<>:"/\\|?*\x00-\x1f]'
    safe_name = re.sub(illegal_chars, '_', name)
    # 移除首尾空格和点
    safe_name = safe_name.strip('. ')
    # 限制长度
    if len(safe_name) > 100:
        safe_name = safe_name[:100]
    # 如果清理后为空，使用时间戳
    if not safe_name:
        safe_name = datetime.now().strftime('%Y%m%d_%H%M%S')
    return safe_name


def save_exam(exam: dict, name: str = None) -> str:
    """
    保存试卷到对应目录

    - draft 状态：保存到 题库/草稿/ 目录
    - approved 状态：保存到 题库/ 目录

    Args:
        exam: 试卷JSON
        name: 文件名(不含扩展名)，默认使用试卷名称

    Returns:
        保存的文件路径
    """
    # 根据状态确定保存目录
    status = exam.get("status", EXAM_STATUS_DRAFT)
    if status == EXAM_STATUS_APPROVED:
        save_dir = QUESTION_BANK_DIR
    else:
        save_dir = DRAFT_DIR

    # 确保目录存在
    os.makedirs(save_dir, exist_ok=True)
    # 确保草稿目录存在
    os.makedirs(DRAFT_DIR, exist_ok=True)

    # 确定文件名：优先使用试卷名称
    if name is None:
        # 使用试卷名称作为文件名
        exam_name = exam.get("name") or exam.get("topic", "未命名试卷")
        name = sanitize_filename(exam_name)

        # 检查是否已存在同名文件，如果存在则添加时间戳
        filepath = os.path.join(save_dir, f"{name}.json")
        if os.path.exists(filepath):
            timestamp = datetime.now().strftime('_%Y%m%d_%H%M%S')
            name = f"{name}{timestamp}"

    filepath = os.path.join(save_dir, f"{name}.json")

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(exam, f, ensure_ascii=False, indent=2)

    print(f"试卷已保存: {filepath} (状态: {status})")
    return filepath


def load_exam(filepath: str) -> dict:
    """加载试卷"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==================== 题库管理函数 ====================

def list_exams(status: str = None, page: int = 1, limit: int = 20) -> dict:
    """
    获取试卷列表

    Args:
        status: 状态过滤（draft/pending_review/approved/rejected）
        page: 页码
        limit: 每页数量

    Returns:
        {
            "exams": [...],
            "total": int,
            "page": int
        }
    """
    # 确保目录存在
    os.makedirs(QUESTION_BANK_DIR, exist_ok=True)
    os.makedirs(DRAFT_DIR, exist_ok=True)

    exams = []

    # 从题库目录和草稿目录加载试卷
    for directory in [QUESTION_BANK_DIR, DRAFT_DIR]:
        if not os.path.exists(directory):
            continue
        for filename in os.listdir(directory):
            if not filename.endswith('.json'):
                continue

            filepath = os.path.join(directory, filename)
            try:
                exam = load_exam(filepath)
                # 状态过滤
                if status and exam.get("status") != status:
                    continue
                # 只返回摘要信息
                exams.append({
                    "exam_id": exam.get("exam_id", filename[:-5]),
                    "name": exam.get("name") or exam.get("topic", "未命名试卷"),
                    "topic": exam.get("topic", ""),
                    "status": exam.get("status", "approved"),
                    "total_count": exam.get("total_count", 0),
                    "total_score": exam.get("total_score", 0),
                    "created_at": exam.get("created_at", ""),
                    "created_by": exam.get("created_by", ""),
                    "filename": filename,
                    "filepath": filepath
                })
            except Exception as e:
                print(f"加载试卷失败 {filename}: {e}")
                continue

    # 按创建时间倒序
    exams.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # 分页
    total = len(exams)
    start = (page - 1) * limit
    end = start + limit

    return {
        "exams": exams[start:end],
        "total": total,
        "page": page
    }


def _find_exam_filepath(exam_id: str) -> Optional[str]:
    """
    查找试卷文件路径（在题库和草稿目录中查找）

    Args:
        exam_id: 试卷ID

    Returns:
        文件路径，如果不存在返回None
    """
    # 确保目录存在
    os.makedirs(QUESTION_BANK_DIR, exist_ok=True)
    os.makedirs(DRAFT_DIR, exist_ok=True)

    # 先检查题库目录
    for directory in [DRAFT_DIR, QUESTION_BANK_DIR]:
        for filename in os.listdir(directory):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(directory, filename)
            try:
                exam = load_exam(filepath)
                if exam.get("exam_id") == exam_id:
                    return filepath
            except:
                continue
    return None


def get_exam_by_id(exam_id: str) -> Optional[dict]:
    """
    根据 ID 获取试卷

    Args:
        exam_id: 试卷ID

    Returns:
        试卷JSON，如果不存在返回None
    """
    filepath = _find_exam_filepath(exam_id)
    if filepath:
        return load_exam(filepath)
    return None


def update_exam(exam_id: str, exam_data: dict) -> Optional[dict]:
    """
    更新试卷（合并更新，保留未传字段）

    Args:
        exam_id: 试卷ID
        exam_data: 新的试卷数据（部分字段）

    Returns:
        更新后的试卷，如果不存在返回None
    """
    # 查找试卷文件路径
    filepath = _find_exam_filepath(exam_id)
    if not filepath:
        return None

    # 加载现有试卷数据
    existing_exam = load_exam(filepath)

    # 合并数据：现有数据 + 新数据（新数据覆盖同名字段）
    merged = {**existing_exam, **exam_data}

    # 保留不可修改的字段
    merged["exam_id"] = exam_id
    merged["created_at"] = existing_exam.get("created_at")
    merged["created_by"] = existing_exam.get("created_by")

    # 保留状态（除非明确传入新状态）
    if "status" not in exam_data:
        merged["status"] = existing_exam.get("status", EXAM_STATUS_DRAFT)

    # 更新时间戳
    merged["updated_at"] = datetime.now().isoformat()

    # 重新计算统计
    merged["total_count"] = (
        len(merged.get("choice_questions", [])) +
        len(merged.get("blank_questions", [])) +
        len(merged.get("short_answer_questions", []))
    )

    # 保存到原位置
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    return merged


def delete_exam(exam_id: str) -> bool:
    """
    删除试卷

    Args:
        exam_id: 试卷ID

    Returns:
        是否删除成功
    """
    filepath = _find_exam_filepath(exam_id)
    if filepath and os.path.exists(filepath):
        os.remove(filepath)
        return True

    return False


# ==================== 题目搜索 ====================

def search_questions(keyword: str, question_type: str = None,
                     difficulty: int = None, limit: int = 50) -> dict:
    """
    搜索题目

    Args:
        keyword: 搜索关键词
        question_type: 题型过滤（choice/blank/short_answer）
        difficulty: 难度过滤
        limit: 返回数量限制

    Returns:
        {
            "questions": [...],
            "total": int
        }
    """
    os.makedirs(QUESTION_BANK_DIR, exist_ok=True)

    results = []
    keyword_lower = keyword.lower()

    for filename in os.listdir(QUESTION_BANK_DIR):
        if not filename.endswith('.json'):
            continue

        filepath = os.path.join(QUESTION_BANK_DIR, filename)
        try:
            exam = load_exam(filepath)
            exam_id = exam.get("exam_id", filename[:-5])
            exam_name = exam.get("topic", filename[:-5])

            # 搜索选择题
            if not question_type or question_type == "choice":
                for q in exam.get("choice_questions", []):
                    if difficulty and q.get("difficulty") != difficulty:
                        continue
                    content = q.get("content", "").lower()
                    if keyword_lower in content:
                        results.append({
                            "exam_id": exam_id,
                            "exam_name": exam_name,
                            "type": "choice",
                            "question": q
                        })

            # 搜索填空题
            if not question_type or question_type == "blank":
                for q in exam.get("blank_questions", []):
                    if difficulty and q.get("difficulty") != difficulty:
                        continue
                    content = q.get("content", "").lower()
                    if keyword_lower in content:
                        results.append({
                            "exam_id": exam_id,
                            "exam_name": exam_name,
                            "type": "blank",
                            "question": q
                        })

            # 搜索简答题
            if not question_type or question_type == "short_answer":
                for q in exam.get("short_answer_questions", []):
                    if difficulty and q.get("difficulty") != difficulty:
                        continue
                    content = q.get("content", "").lower()
                    if keyword_lower in content:
                        results.append({
                            "exam_id": exam_id,
                            "exam_name": exam_name,
                            "type": "short_answer",
                            "question": q
                        })

        except Exception as e:
            print(f"搜索试卷失败 {filename}: {e}")
            continue

    return {
        "questions": results[:limit],
        "total": len(results)
    }


def grade_question(question: dict, student_answer: str, user_token: str = None) -> dict:
    """
    批阅单道题

    Args:
        question: 题目信息(含正确答案和分值)
        student_answer: 学生答案
        user_token: 用户认证token（由网关注入）

    Returns:
        批阅结果
    """
    # 判断题型
    if 'options' in question:
        # 选择题
        question_type = "choice"
        correct_answer = question.get("answer", "")
        max_score = question.get("score", 2)  # 从试卷获取分值，默认2分
    elif 'reference_answer' in question:
        # 简答题 - 使用blank类型（填空和简答合并处理）
        question_type = "blank"
        correct_answer = json.dumps(question.get("reference_answer", {}), ensure_ascii=False)
        max_score = question.get("reference_answer", {}).get("total_score", 10)
    else:
        # 填空题
        question_type = "blank"
        correct_answer = question.get("answer", "")
        max_score = question.get("score", 3)  # 从试卷获取分值，默认3分

    inputs = {
        "question_id": question.get("id", 0),
        "question_type": question_type,
        "question_content": question.get("content", ""),
        "correct_answer": correct_answer,
        "student_answer": student_answer,
        "max_score": max_score,
        # 模拟用户认证信息（用于访问/search接口）
        "user_id": "exam-system",
        "user_role": "admin",
        "user_department": ""
    }

    print(f"[DEBUG] 批阅题目: 类型={question_type}, ID={question.get('id', 0)}")

    try:
        result = call_dify_workflow(DIFY_GRADE_API_KEY, inputs)
        outputs = parse_json_response(result)
    except Exception as e:
        print(f"[ERROR] 批阅题目失败: {e}")
        # 返回默认结果，避免整个批阅流程失败
        return {
            "score": 0,
            "max_score": max_score,
            "feedback": f"批阅服务暂时不可用: {str(e)}",
            "correct": False,
            "error": True
        }

    # 解析返回结果
    grade_result = outputs.get("result", {})

    # 如果是字符串，尝试解析JSON
    if isinstance(grade_result, str):
        grade_result = grade_result.strip()
        if grade_result.startswith("```json"):
            grade_result = grade_result[7:]
        if grade_result.startswith("```"):
            grade_result = grade_result[3:]
        if grade_result.endswith("```"):
            grade_result = grade_result[:-3]
        grade_result = grade_result.strip()
        try:
            grade_result = json.loads(grade_result)
        except:
            # 如果解析失败，返回默认结果
            grade_result = {"score": 0, "feedback": "批阅结果解析失败"}

    # 确保返回字典
    if not isinstance(grade_result, dict):
        grade_result = {"score": 0, "feedback": str(grade_result)}

    return grade_result


def grade_from_mysql(
    exam_id: str,
    student_id: str,
    student_name: str,
    answers: List[Dict],
    user_token: str = None
) -> Dict:
    """
    基于前端传入的题目批卷（不从本地文件读取）

    Args:
        exam_id: 试卷ID（前端生成）
        student_id: 学生ID
        student_name: 学生姓名
        answers: 答案列表，每项包含：
            {
                "question_id": "q_uuid_001",
                "question_type": "choice/blank/short_answer",
                "question_content": "题目内容",
                "correct_answer": "A" 或 JSON 字符串（简答题）,
                "max_score": 2,
                "student_answer": "学生答案"
            }
        user_token: 用户认证token（由网关注入）

    Returns:
        批阅报告（与 grade_exam() 返回格式一致）
    """
    report = {
        "report_id": str(uuid.uuid4()),
        "exam_id": exam_id,
        "student_id": student_id,
        "student_name": student_name or "匿名",
        "graded_at": datetime.now().isoformat(),
        "total_score": 0,
        "max_score": 0,
        "results": []
    }

    if not answers:
        report["error"] = "没有答案数据"
        return report

    # 收集所有需要批阅的题目
    tasks = []

    for ans in answers:
        question_type = ans.get("question_type", "choice")
        question_id = ans.get("question_id", "")
        question_content = ans.get("question_content", "")
        correct_answer = ans.get("correct_answer", "")
        max_score = ans.get("max_score", 2)
        student_answer = ans.get("student_answer", "")

        # 构造题目对象（用于 grade_question）
        question = {
            "id": question_id,
            "content": question_content,
            "score": max_score
        }

        # 根据题型设置答案格式
        if question_type == "choice":
            question["options"] = []  # 选择题选项
            question["answer"] = correct_answer
        elif question_type == "short_answer":
            # 简答题答案是 JSON 字符串
            try:
                question["reference_answer"] = json.loads(correct_answer) if isinstance(correct_answer, str) else correct_answer
            except (json.JSONDecodeError, TypeError):
                question["reference_answer"] = {
                    "points": [{"point": correct_answer, "score": max_score}],
                    "total_score": max_score
                }
        else:  # blank
            question["answer"] = correct_answer

        tasks.append({
            "type": question_type,
            "question": question,
            "student_answer": student_answer,
            "qid": question_id,
            "max_score": max_score
        })

    # 并发批阅（最多 5 个并发）
    print(f"[INFO] 开始并发批阅 {len(tasks)} 道题目（来自前端）...")
    results = [None] * len(tasks)  # 保持顺序

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_index = {
            executor.submit(grade_question, task["question"], task["student_answer"], user_token): i
            for i, task in enumerate(tasks)
        }

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                print(f"[ERROR] 题目批阅失败: {e}")
                # 失败时返回默认结果
                results[index] = {"score": 0, "feedback": f"批阅失败: {str(e)}", "error": True}

    # 处理结果
    for i, task in enumerate(tasks):
        result = results[i]
        qid = task["qid"]
        q_type = task["type"]
        max_score = task["max_score"]
        student_answer = task["student_answer"]
        question = task["question"]

        q_score = result.get("score", 0)
        report["total_score"] += q_score
        report["max_score"] += max_score

        result_item = {
            "question_id": qid,
            "question_type": q_type,
            "question_content": question.get("content", ""),
            "student_answer": student_answer,
            "score": q_score,
            "max_score": max_score,
            "feedback": result.get("feedback", ""),
            "correct": result.get("correct", False)
        }

        # 简答题添加更多字段
        if q_type == "short_answer":
            result_item["correct_answer"] = question.get("reference_answer", {})
            result_item["highlights"] = result.get("highlights", [])
            result_item["shortcomings"] = result.get("shortcomings", [])
            result_item["score_details"] = result.get("score_details", [])
        elif q_type == "choice":
            result_item["correct_answer"] = question.get("answer", "")
        else:
            result_item["correct_answer"] = question.get("answer", "")
            result_item["highlights"] = result.get("highlights", [])
            result_item["shortcomings"] = result.get("shortcomings", [])

        report["results"].append(result_item)

    # 计算得分率
    report["score_rate"] = round(report["total_score"] / report["max_score"] * 100, 1) if report["max_score"] > 0 else 0

    print(f"[INFO] 批阅完成: 得分 {report['total_score']}/{report['max_score']} ({report['score_rate']}%)")
    return report


def grade_exam(exam_filepath: str, student_answers: dict, student_name: str = None) -> dict:
    """
    批阅整份试卷

    Args:
        exam_filepath: 试卷文件路径或exam_id
        student_answers: 学生答案，格式: {题型_题号: 答案}
                         例如: {"choice_1": "A", "blank_1": "答案", "short_answer_1": "学生作答"}
        student_name: 学生姓名

    Returns:
        批阅报告
    """
    # 支持 exam_id 或文件路径
    if not exam_filepath.endswith('.json'):
        exam = get_exam_by_id(exam_filepath)
        if not exam:
            raise ValueError(f"试卷不存在: {exam_filepath}")
    else:
        exam = load_exam(exam_filepath)

    report = {
        "report_id": str(uuid.uuid4()),
        "exam_id": exam.get("exam_id", ""),
        "exam_name": exam.get("topic", ""),
        "student_name": student_name or "匿名",
        "graded_at": datetime.now().isoformat(),
        "total_score": 0,
        "max_score": 0,
        "questions": []
    }

    # 收集所有需要批阅的题目
    tasks = []

    # 选择题
    for q in exam.get("choice_questions", []):
        qid = q.get("id", 0)
        key = f"choice_{qid}"
        student_answer = student_answers.get(key, "")
        tasks.append({
            "type": "choice",
            "question": q,
            "student_answer": student_answer,
            "qid": qid
        })

    # 填空题
    for q in exam.get("blank_questions", []):
        qid = q.get("id", 0)
        key = f"blank_{qid}"
        student_answer = student_answers.get(key, "")
        tasks.append({
            "type": "blank",
            "question": q,
            "student_answer": student_answer,
            "qid": qid
        })

    # 简答题
    for q in exam.get("short_answer_questions", []):
        qid = q.get("id", 0)
        key = f"short_answer_{qid}"
        student_answer = student_answers.get(key, "")
        tasks.append({
            "type": "short_answer",
            "question": q,
            "student_answer": student_answer,
            "qid": qid
        })

    # 并发批阅（最多 5 个并发）
    print(f"[INFO] 开始并发批阅 {len(tasks)} 道题目...")
    results = [None] * len(tasks)  # 保持顺序

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_index = {
            executor.submit(grade_question, task["question"], task["student_answer"]): i
            for i, task in enumerate(tasks)
        }

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                print(f"[ERROR] 题目批阅失败: {e}")
                # 失败时返回默认结果
                results[index] = {"score": 0, "feedback": f"批阅失败: {str(e)}", "error": True}

    # 处理结果
    for i, task in enumerate(tasks):
        result = results[i]
        q = task["question"]
        qid = task["qid"]
        q_type = task["type"]
        student_answer = task["student_answer"]

        if q_type == "choice":
            q_score = result.get("score", 0)
            q_max = q.get("score", 2)
            report["total_score"] += q_score
            report["max_score"] += q_max
            report["questions"].append({
                "type": "choice",
                "id": qid,
                "content": q.get("content", ""),
                "student_answer": student_answer,
                "correct_answer": q.get("answer", ""),
                "score": q_score,
                "max_score": q_max,
                "feedback": result.get("feedback", ""),
                "correct": result.get("correct", False)
            })
        elif q_type == "blank":
            q_score = result.get("score", 0)
            q_max = q.get("score", 3)
            report["total_score"] += q_score
            report["max_score"] += q_max
            report["questions"].append({
                "type": "blank",
                "id": qid,
                "content": q.get("content", ""),
                "student_answer": student_answer,
                "correct_answer": q.get("answer", ""),
                "score": q_score,
                "max_score": q_max,
                "feedback": result.get("feedback", ""),
                "highlights": result.get("highlights", []),
                "shortcomings": result.get("shortcomings", [])
            })
        elif q_type == "short_answer":
            q_score = result.get("score", 0)
            q_max = q.get("reference_answer", {}).get("total_score", 10)
            report["total_score"] += q_score
            report["max_score"] += q_max
            report["questions"].append({
                "type": "short_answer",
                "id": qid,
                "content": q.get("content", ""),
                "student_answer": student_answer,
                "reference_answer": q.get("reference_answer", {}),
                "score": q_score,
                "max_score": q_max,
                "feedback": result.get("feedback", ""),
                "highlights": result.get("highlights", []),
                "shortcomings": result.get("shortcomings", []),
                "suggestions": result.get("suggestions", []),
                "score_details": result.get("score_details", [])
            })

    # 计算得分率
    report["score_rate"] = round(report["total_score"] / report["max_score"] * 100, 1) if report["max_score"] > 0 else 0

    print(f"[INFO] 批阅完成: 得分 {report['total_score']}/{report['max_score']} ({report['score_rate']}%)")
    return report


def save_grade_report(report: dict, student_name: str = None) -> str:
    """保存批阅报告"""
    os.makedirs(REPORT_DIR, exist_ok=True)

    # 使用 report_id 作为文件名
    report_id = report.get("report_id", datetime.now().strftime('%Y%m%d_%H%M%S'))
    student = student_name or report.get("student_name", "student")

    filename = f"{student}_{report_id[:8]}.json"
    filepath = os.path.join(REPORT_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"批阅报告已保存: {filepath}")
    return filepath


def get_report_by_id(report_id: str) -> Optional[dict]:
    """
    根据ID获取批阅报告

    Args:
        report_id: 报告ID

    Returns:
        报告内容
    """
    os.makedirs(REPORT_DIR, exist_ok=True)

    for filename in os.listdir(REPORT_DIR):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(REPORT_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                report = json.load(f)
            if report.get("report_id") == report_id:
                return report
        except:
            continue

    return None


def list_reports(page: int = 1, limit: int = 20) -> dict:
    """
    获取批阅报告列表

    Args:
        page: 页码
        limit: 每页数量

    Returns:
        {"reports": [...], "total": int, "page": int}
    """
    os.makedirs(REPORT_DIR, exist_ok=True)

    reports = []
    for filename in os.listdir(REPORT_DIR):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(REPORT_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                report = json.load(f)
            reports.append({
                "report_id": report.get("report_id", ""),
                "exam_id": report.get("exam_id", ""),
                "exam_name": report.get("exam_name", ""),
                "student_name": report.get("student_name", ""),
                "total_score": report.get("total_score", 0),
                "max_score": report.get("max_score", 0),
                "score_rate": report.get("score_rate", 0),
                "graded_at": report.get("graded_at", ""),
                "filename": filename
            })
        except:
            continue

    # 按时间倒序
    reports.sort(key=lambda x: x.get("graded_at", ""), reverse=True)

    total = len(reports)
    start = (page - 1) * limit
    end = start + limit

    return {
        "reports": reports[start:end],
        "total": total,
        "page": page
    }


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 示例1: 生成并保存试卷
    # exam = generate_exam(
    #     topic="国家社科基金项目申报",
    #     choice_count=3,
    #     blank_count=2,
    #     short_answer_count=2,
    #     difficulty=3
    # )
    # save_exam(exam, "test1")

    # 示例2: 批阅试卷
    # exam_file = "./题库/test1.json"
    # student_answers = {
    #     "choice_1": "A",
    #     "choice_2": "B",
    #     "choice_3": "C",
    #     "blank_1": "重点课题",
    #     "blank_2": "申请人",
    #     "short_answer_1": "国家社科基金项目包括重点项目、一般项目和青年项目等类别",
    #     "short_answer_2": "申报流程包括提交申请书、专家评审、立项审批等步骤"
    # }
    # report = grade_exam(exam_file, student_answers)
    # save_grade_report(report, "张三")

    print("请先配置DIFY_QUESTION_API_KEY和DIFY_GRADE_API_KEY环境变量")
    print("然后取消注释示例代码运行")

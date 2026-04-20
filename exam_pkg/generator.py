"""
出题生成器 - 结构化 RAG 出题架构

核心功能：
1. 按章节分组检索切片
2. 每章节提取知识点
3. 按知识点精准检索并出题
4. 覆盖控制 + 去重

架构：
    文档 → 章节分组 → 知识点提取 → 定向检索 → 出题 → 合并去重

使用方式：
    from exam_pkg.generator import QuestionGenerator

    generator = QuestionGenerator()
    questions = generator.generate_questions(source_content, question_types, difficulty)
"""

import json
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional

# 导入 LLM 配置
try:
    from config import API_KEY, BASE_URL, MODEL
    LLM_AVAILABLE = True
except ImportError:
    API_KEY = None
    BASE_URL = None
    MODEL = None
    LLM_AVAILABLE = False


# ==================== 辅助函数 ====================

def group_chunks_by_section(chunks: List[Dict]) -> Dict[str, List[Dict]]:
    """
    🔥 结构化出题 Step 1：按章节分组

    将切片按 section 字段分组，便于后续按章节提取知识点
    """
    section_map = defaultdict(list)
    for chunk in chunks:
        section = chunk.get('section', '') or '未分类'
        # 清理章节名称（去除多余的标记）
        section_clean = section.replace('**', '').strip()
        section_map[section_clean].append(chunk)
    return dict(section_map)


def build_semantic_query(question_types: Dict[str, int]) -> str:
    """
    根据题型构建语义化检索 query（保留用于知识点检索）
    """
    query_parts = []
    query_parts.append("重点内容 关键概念 定义")

    if question_types.get('fill_blank', 0) > 0:
        query_parts.append("术语 公式 数值 标准")

    if question_types.get('subjective', 0) > 0:
        query_parts.append("流程 步骤 原则 方法")

    if question_types.get('multiple_choice', 0) > 0:
        query_parts.append("区别 对比 分类")

    return " ".join(query_parts)


def build_knowledge_point_query(knowledge_point: str, question_type: str = None) -> str:
    """
    🔥 结构化出题 Step 3：根据知识点构建精准检索 query

    Args:
        knowledge_point: 知识点名称（如 "请假申请流程"）
        question_type: 题型，用于补充检索词

    Returns:
        精准检索 query
    """
    # 基础：知识点本身
    query_parts = [knowledge_point]

    # 根据题型补充
    if question_type in ['single_choice', 'multiple_choice']:
        query_parts.append("定义 规则 标准")
    elif question_type == 'fill_blank':
        query_parts.append("具体数值 公式 术语")
    elif question_type == 'subjective':
        query_parts.append("详细说明 步骤 流程")

    return " ".join(query_parts)


def safe_parse_questions(result: str) -> List[Dict]:
    """
    🔥 P0 改进：安全解析 JSON，支持自动修复

    尝试多种方式解析 LLM 返回的 JSON：
    1. 直接解析
    2. 提取 ```json 代码块
    3. 提取数组 [...] 模式
    """
    # 尝试直接解析
    try:
        data = json.loads(result)
        if isinstance(data, dict) and 'questions' in data:
            return data['questions']
        elif isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 块
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict) and 'questions' in data:
                return data['questions']
            elif isinstance(data, list):
                return data
        except:
            pass

    # 尝试提取数组
    array_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', result)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except:
            pass

    return []


def validate_questions_schema(questions: List[Dict]) -> List[Dict]:
    """
    🔥 P0 改进：JSON Schema 校验，过滤/修复无效题目

    校验规则：
    - 必须有 type 且在有效类型中
    - 必须有 content.stem
    - 必须有 content.answer
    - 选项题必须有 options
    """
    VALID_TYPES = {'single_choice', 'multiple_choice', 'true_false', 'fill_blank', 'subjective'}
    validated = []

    for q in questions:
        # 必须有 type
        if q.get('type') not in VALID_TYPES:
            continue

        # 必须有 content
        content = q.get('content', {})
        if not content.get('stem'):
            continue

        # 必须有 answer
        if 'answer' not in content:
            continue

        # 选项题必须有 options
        if q['type'] in ['single_choice', 'multiple_choice']:
            if not content.get('data', {}).get('options'):
                continue

        validated.append(q)

    return validated


def build_source_context(chunks: List[Dict]) -> str:
    """
    构建带溯源标记的上下文

    🔥 改进：添加 chunk_id 标记，便于 LLM 精确引用
    """
    context_parts = []
    for chunk in chunks:
        chunk_id = chunk.get('chunk_id', '')
        page_info = f"第{chunk['page']}页" if chunk.get('page') else ""
        section_info = chunk.get('section', '')
        # 添加 chunk_id 标记，格式：[chunk_xxx | 第N页 章节]
        context_parts.append(f"[chunk_id:{chunk_id} | {page_info} {section_info}]\n{chunk['content']}")

    return "\n\n---\n\n".join(context_parts)


def find_referenced_chunks(question: Dict, chunks: List[Dict]) -> List[Dict]:
    """
    找到题目引用的切片

    🔥 改进：优先用 referenced_chunk_ids 精确匹配，其次用 referenced_pages
    """
    # 1. 优先使用 chunk_id 精确匹配
    referenced_chunk_ids = question.get('referenced_chunk_ids', [])
    if referenced_chunk_ids:
        referenced = []
        for chunk in chunks:
            chunk_id = chunk.get('chunk_id', '')
            for ref_id in referenced_chunk_ids:
                # 支持两种格式：直接匹配或去掉 chunk_id: 前缀后匹配
                if chunk_id == ref_id or chunk_id == ref_id.replace('chunk_id:', ''):
                    referenced.append(chunk)
                    break
        if referenced:
            return referenced

    # 2. 退而求其次，使用页码匹配
    referenced_pages = question.get('referenced_pages', [])
    if referenced_pages:
        referenced = []
        for chunk in chunks:
            if chunk.get('page') in referenced_pages:
                referenced.append(chunk)
        if referenced:
            return referenced

    # 3. 都没有，返回第一个切片（作为 fallback）
    return chunks[:1] if chunks else []


# ==================== QuestionGenerator 类 ====================

class QuestionGenerator:
    """本地出题生成器 - 使用本地 OpenAI 客户端"""

    def __init__(self):
        self.client = None
        if LLM_AVAILABLE and API_KEY:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
            except ImportError:
                pass
        self.model = MODEL

    def generate_questions_structured(
        self,
        chunks: List[Dict],
        document_name: str,
        question_types: Dict[str, int],
        difficulty: int = 3
    ) -> List[Dict]:
        """
        🔥 结构化出题主流程（唯一入口）

        流程：
        1. 按章节分组
        2. 每章节提取知识点
        3. 按知识点分配题目数量
        4. 按知识点出题
        5. 合并去重
        """
        total_questions = sum(question_types.values())
        if not chunks or total_questions == 0:
            return []

        # Step 1: 按章节分组
        section_map = group_chunks_by_section(chunks)
        print(f"[结构化出题] 章节数: {len(section_map)}")

        # Step 2: 每章节提取知识点
        all_knowledge_points = []
        for section, section_chunks in section_map.items():
            kps = self._extract_knowledge_points(section, section_chunks)
            all_knowledge_points.extend(kps)
            print(f"  章节 [{section[:20]}...]: 提取 {len(kps)} 个知识点")

        if not all_knowledge_points:
            # 降级：使用传统方式
            print("[结构化出题] 知识点提取失败，降级为传统方式")
            source_content = build_source_context(chunks)
            return self.generate_questions(source_content, document_name, question_types, difficulty, chunks)

        print(f"[结构化出题] 总知识点: {len(all_knowledge_points)}")

        # Step 3: 分配题目数量
        kp_assignments = self._assign_questions_to_kps(
            all_knowledge_points, question_types, total_questions
        )

        # Step 4: 按知识点出题（带重试机制）
        all_questions = []
        failed_assignments = []  # 记录失败的分配，用于补题

        for kp, q_types, q_count in kp_assignments:
            # 找到该知识点相关的 chunks
            kp_chunks = self._retrieve_kp_chunks(kp, chunks)
            if not kp_chunks:
                print(f"  [警告] 知识点 [{kp[:20]}...] 无相关 chunks，跳过")
                failed_assignments.append((kp, q_types, q_count, "无相关chunks"))
                continue

            # 构造上下文并出题
            source_content = build_source_context(kp_chunks)
            prompt = self._build_prompt_for_kp(source_content, kp, q_types, difficulty)

            # 🔥 改进：带重试的出题
            success, questions = self._generate_with_retry(prompt, q_types, kp_chunks, document_name, max_retries=2)

            if success and questions:
                # 🔥 新增：校验题型一致性
                validated_questions = self._validate_question_types(questions, q_types)
                all_questions.extend(validated_questions)
            else:
                failed_assignments.append((kp, q_types, q_count, "出题失败"))

        # 🔥 Step 4.5: 补题机制 - 对不足的题型进行补充
        current_counts = defaultdict(int)
        for q in all_questions:
            current_counts[q.get('question_type')] += 1

        for q_type, target_count in question_types.items():
            shortage = target_count - current_counts.get(q_type, 0)
            if shortage > 0:
                print(f"  [补题] {q_type} 缺少 {shortage} 道，尝试补充...")
                extra_questions = self._makeup_questions(chunks, q_type, shortage, difficulty, document_name)
                all_questions.extend(extra_questions)

        # Step 5: 去重 + 数量校正
        final_questions = self._deduplicate_and_balance(all_questions, question_types)

        # 🔥 最终日志：输出题型分布
        final_counts = defaultdict(int)
        for q in final_questions:
            final_counts[q.get('question_type')] += 1
        print(f"[出题完成] 题型分布: {dict(final_counts)}")

        return final_questions

    def _generate_with_retry(
        self,
        prompt: str,
        q_types: Dict[str, int],
        chunks: List[Dict],
        document_name: str,
        max_retries: int = 2
    ) -> tuple:
        """
        🔥 带重试的出题方法

        Returns:
            (success: bool, questions: List[Dict])
        """
        for attempt in range(max_retries + 1):
            try:
                response = self._call_llm(prompt)
                raw_questions = safe_parse_questions(response)
                validated = validate_questions_schema(raw_questions)

                if validated:
                    enriched = self._enrich_with_source_trace(validated, chunks, document_name)
                    return (True, enriched)
                else:
                    print(f"    [重试 {attempt+1}] JSON 解析成功但题目无效")

            except Exception as e:
                print(f"    [重试 {attempt+1}] 出题异常: {e}")

        return (False, [])

    def _validate_question_types(
        self,
        questions: List[Dict],
        expected_types: Dict[str, int]
    ) -> List[Dict]:
        """
        🔥 校验题型一致性，过滤不符合预期的题目

        只保留 expected_types 中指定的题型
        """
        valid_types = set(expected_types.keys())
        validated = []

        for q in questions:
            q_type = q.get('question_type') or q.get('type')
            if q_type in valid_types:
                validated.append(q)
            else:
                print(f"    [过滤] 题型 {q_type} 不在预期范围内")

        return validated

    def _makeup_questions(
        self,
        chunks: List[Dict],
        q_type: str,
        count: int,
        difficulty: int,
        document_name: str
    ) -> List[Dict]:
        """
        补题机制：为缺少的题型补充题目

        策略：从 chunks 中选择未使用的切片进行补题
        """
        if not chunks or count <= 0:
            return []

        # 简单策略：使用前几个 chunks 进行补题
        makeup_chunks = chunks[:5]
        source_content = build_source_context(makeup_chunks)

        prompt = f"""基于以下文档内容，生成 {count} 道 {self._get_q_type_name(q_type)}。

## 文档内容
{source_content}

## 出题要求
- 题型：{self._get_q_type_name(q_type)}
- 数量：{count} 道
- 难度：{difficulty}/5

## 输出格式（JSON 数组）
{self._get_format_examples()}

请直接输出 JSON 数组："""

        try:
            response = self._call_llm(prompt)
            raw_questions = safe_parse_questions(response)
            validated = validate_questions_schema(raw_questions)
            enriched = self._enrich_with_source_trace(validated, makeup_chunks, document_name)

            # 只取需要的数量
            return enriched[:count]
        except Exception as e:
            print(f"  [补题失败] {e}")
            return []

    def _get_q_type_name(self, q_type: str) -> str:
        """获取题型的中文名称"""
        type_names = {
            'single_choice': '单选题',
            'multiple_choice': '多选题',
            'true_false': '判断题',
            'fill_blank': '填空题',
            'subjective': '简答题'
        }
        return type_names.get(q_type, q_type)

    def _call_llm(self, prompt: str) -> str:
        """调用本地 LLM（OpenAI 兼容接口）"""
        if not self.client:
            raise ValueError("LLM 客户端未初始化，请检查 config.py 中的 API_KEY 配置")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的出题专家，擅长根据文档内容生成各类考试题目。你必须严格按照JSON格式输出，不要有任何其他内容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            return response.choices[0].message.content

        except Exception as e:
            raise Exception(f"LLM 调用失败: {e}")

    def _get_format_examples(self) -> str:
        """返回各题型格式示例"""
        return '''
### 单选题示例
{
  "type": "single_choice",
  "content": {
    "stem": "题干内容",
    "data": {"options": [{"key": "A", "content": "选项A"}, {"key": "B", "content": "选项B"}, {"key": "C", "content": "选项C"}, {"key": "D", "content": "选项D"}]},
    "answer": "B",
    "explanation": "解析..."
  },
  "referenced_chunk_ids": ["chunk_001"]
}

### 填空题示例
{
  "type": "fill_blank",
  "content": {
    "stem": "RAG的全称是___，其核心在于___。",
    "data": {"blank_count": 2},
    "answer": [["检索增强生成"], ["外部知识库", "检索"]],
    "explanation": "解析..."
  },
  "referenced_chunk_ids": ["chunk_003"]
}
'''

    def _extract_knowledge_points(
        self,
        section: str,
        chunks: List[Dict],
        max_points: int = 5
    ) -> List[Dict]:
        """
        🔥 Step 2: 从章节内容提取知识点

        策略：
        1. 长内容（>= 100字）：调用 LLM 提取知识点
        2. 短内容（< 100字）：直接用内容本身作为知识点

        Returns:
            [{"name": "知识点名称", "section": "所属章节"}, ...]
        """
        if not chunks:
            return []

        # 合并同一章节的所有切片内容
        all_content = "\n\n".join(
            c.get('content', '').strip()
            for c in chunks
            if c.get('content', '').strip()
        )

        # 清理纯标点符号
        import re
        all_content = re.sub(r'^[\s\*\-\d\.。、，：:；;]+$', '', all_content, flags=re.MULTILINE)
        all_content = all_content.strip()

        if not all_content:
            return []

        # 🔥 策略分叉：根据内容长度选择不同处理方式
        if len(all_content) < 100:
            # 短内容：直接用内容作为知识点（不调用 LLM）
            # 提取关键短语（去除标点和编号）
            clean_content = re.sub(r'^[\d\.\-\*]+\s*', '', all_content)
            clean_content = re.sub(r'[。、，：:；;\s]+$', '', clean_content)

            if 5 <= len(clean_content) <= 30:
                return [{"name": clean_content, "section": section}]
            return []

        # 长内容：调用 LLM 提取知识点
        prompt = f"""从以下文档内容中提取 {max_points} 个关键知识点。

## 内容
{all_content[:2000]}

## 要求
1. 每个知识点用简短短语描述（5-15字）
2. 知识点应该适合用于出考试题
3. 知识点之间不要重复或重叠
4. 必须返回 JSON 数组格式，不要有其他内容

## 输出格式
["知识点1", "知识点2", "知识点3"]

请直接输出 JSON 数组："""

        try:
            response = self._call_llm(prompt)

            # 清理响应（移除可能的 markdown 标记）
            response = response.strip()
            if response.startswith('```'):
                lines = response.split('\n')
                response = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])

            # 解析 JSON
            result = json.loads(response)
            if isinstance(result, list):
                return [
                    {"name": kp, "section": section}
                    for kp in result[:max_points]
                    if isinstance(kp, str) and 3 <= len(kp) <= 30
                ]
        except json.JSONDecodeError as e:
            print(f"  知识点 JSON 解析失败: {e}")
        except Exception as e:
            print(f"  知识点提取失败: {e}")

        return []

    def _assign_questions_to_kps(
        self,
        knowledge_points: List[Dict],
        question_types: Dict[str, int],
        total_questions: int
    ) -> List[tuple]:
        """
        🔥 Step 3: 将题目分配到各知识点

        🔥 改进策略：
        1. 为每种题型单独分配知识点（确保题型覆盖）
        2. 轮流分配知识点，避免重复
        3. 每个知识点最多负责 1 种题型的 1-2 道题

        Returns:
            [(知识点名称, 题型dict, 题目数量), ...]
        """
        kp_count = len(knowledge_points)
        if kp_count == 0:
            return []

        # 🔥 新策略：为每种题型分配知识点
        # 使用 dict 来累积每个知识点的题型分配
        kp_assignments = {}  # {kp_name: {q_type: count, ...}}

        # 按题型依次分配
        for q_type, type_count in question_types.items():
            if type_count <= 0:
                continue

            assigned_for_type = 0
            kp_idx = 0

            while assigned_for_type < type_count:
                # 循环使用知识点
                kp_idx = kp_idx % kp_count
                kp = knowledge_points[kp_idx]
                kp_name = kp['name']

                # 初始化该知识点的分配记录
                if kp_name not in kp_assignments:
                    kp_assignments[kp_name] = {}

                # 每个知识点对每种题型最多出 1 道
                current_count = kp_assignments[kp_name].get(q_type, 0)
                if current_count < 1:
                    kp_assignments[kp_name][q_type] = current_count + 1
                    assigned_for_type += 1

                kp_idx += 1

                # 防止无限循环（知识点不够用时）
                if kp_idx > kp_count * type_count:
                    break

        # 转换为 List[tuple] 格式
        assignments = []
        for kp_name, q_types in kp_assignments.items():
            total = sum(q_types.values())
            assignments.append((kp_name, q_types, total))

        return assignments

    def _retrieve_kp_chunks(
        self,
        knowledge_point: str,
        all_chunks: List[Dict],
        top_k: int = 5
    ) -> List[Dict]:
        """
        🔥 Step 3.5: 根据知识点检索相关 chunks

        策略：
        1. 先尝试语义检索
        2. 如果结果不足，用关键词匹配补充
        """
        # 构建精准 query
        query = f"{knowledge_point} 定义 规则 说明"

        # 简单的关键词匹配（不调用向量检索，因为 chunks 已经是过滤后的）
        scored_chunks = []
        kp_lower = knowledge_point.lower()

        for chunk in all_chunks:
            content = chunk.get('content', '').lower()
            score = 0

            # 知识点直接匹配
            if kp_lower in content:
                score += 10

            # 关键词匹配
            for keyword in ['定义', '规则', '说明', '标准', '流程']:
                if keyword in content:
                    score += 1

            if score > 0:
                scored_chunks.append((score, chunk))

        # 按分数排序
        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        # 如果匹配不足，补充前面的 chunks
        result = [c for _, c in scored_chunks[:top_k]]
        if len(result) < top_k:
            for chunk in all_chunks:
                if chunk not in result:
                    result.append(chunk)
                    if len(result) >= top_k:
                        break

        return result

    def _build_prompt_for_kp(
        self,
        source_content: str,
        knowledge_point: str,
        question_types: Dict[str, int],
        difficulty: int
    ) -> str:
        """
        🔥 Step 4: 构造针对知识点的出题 Prompt
        """
        q_type_str = ", ".join(f"{t}:{n}道" for t, n in question_types.items())

        return f"""基于以下文档内容，围绕知识点【{knowledge_point}】生成考试题目。

## 文档内容
{source_content}

## 出题要求
- 核心知识点：{knowledge_point}
- 难度等级：{difficulty}/5
- 题型及数量：{q_type_str}

## 🔥 关键约束
1. **必须围绕【{knowledge_point}】出题**，题目内容要与该知识点直接相关
2. **每道题必须基于不同的角度或细节**，避免重复考察同一内容
3. **严禁输出非 JSON 内容**
4. **必须从文档内容中找到依据**

## 输出格式（JSON 数组）
{self._get_format_examples()}

请直接输出 JSON 数组："""

    def _deduplicate_and_balance(
        self,
        questions: List[Dict],
        target_types: Dict[str, int]
    ) -> List[Dict]:
        """
        🔥 Step 5: 去重 + 题型平衡
        """
        if not questions:
            return []

        # 按题型分组
        by_type = defaultdict(list)
        for q in questions:
            q_type = q.get('question_type', 'unknown')
            by_type[q_type].append(q)

        # 去重：同题型的题目，题干相似度高的去重
        deduped = []
        for q_type, q_list in by_type.items():
            seen_stems = set()
            type_questions = []

            for q in q_list:
                stem = q.get('content', {}).get('stem', '')
                stem_key = stem[:50]  # 用前50字作为去重key

                if stem_key not in seen_stems:
                    seen_stems.add(stem_key)
                    type_questions.append(q)

            # 按目标数量截取
            target_count = target_types.get(q_type, 0)
            deduped.extend(type_questions[:target_count])

        return deduped

    def _enrich_with_source_trace(
        self,
        questions: List[Dict],
        chunks: List[Dict],
        document_name: str
    ) -> List[Dict]:
        """
        补充溯源信息

        🔥 只返回 RAG 负责的字段，后端负责的字段（question_id, score, tags）不生成
        """
        enriched = []

        for q in questions:
            # 找到引用的切片
            referenced_chunks = find_referenced_chunks(q, chunks)

            question = {
                # 题型（RAG 负责）
                "question_type": q.get('type'),

                # 难度（RAG 负责）
                "difficulty": q.get('difficulty', 3),

                # 题目内容（RAG 负责）
                "content": q.get('content', {}),

                # 溯源信息（RAG 负责）
                "source_trace": {
                    "document_name": document_name,
                    "chunk_ids": [c.get('chunk_id', '') for c in referenced_chunks],
                    "page_numbers": sorted(set([c.get('page') for c in referenced_chunks if c.get('page')])),
                    "sources": [
                        {
                            "chunk_id": c.get('chunk_id', ''),
                            "page": c.get('page'),
                            "section": c.get('section', ''),
                            "snippet": c['content'][:200] if c.get('content') else ''
                        }
                        for c in referenced_chunks
                    ]
                }
            }
            enriched.append(question)

        return enriched


# ==================== 便捷函数 ====================

def generate_questions_from_content(
    source_content: str,
    document_name: str,
    question_types: Dict[str, int],
    difficulty: int = 3
) -> List[Dict]:
    """便捷函数：从内容生成题目"""
    generator = QuestionGenerator()
    return generator.generate_questions(source_content, document_name, question_types, difficulty)

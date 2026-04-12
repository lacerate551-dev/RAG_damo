"""
Entity Extractor - 实体提取模块

使用 LLM 从文本中提取实体和关系三元组

功能：
- 从文档文本中提取实体（部门、制度、人员、流程等）
- 提取实体之间的关系
- 支持批量处理
- 支持自定义实体类型和关系类型

使用方式：
    from entity_extractor import EntityExtractor

    extractor = EntityExtractor()
    triples = extractor.extract("差旅管理办法由人力资源部负责...")
    for triple in triples:
        print(f"{triple.head.name} --{triple.relation}--> {triple.tail.name}")
"""

import os
import sys
import json
import re
from typing import List, Optional
from dataclasses import dataclass

# Windows 控制台编码处理
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 添加项目根路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 导入配置
try:
    from config import API_KEY, BASE_URL, GRAPH_EXTRACTION_MODEL
except ImportError:
    from rag_demo import API_KEY, BASE_URL
    GRAPH_EXTRACTION_MODEL = "qwen3.5-plus"

from graph.graph_manager import Entity, Triple

from openai import OpenAI


# 企业制度文档的实体类型定义
DEFAULT_ENTITY_TYPES = {
    "部门": "组织机构，如：人力资源部、财务部、行政部",
    "制度": "规章制度，如：差旅管理办法、报销制度、考勤规定",
    "人员": "人员角色，如：员工、经理、审批人、部门负责人",
    "流程": "业务流程，如：报销流程、审批流程、申请流程",
    "金额": "金额标准，如：补助金额、报销限额、费用标准",
    "时间": "时间期限，如：有效期、申请时限、审批时限",
    "条件": "适用条件，如：享受条件、申请条件、适用范围",
    "地点": "地点场所，如：出差地点、办公地点",
    "项目": "业务项目，如：培训项目、工程项目",
}

# 关系类型定义
DEFAULT_RELATION_TYPES = {
    "负责": "部门/人员 对 制度/流程 的管理责任",
    "适用": "制度 对 人员/部门 的适用范围",
    "包含": "制度/流程 包含的子项",
    "审批": "人员 对 流程 的审批权限",
    "限额": "制度 规定的 金额 限制",
    "时效": "制度 规定的 时间 限制",
    "条件": "制度 规定的 适用条件",
    "相关": "制度 与 其他制度 的关联",
    "属于": "人员/制度 属于 某个部门",
    "管理": "部门/人员 管理的范围",
}


@dataclass
class ExtractionResult:
    """提取结果"""
    triples: List[Triple]
    raw_response: str
    success: bool
    error: Optional[str] = None


class EntityExtractor:
    """
    实体提取器

    使用 LLM 从文本中提取实体和关系
    """

    def __init__(
        self,
        model: str = None,
        entity_types: dict = None,
        relation_types: dict = None
    ):
        """
        初始化实体提取器

        Args:
            model: LLM 模型名称
            entity_types: 自定义实体类型
            relation_types: 自定义关系类型
        """
        self.model = model or GRAPH_EXTRACTION_MODEL
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        self.entity_types = entity_types or DEFAULT_ENTITY_TYPES
        self.relation_types = relation_types or DEFAULT_RELATION_TYPES

        # 构建提示词模板
        self.extraction_prompt = self._build_extraction_prompt()

    def _build_extraction_prompt(self) -> str:
        """构建提取提示词"""
        entity_desc = "\n".join([f"- {k}: {v}" for k, v in self.entity_types.items()])
        relation_desc = "\n".join([f"- {k}: {v}" for k, v in self.relation_types.items()])

        # 使用字符串拼接避免花括号冲突
        json_example = '''
{
    "entities": [
        {"name": "实体名称", "type": "实体类型", "properties": {"属性名": "属性值"}}
    ],
    "relations": [
        {"head": "头实体名称", "relation": "关系类型", "tail": "尾实体名称"}
    ]
}
'''

        return """你是一个专业的知识图谱构建助手，负责从企业制度文档中提取实体和关系。

## 实体类型
""" + entity_desc + """

## 关系类型
""" + relation_desc + """

## 提取规则
1. 只提取明确提及的实体和关系，不要臆测
2. 实体名称应保持原文中的准确表述
3. 关系类型必须从给定的关系类型中选择
4. 如果文本中没有明确的关系，返回空列表

## 输出格式
请严格按照以下 JSON 格式输出，不要输出其他内容：
```json
""" + json_example + """```

## 待提取文本
{text}

请提取实体和关系："""

    def extract(
        self,
        text: str,
        doc_source: str = None
    ) -> ExtractionResult:
        """
        从文本中提取实体和关系

        Args:
            text: 输入文本
            doc_source: 文档来源（用于元数据）

        Returns:
            ExtractionResult 包含三元组列表
        """
        # 限制文本长度
        max_length = 3000
        if len(text) > max_length:
            text = text[:max_length] + "..."

        # 直接构建 prompt，避免 format() 花括号冲突
        entity_desc = "\n".join([f"- {k}: {v}" for k, v in self.entity_types.items()])
        relation_desc = "\n".join([f"- {k}: {v}" for k, v in self.relation_types.items()])

        prompt = f"""你是一个专业的知识图谱构建助手，负责从企业制度文档中提取实体和关系。

## 实体类型
{entity_desc}

## 关系类型
{relation_desc}

## 提取规则
1. 只提取明确提及的实体和关系，不要臆测
2. 实体名称应保持原文中的准确表述
3. 关系类型必须从给定的关系类型中选择
4. 如果文本中没有明确的关系，返回空列表

## 输出格式
请严格按照 JSON 格式输出，包含 entities 和 relations 两个字段：
- entities: 实体列表，每个实体包含 name, type, properties
- relations: 关系列表，每个关系包含 head, relation, tail

## 待提取文本
{text}

请提取实体和关系，直接输出JSON："""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的知识图谱构建助手。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # 低温度以获得更稳定的输出
                response_format={"type": "json_object"}
            )

            raw_response = response.choices[0].message.content

            # 解析 JSON 响应
            result = self._parse_response(raw_response, doc_source)

            return ExtractionResult(
                triples=result,
                raw_response=raw_response,
                success=True
            )

        except json.JSONDecodeError as e:
            return ExtractionResult(
                triples=[],
                raw_response=raw_response if 'raw_response' in dir() else "",
                success=False,
                error=f"JSON 解析错误: {e}"
            )
        except Exception as e:
            return ExtractionResult(
                triples=[],
                raw_response="",
                success=False,
                error=str(e)
            )

    def _parse_response(
        self,
        response: str,
        doc_source: str = None
    ) -> List[Triple]:
        """
        解析 LLM 响应，构建三元组

        Args:
            response: LLM 返回的 JSON 字符串
            doc_source: 文档来源

        Returns:
            三元组列表
        """
        triples = []

        try:
            # 清理响应文本
            json_str = response.strip()

            # 尝试提取 JSON 块
            json_match = re.search(r'```json\s*(.*?)\s*```', json_str, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # 尝试提取纯 JSON 块
                json_match = re.search(r'\{[\s\S]*\}', json_str)
                if json_match:
                    json_str = json_match.group(0)

            data = json.loads(json_str)

            # 构建实体映射
            entity_map = {}
            for entity_data in data.get('entities', []):
                name = entity_data.get('name', '').strip()
                entity_type = entity_data.get('type', '').strip()
                properties = entity_data.get('properties', {})

                if name and entity_type:
                    if doc_source:
                        properties['source'] = doc_source
                    entity_map[name] = Entity(
                        name=name,
                        type=entity_type,
                        properties=properties
                    )

            # 构建三元组
            for rel_data in data.get('relations', []):
                head_name = rel_data.get('head', '').strip()
                relation = rel_data.get('relation', '').strip()
                tail_name = rel_data.get('tail', '').strip()

                if head_name and relation and tail_name:
                    # 获取或创建实体
                    head_entity = entity_map.get(head_name)
                    if not head_entity:
                        head_entity = Entity(name=head_name, type="未知")
                    tail_entity = entity_map.get(tail_name)
                    if not tail_entity:
                        tail_entity = Entity(name=tail_name, type="未知")

                    # 验证关系类型
                    if relation in self.relation_types:
                        triples.append(Triple(
                            head=head_entity,
                            relation=relation,
                            tail=tail_entity
                        ))

        except json.JSONDecodeError as e:
            print(f"JSON 解析错误: {e}")
        except Exception as e:
            print(f"解析响应时出错: {e}")

        return triples

    def extract_batch(
        self,
        texts: List[str],
        doc_sources: List[str] = None,
        verbose: bool = True
    ) -> List[Triple]:
        """
        批量提取实体和关系

        Args:
            texts: 文本列表
            doc_sources: 文档来源列表
            verbose: 是否打印进度

        Returns:
            所有三元组的列表
        """
        all_triples = []
        doc_sources = doc_sources or [None] * len(texts)

        for i, (text, source) in enumerate(zip(texts, doc_sources)):
            if verbose:
                print(f"  正在提取 [{i+1}/{len(texts)}]...")

            result = self.extract(text, source)

            if result.success:
                all_triples.extend(result.triples)
                if verbose:
                    print(f"    提取到 {len(result.triples)} 个三元组")
            else:
                if verbose:
                    print(f"    提取失败: {result.error}")

        # 去重
        unique_triples = self._deduplicate_triples(all_triples)

        if verbose:
            print(f"\n总计提取 {len(unique_triples)} 个唯一三元组")

        return unique_triples

    def _deduplicate_triples(self, triples: List[Triple]) -> List[Triple]:
        """
        去除重复的三元组

        Args:
            triples: 三元组列表

        Returns:
            去重后的三元组列表
        """
        seen = set()
        unique = []

        for triple in triples:
            key = (triple.head.name, triple.relation, triple.tail.name)
            if key not in seen:
                seen.add(key)
                unique.append(triple)

        return unique

    def extract_from_document_chunks(
        self,
        chunks: List[dict],
        verbose: bool = True
    ) -> List[Triple]:
        """
        从文档分块中提取实体和关系

        Args:
            chunks: 文档分块列表，每个分块包含 'content' 和 'metadata'
            verbose: 是否打印进度

        Returns:
            三元组列表
        """
        texts = []
        sources = []

        for chunk in chunks:
            content = chunk.get('content', chunk.get('document', ''))
            metadata = chunk.get('metadata', {})
            source = metadata.get('source', 'unknown')

            texts.append(content)
            sources.append(source)

        return self.extract_batch(texts, sources, verbose)


# ==================== 便捷函数 ====================

def extract_entities_from_text(text: str) -> List[Triple]:
    """
    便捷函数：从文本提取实体

    Args:
        text: 输入文本

    Returns:
        三元组列表
    """
    extractor = EntityExtractor()
    result = extractor.extract(text)
    return result.triples


# ==================== 测试代码 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("Entity Extractor 测试")
    print("=" * 60)

    # 测试文本
    test_text = """
    差旅管理办法

    第一章 总则

    第一条 为规范公司差旅管理，根据公司相关规定，制定本办法。

    第二条 本办法适用于公司全体员工。

    第三条 人力资源部负责本办法的解释和修订。

    第二章 出差审批

    第四条 员工出差须提前申请，经部门负责人审批后方可执行。

    第五条 出差申请流程：
    1. 员工填写出差申请单
    2. 部门负责人审批
    3. 超过3天的出差需分管领导审批

    第三章 差旅费用

    第六条 交通费按实际发生额报销，最高限额：
    - 飞机：经济舱
    - 高铁：一等座

    第七条 住宿费标准：
    - 一线城市：500元/天
    - 二线城市：300元/天

    第八条 餐饮补助：100元/天

    第四章 附则

    第九条 本办法自发布之日起执行，由人力资源部负责解释。
    """

    extractor = EntityExtractor()

    print("\n提取实体和关系...")
    result = extractor.extract(test_text, "差旅管理办法.txt")

    if result.success:
        print(f"\n成功提取 {len(result.triples)} 个三元组:\n")

        # 按关系类型分组显示
        by_relation = {}
        for triple in result.triples:
            if triple.relation not in by_relation:
                by_relation[triple.relation] = []
            by_relation[triple.relation].append(triple)

        for relation, triples in by_relation.items():
            print(f"【{relation}】")
            for triple in triples:
                print(f"  {triple.head.name} ({triple.head.type}) -> {triple.tail.name} ({triple.tail.type})")
            print()
    else:
        print(f"提取失败: {result.error}")

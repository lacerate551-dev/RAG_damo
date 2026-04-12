"""
Graph Manager - Neo4j 图谱管理模块

功能：
- 连接 Neo4j 数据库
- 实体和关系的 CRUD 操作
- 图谱构建与更新
- 子图检索

使用方式：
    from graph_manager import GraphManager

    gm = GraphManager()
    gm.connect()
    gm.create_entity("人力资源部", "部门", {"描述": "负责公司人事管理"})
    gm.create_relation("人力资源部", "负责", "差旅管理办法")
    gm.close()
"""

import os
import sys
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

# Windows 控制台编码处理
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 添加项目根路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 尝试导入配置
try:
    from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, USE_GRAPH_RAG
    HAS_NEO4J_CONFIG = True
except ImportError:
    HAS_NEO4J_CONFIG = False
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASSWORD = "password123"
    USE_GRAPH_RAG = False

# 尝试导入 neo4j
try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False
    print("警告: neo4j 包未安装，图谱功能不可用")
    print("安装命令: pip install neo4j")


@dataclass
class Entity:
    """实体数据类"""
    name: str
    type: str
    properties: Dict[str, Any] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


@dataclass
class Relation:
    """关系数据类"""
    head: str  # 头实体名称
    relation: str  # 关系类型
    tail: str  # 尾实体名称
    properties: Dict[str, Any] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


@dataclass
class Triple:
    """三元组数据类 (头实体, 关系, 尾实体)"""
    head: Entity
    relation: str
    tail: Entity


class GraphManager:
    """
    Neo4j 图谱管理器

    管理知识图谱的构建、查询和更新
    """

    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None
    ):
        """
        初始化图谱管理器

        Args:
            uri: Neo4j 连接地址
            user: 用户名
            password: 密码
        """
        self.uri = uri or NEO4J_URI
        self.user = user or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        self.driver = None
        self.connected = False

    def connect(self) -> bool:
        """
        连接 Neo4j 数据库

        Returns:
            是否连接成功
        """
        if not HAS_NEO4J:
            print("错误: neo4j 包未安装")
            return False

        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
            # 测试连接
            with self.driver.session() as session:
                session.run("RETURN 1")
            self.connected = True
            print(f"✓ 已连接到 Neo4j: {self.uri}")
            return True
        except Exception as e:
            print(f"✗ Neo4j 连接失败: {e}")
            self.connected = False
            return False

    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
            self.connected = False
            print("Neo4j 连接已关闭")

    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()

    # ==================== 节点操作 ====================

    def create_entity(
        self,
        name: str,
        entity_type: str,
        properties: Dict[str, Any] = None,
        merge: bool = True
    ) -> bool:
        """
        创建实体节点

        Args:
            name: 实体名称
            entity_type: 实体类型（如：部门、制度、人员等）
            properties: 实体属性
            merge: 是否使用 MERGE（避免重复创建）

        Returns:
            是否创建成功
        """
        if not self.connected:
            return False

        properties = properties or {}
        properties['name'] = name

        query = f"""
        {'MERGE' if merge else 'CREATE'} (n:{entity_type} {{name: $name}})
        SET n += $properties
        RETURN n
        """

        try:
            with self.driver.session() as session:
                result = session.run(query, name=name, properties=properties)
                return result.single() is not None
        except Exception as e:
            print(f"创建实体失败: {e}")
            return False

    def get_entity(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取实体信息

        Args:
            name: 实体名称

        Returns:
            实体属性字典，不存在返回 None
        """
        if not self.connected:
            return None

        query = """
        MATCH (n {name: $name})
        RETURN n, labels(n) as types
        """

        try:
            with self.driver.session() as session:
                result = session.run(query, name=name)
                record = result.single()
                if record:
                    node = record['n']
                    return {
                        'name': node['name'],
                        'types': record['types'],
                        'properties': dict(node)
                    }
                return None
        except Exception as e:
            print(f"查询实体失败: {e}")
            return None

    def delete_entity(self, name: str) -> bool:
        """
        删除实体及其关系

        Args:
            name: 实体名称

        Returns:
            是否删除成功
        """
        if not self.connected:
            return False

        query = """
        MATCH (n {name: $name})
        DETACH DELETE n
        """

        try:
            with self.driver.session() as session:
                session.run(query, name=name)
                return True
        except Exception as e:
            print(f"删除实体失败: {e}")
            return False

    # ==================== 关系操作 ====================

    def create_relation(
        self,
        head: str,
        relation_type: str,
        tail: str,
        properties: Dict[str, Any] = None,
        merge: bool = True
    ) -> bool:
        """
        创建关系

        Args:
            head: 头实体名称
            relation_type: 关系类型（如：负责、适用、包含等）
            tail: 尾实体名称
            properties: 关系属性
            merge: 是否使用 MERGE（避免重复创建）

        Returns:
            是否创建成功
        """
        if not self.connected:
            return False

        # 替换关系类型中的中文字符为拼音或英文（Neo4j 关系类型不支持中文）
        relation_type_safe = self._sanitize_relation_type(relation_type)

        query = f"""
        MATCH (a {{name: $head}})
        MATCH (b {{name: $tail}})
        {'MERGE' if merge else 'CREATE'} (a)-[r:{relation_type_safe}]->(b)
        SET r += $properties
        RETURN r
        """

        try:
            with self.driver.session() as session:
                result = session.run(
                    query,
                    head=head,
                    tail=tail,
                    properties=properties or {}
                )
                return result.single() is not None
        except Exception as e:
            print(f"创建关系失败: {e}")
            return False

    def get_relations(
        self,
        entity_name: str,
        direction: str = "both"
    ) -> List[Dict[str, Any]]:
        """
        获取实体的关系

        Args:
            entity_name: 实体名称
            direction: 关系方向 ("out", "in", "both")

        Returns:
            关系列表
        """
        if not self.connected:
            return []

        if direction == "out":
            pattern = "(n)-[r]->(m)"
        elif direction == "in":
            pattern = "(n)<-[r]-(m)"
        else:
            pattern = "(n)-[r]-(m)"

        query = f"""
        MATCH {pattern}
        WHERE n.name = $name
        RETURN n.name as head, type(r) as relation, m.name as tail,
               properties(r) as properties
        """

        try:
            with self.driver.session() as session:
                result = session.run(query, name=entity_name)
                relations = []
                for record in result:
                    relations.append({
                        'head': record['head'],
                        'relation': record['relation'],
                        'tail': record['tail'],
                        'properties': record['properties']
                    })
                return relations
        except Exception as e:
            print(f"查询关系失败: {e}")
            return []

    # ==================== 图谱构建 ====================

    def build_from_triples(
        self,
        triples: List[Triple],
        batch_size: int = 100
    ) -> int:
        """
        从三元组批量构建图谱

        Args:
            triples: 三元组列表
            batch_size: 批量处理大小

        Returns:
            成功创建的关系数量
        """
        if not self.connected:
            return 0

        # 先创建所有实体（包含属性，如 source）
        entities = {}  # {(name, type): properties}
        for triple in triples:
            entities[(triple.head.name, triple.head.type)] = triple.head.properties or {}
            entities[(triple.tail.name, triple.tail.type)] = triple.tail.properties or {}

        print(f"正在创建 {len(entities)} 个实体...")
        for (name, entity_type), properties in entities.items():
            self.create_entity(name, entity_type, properties)

        # 再创建所有关系
        print(f"正在创建 {len(triples)} 个关系...")
        success_count = 0
        for triple in triples:
            if self.create_relation(
                triple.head.name,
                triple.relation,
                triple.tail.name,
                triple.head.properties
            ):
                success_count += 1

        return success_count

    def clear_graph(self) -> bool:
        """
        清空整个图谱

        Returns:
            是否成功
        """
        if not self.connected:
            return False

        query = "MATCH (n) DETACH DELETE n"

        try:
            with self.driver.session() as session:
                session.run(query)
                print("图谱已清空")
                return True
        except Exception as e:
            print(f"清空图谱失败: {e}")
            return False

    # ==================== 查询操作 ====================

    def search_subgraph(
        self,
        entity_names: List[str],
        depth: int = 2,
        allowed_sources: List[str] = None
    ) -> Dict[str, Any]:
        """
        根据实体名称搜索子图

        Args:
            entity_names: 实体名称列表
            depth: 搜索深度
            allowed_sources: 允许访问的来源文件列表（用于权限过滤）
                           例如: ['public/', 'internal/'] 表示只访问公开和内部文档

        Returns:
            包含节点和边的子图数据
        """
        if not self.connected:
            return {'nodes': [], 'edges': []}

        # 构建来源过滤条件
        source_filter = ""
        if allowed_sources:
            # 构建路径前缀匹配条件
            source_conditions = " OR ".join([
                f"n.source STARTS WITH '{prefix}' OR m.source STARTS WITH '{prefix}'"
                for prefix in allowed_sources
            ])
            # 也允许没有 source 属性的节点（兼容旧数据）
            source_filter = f"AND (n.source IS NULL OR m.source IS NULL OR {source_conditions})"

        query = f"""
        MATCH path = (n)-[*1..{depth}]-(m)
        WHERE n.name IN $names
        {source_filter}
        RETURN DISTINCT
            n.name as start_name, labels(n) as start_types, n.source as start_source,
            m.name as end_name, labels(m) as end_types, m.source as end_source,
            [rel in relationships(path) | {{
                from: startNode(rel).name,
                to: endNode(rel).name,
                type: type(rel)
            }}] as edges
        LIMIT 100
        """

        try:
            with self.driver.session() as session:
                result = session.run(query, names=entity_names)
                nodes = {}  # 使用字典存储，key为节点名
                edges = []

                for record in result:
                    # 添加节点（将列表转为字符串作为类型）
                    start_name = record['start_name']
                    start_types = record['start_types']
                    start_source = record['start_source'] or ''
                    end_name = record['end_name']
                    end_types = record['end_types']
                    end_source = record['end_source'] or ''

                    # 二次权限过滤：确保节点来源符合权限
                    if allowed_sources:
                        start_allowed = not start_source or any(start_source.startswith(p) for p in allowed_sources)
                        end_allowed = not end_source or any(end_source.startswith(p) for p in allowed_sources)
                        if not start_allowed or not end_allowed:
                            continue

                    # 使用节点名作为key，避免列表不可哈希问题
                    if start_name not in nodes:
                        nodes[start_name] = {'name': start_name, 'types': start_types, 'source': start_source}
                    if end_name not in nodes:
                        nodes[end_name] = {'name': end_name, 'types': end_types, 'source': end_source}

                    # 添加边
                    for edge in record['edges']:
                        edges.append(edge)

                return {
                    'nodes': list(nodes.values()),
                    'edges': edges
                }
        except Exception as e:
            print(f"子图搜索失败: {e}")
            return {'nodes': [], 'edges': []}

    def get_entity_neighbors(
        self,
        entity_name: str,
        relation_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        获取实体的邻居节点

        Args:
            entity_name: 实体名称
            relation_type: 可选，过滤关系类型

        Returns:
            邻居节点列表
        """
        if not self.connected:
            return []

        if relation_type:
            relation_type_safe = self._sanitize_relation_type(relation_type)
            query = f"""
            MATCH (n {{name: $name}})-[r:{relation_type_safe}]-(m)
            RETURN m.name as name, labels(m) as types,
                   type(r) as relation, properties(m) as properties
            """
        else:
            query = """
            MATCH (n {name: $name})-[r]-(m)
            RETURN m.name as name, labels(m) as types,
                   type(r) as relation, properties(m) as properties
            """

        try:
            with self.driver.session() as session:
                result = session.run(query, name=entity_name)
                neighbors = []
                for record in result:
                    neighbors.append({
                        'name': record['name'],
                        'types': record['types'],
                        'relation': record['relation'],
                        'properties': record['properties']
                    })
                return neighbors
        except Exception as e:
            print(f"查询邻居失败: {e}")
            return []

    def search_by_relation(
        self,
        relation_type: str,
        entity_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        按关系类型搜索

        Args:
            relation_type: 关系类型
            entity_type: 可选，过滤实体类型

        Returns:
            匹配的三元组列表
        """
        if not self.connected:
            return []

        relation_type_safe = self._sanitize_relation_type(relation_type)

        if entity_type:
            query = f"""
            MATCH (a:{entity_type})-[r:{relation_type_safe}]->(b)
            RETURN a.name as head, type(r) as relation, b.name as tail
            """
        else:
            query = f"""
            MATCH (a)-[r:{relation_type_safe}]->(b)
            RETURN a.name as head, type(r) as relation, b.name as tail
            """

        try:
            with self.driver.session() as session:
                result = session.run(query)
                triples = []
                for record in result:
                    triples.append({
                        'head': record['head'],
                        'relation': record['relation'],
                        'tail': record['tail']
                    })
                return triples
        except Exception as e:
            print(f"关系搜索失败: {e}")
            return []

    # ==================== 统计信息 ====================

    def get_stats(self) -> Dict[str, int]:
        """
        获取图谱统计信息

        Returns:
            统计数据字典
        """
        if not self.connected:
            return {'nodes': 0, 'edges': 0, 'types': {}}

        try:
            with self.driver.session() as session:
                # 节点数量
                node_result = session.run("MATCH (n) RETURN count(n) as count")
                node_count = node_result.single()['count']

                # 边数量
                edge_result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
                edge_count = edge_result.single()['count']

                # 实体类型分布
                type_result = session.run("""
                    MATCH (n)
                    RETURN labels(n)[0] as type, count(n) as count
                    ORDER BY count DESC
                """)
                type_dist = {record['type']: record['count'] for record in type_result}

                return {
                    'nodes': node_count,
                    'edges': edge_count,
                    'types': type_dist
                }
        except Exception as e:
            print(f"获取统计信息失败: {e}")
            return {'nodes': 0, 'edges': 0, 'types': {}}

    # ==================== 辅助方法 ====================

    def _sanitize_relation_type(self, relation_type: str) -> str:
        """
        将关系类型转换为 Neo4j 兼容格式

        Neo4j 关系类型只支持字母、数字和下划线
        """
        # 中文关系到英文的映射
        relation_map = {
            "负责": "RESPONSIBLE_FOR",
            "适用": "APPLIES_TO",
            "包含": "CONTAINS",
            "审批": "APPROVES",
            "限额": "HAS_LIMIT",
            "时效": "HAS_DEADLINE",
            "条件": "HAS_CONDITION",
            "相关": "RELATED_TO",
            "属于": "BELONGS_TO",
            "管理": "MANAGES",
            "使用": "USES",
        }

        if relation_type in relation_map:
            return relation_map[relation_type]

        # 如果不在映射中，尝试转换
        # 替换空格和特殊字符
        safe_type = relation_type.replace(" ", "_").replace("-", "_")
        # 如果是纯中文，使用 RELATED_TO
        if all('\u4e00' <= c <= '\u9fff' for c in relation_type):
            return "RELATED_TO"

        return safe_type.upper()


# ==================== 便捷函数 ====================

def get_graph_manager() -> Optional[GraphManager]:
    """
    获取图谱管理器实例

    Returns:
        GraphManager 实例，如果 Neo4j 未配置则返回 None
    """
    if not HAS_NEO4J:
        print("警告: neo4j 包未安装")
        return None

    if not USE_GRAPH_RAG:
        print("提示: Graph RAG 功能未启用 (USE_GRAPH_RAG=False)")
        return None

    gm = GraphManager()
    if gm.connect():
        return gm
    return None


# ==================== 测试代码 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("Graph Manager 测试")
    print("=" * 60)

    # 测试连接
    gm = GraphManager()
    if gm.connect():
        print("\n测试创建实体和关系...")

        # 创建测试实体
        gm.create_entity("人力资源部", "部门", {"描述": "负责公司人事管理"})
        gm.create_entity("差旅管理办法", "制度", {"版本": "v2.0"})
        gm.create_entity("张三", "人员", {"职位": "员工"})

        # 创建测试关系
        gm.create_relation("人力资源部", "负责", "差旅管理办法")
        gm.create_relation("差旅管理办法", "适用", "张三")

        # 查询测试
        print("\n查询实体: 人力资源部")
        entity = gm.get_entity("人力资源部")
        print(f"  结果: {entity}")

        print("\n查询关系: 差旅管理办法")
        relations = gm.get_relations("差旅管理办法")
        print(f"  关系数: {len(relations)}")
        for r in relations:
            print(f"    {r['head']} -> {r['relation']} -> {r['tail']}")

        # 统计信息
        print("\n图谱统计:")
        stats = gm.get_stats()
        print(f"  节点数: {stats['nodes']}")
        print(f"  边数: {stats['edges']}")
        print(f"  类型分布: {stats['types']}")

        # 清理测试数据
        print("\n清理测试数据...")
        gm.delete_entity("人力资源部")
        gm.delete_entity("差旅管理办法")
        gm.delete_entity("张三")

        gm.close()
    else:
        print("无法连接到 Neo4j，请确保:")
        print("1. Neo4j 服务已启动")
        print("2. 配置正确 (config.py 中的 NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)")

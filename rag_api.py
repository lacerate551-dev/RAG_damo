"""
RAG API服务 - 供Dify HTTP节点调用
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入RAG组件
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb
from rank_bm25 import BM25Okapi
import jieba
import pickle
import numpy as np

# 路径配置
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")

EMBEDDING_MODEL_PATH = os.path.join(MODELS_DIR, "bge-base-zh-v1.5")
RERANK_MODEL_PATH = os.path.join(MODELS_DIR, "bge-reranker-base")
CHROMA_DB_PATH = os.path.join(PROJECT_ROOT, "chroma_db")
BM25_INDEX_PATH = os.path.join(PROJECT_ROOT, "bm25_index.pkl")
VECTOR_WEIGHT = 0.5
BM25_WEIGHT = 0.5

print("初始化RAG组件...")

# 加载模型
embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)

# 加载Rerank模型
if os.path.exists(RERANK_MODEL_PATH) and os.path.exists(os.path.join(RERANK_MODEL_PATH, "config.json")):
    reranker = CrossEncoder(RERANK_MODEL_PATH)
else:
    print(f"警告: Rerank模型未找到，请下载到 {RERANK_MODEL_PATH}")
    print("  huggingface-cli download BAAI/bge-reranker-base --local-dir ./models/bge-reranker-base")
    reranker = None

# 加载向量库
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = chroma_client.get_collection("knowledge_base")
print(f"向量库: {collection.count()} 个文档")

# 加载BM25索引
with open(BM25_INDEX_PATH, 'rb') as f:
    bm25_data = pickle.load(f)
bm25_docs = bm25_data['documents']
bm25_metas = bm25_data['metadatas']
bm25_ids = bm25_data['ids']
tokenized_docs = [list(jieba.cut(doc)) for doc in bm25_docs]
bm25 = BM25Okapi(tokenized_docs)

print("RAG组件初始化完成！")

# Flask应用
app = Flask(__name__)
CORS(app)


def reciprocal_rank_fusion(results_list, weights=None, k=60):
    """RRF融合"""
    if weights is None:
        weights = [1.0] * len(results_list)

    doc_scores = {}
    for results, weight in zip(results_list, weights):
        if not results['documents'][0]:
            continue
        for rank, (doc_id, doc, meta) in enumerate(zip(
            results['ids'][0],
            results['documents'][0],
            results['metadatas'][0]
        )):
            rrf_score = weight / (k + rank + 1)
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {'score': 0.0, 'doc': doc, 'meta': meta}
            doc_scores[doc_id]['score'] += rrf_score

    sorted_items = sorted(doc_scores.items(), key=lambda x: x[1]['score'], reverse=True)
    return {
        'ids': [[item[0] for item in sorted_items]],
        'documents': [[item[1]['doc'] for item in sorted_items]],
        'metadatas': [[item[1]['meta'] for item in sorted_items]],
        'distances': [[item[1]['score'] for item in sorted_items]]
    }


def search_vector(query, top_k=15):
    """向量检索"""
    query_vector = embedding_model.encode(query).tolist()
    return collection.query(query_embeddings=[query_vector], n_results=top_k)


def search_bm25(query, top_k=15):
    """BM25检索"""
    tokenized_query = list(jieba.cut(query))
    scores = bm25.get_scores(tokenized_query)
    top_indices = np.argsort(scores)[::-1][:top_k]
    return {
        'ids': [[bm25_ids[i] for i in top_indices]],
        'documents': [[bm25_docs[i] for i in top_indices]],
        'metadatas': [[bm25_metas[i] for i in top_indices]],
        'distances': [[float(scores[i]) for i in top_indices]]
    }


def search_hybrid(query, top_k=5, candidates=15):
    """混合检索 + Rerank"""
    # 向量检索
    vector_results = search_vector(query, candidates)
    # BM25检索
    bm25_results = search_bm25(query, candidates)
    # RRF融合
    fused_results = reciprocal_rank_fusion([vector_results, bm25_results], [VECTOR_WEIGHT, BM25_WEIGHT])

    # Rerank
    pairs = [(query, doc) for doc in fused_results['documents'][0]]
    scores = reranker.predict(pairs)
    sorted_indices = np.argsort(scores)[::-1][:top_k]

    return {
        'ids': [[fused_results['ids'][0][i] for i in sorted_indices]],
        'documents': [[fused_results['documents'][0][i] for i in sorted_indices]],
        'metadatas': [[fused_results['metadatas'][0][i] for i in sorted_indices]],
        'distances': [[float(scores[i]) for i in sorted_indices]]
    }


@app.route('/search', methods=['POST'])
def search():
    """检索接口"""
    data = request.json
    query = data.get('query', '')
    top_k = data.get('top_k', 5)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    results = search_hybrid(query, top_k=top_k)

    return jsonify({
        'contexts': results['documents'][0],
        'metadatas': results['metadatas'][0],
        'scores': results['distances'][0]
    })


@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({'status': 'ok', 'docs_count': collection.count()})


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("RAG API服务启动")
    print("地址: http://0.0.0.0:5000")
    print("接口: POST /search  body: {query, top_k}")
    print("=" * 50 + "\n")
    app.run(host='0.0.0.0', port=5000)
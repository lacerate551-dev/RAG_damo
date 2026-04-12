"""
本地出题批卷数据库 - 用于开发测试

使用 SQLite 存储：
1. 题目表（含溯源信息）
2. 试卷表
3. 学生答卷表
4. 批阅报告表
"""

import os
import sys
import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


class ExamLocalDB:
    """本地出题批卷数据库"""

    def __init__(self, db_path: str = "./data/exam_local.db"):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """初始化表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. 题目表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                question_type TEXT NOT NULL,
                content TEXT NOT NULL,
                options TEXT,
                correct_answer TEXT NOT NULL,
                analysis TEXT,
                knowledge_points TEXT,
                difficulty INTEGER DEFAULT 3,
                score INTEGER NOT NULL,

                -- 溯源字段
                source_file TEXT NOT NULL,
                source_collection TEXT NOT NULL,
                source_snippet TEXT,
                source_hash TEXT,

                -- 状态
                status TEXT DEFAULT 'approved',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 2. 试卷表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                total_score INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                duration INTEGER DEFAULT 60,
                status TEXT DEFAULT 'published',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT
            )
        ''')

        # 3. 试卷题目关联表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exam_questions (
                exam_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                question_order INTEGER NOT NULL,
                PRIMARY KEY (exam_id, question_id),
                FOREIGN KEY (exam_id) REFERENCES exams(id),
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
        ''')

        # 4. 学生答卷表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS student_answers (
                id TEXT PRIMARY KEY,
                exam_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                student_name TEXT,
                question_id TEXT NOT NULL,
                question_type TEXT NOT NULL,
                student_answer TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                max_score INTEGER NOT NULL,
                feedback TEXT,
                score_details TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                graded_at TIMESTAMP,
                FOREIGN KEY (exam_id) REFERENCES exams(id),
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
        ''')

        # 5. 批阅报告表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS grade_reports (
                id TEXT PRIMARY KEY,
                exam_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                student_name TEXT,
                total_score INTEGER NOT NULL,
                max_score INTEGER NOT NULL,
                score_rate REAL,
                analysis TEXT,
                graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exam_id) REFERENCES exams(id)
            )
        ''')

        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source_file)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_student_answers_exam ON student_answers(exam_id, student_id)')

        conn.commit()
        conn.close()
        print(f"✓ 数据库初始化完成: {self.db_path}")

    # ==================== 题目管理 ====================

    def add_question(self, question: Dict, source_file: str, source_collection: str) -> str:
        """
        添加题目到数据库

        Args:
            question: 题目信息
            source_file: 来源文件路径
            source_collection: 来源向量库

        Returns:
            题目ID
        """
        question_id = question.get('id') or str(uuid.uuid4())

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO questions
            (id, question_type, content, options, correct_answer, analysis,
             knowledge_points, difficulty, score, source_file, source_collection,
             source_snippet, source_hash, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            question_id,
            self._detect_question_type(question),
            question.get('content', ''),
            json.dumps(question.get('options', []), ensure_ascii=False) if question.get('options') else None,
            self._get_correct_answer(question),
            question.get('analysis', ''),
            json.dumps(question.get('knowledge_points', []), ensure_ascii=False),
            question.get('difficulty', 3),
            self._get_score(question),
            source_file,
            source_collection,
            json.dumps(question.get('sources', []), ensure_ascii=False),
            question.get('source_hash'),
            'approved',
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()
        return question_id

    def add_questions_batch(self, questions: List[Dict], source_file: str, source_collection: str) -> int:
        """批量添加题目"""
        count = 0
        for q in questions:
            self.add_question(q, source_file, source_collection)
            count += 1
        return count

    def get_question(self, question_id: str) -> Optional[Dict]:
        """获取单个题目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM questions WHERE id = ?', (question_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_question(row)
        return None

    def get_questions_by_file(self, source_file: str) -> List[Dict]:
        """根据来源文件获取题目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM questions WHERE source_file = ?', (source_file,))
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_question(row) for row in rows]

    def delete_questions_by_file(self, source_file: str) -> int:
        """删除指定文件的所有题目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('DELETE FROM questions WHERE source_file = ?', (source_file,))
        deleted = cursor.rowcount

        conn.commit()
        conn.close()
        return deleted

    def list_questions(self, question_type: str = None, limit: int = 100) -> List[Dict]:
        """列出题目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if question_type:
            cursor.execute(
                'SELECT * FROM questions WHERE question_type = ? ORDER BY created_at DESC LIMIT ?',
                (question_type, limit)
            )
        else:
            cursor.execute('SELECT * FROM questions ORDER BY created_at DESC LIMIT ?', (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_question(row) for row in rows]

    # ==================== 试卷管理 ====================

    def create_exam(self, name: str, question_ids: List[str], created_by: str = 'admin',
                    description: str = '', duration: int = 60) -> Dict:
        """
        创建试卷

        Args:
            name: 试卷名称
            question_ids: 题目ID列表
            created_by: 创建者
            description: 描述
            duration: 考试时长（分钟）

        Returns:
            试卷信息
        """
        exam_id = str(uuid.uuid4())

        # 计算总分和题目数
        questions = []
        total_score = 0
        for qid in question_ids:
            q = self.get_question(qid)
            if q:
                questions.append(q)
                total_score += q['score']

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 插入试卷
        cursor.execute('''
            INSERT INTO exams (id, name, description, total_score, total_count, duration, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (exam_id, name, description, total_score, len(questions), duration, 'published', created_by))

        # 关联题目
        for order, qid in enumerate(question_ids):
            cursor.execute('''
                INSERT INTO exam_questions (exam_id, question_id, question_order)
                VALUES (?, ?, ?)
            ''', (exam_id, qid, order))

        conn.commit()
        conn.close()

        return {
            'id': exam_id,
            'name': name,
            'total_score': total_score,
            'total_count': len(questions),
            'duration': duration,
            'question_ids': question_ids
        }

    def get_exam(self, exam_id: str) -> Optional[Dict]:
        """获取试卷详情"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM exams WHERE id = ?', (exam_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        exam = {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'total_score': row[3],
            'total_count': row[4],
            'duration': row[5],
            'status': row[6],
            'created_at': row[7],
            'created_by': row[8]
        }

        # 获取关联的题目
        cursor.execute('''
            SELECT question_id FROM exam_questions
            WHERE exam_id = ? ORDER BY question_order
        ''', (exam_id,))

        question_ids = [r[0] for r in cursor.fetchall()]
        exam['question_ids'] = question_ids
        exam['questions'] = [self.get_question(qid) for qid in question_ids]

        conn.close()
        return exam

    def list_exams(self, limit: int = 20) -> List[Dict]:
        """列出试卷"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, total_score, total_count, status, created_at
            FROM exams ORDER BY created_at DESC LIMIT ?
        ''', (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [{
            'id': r[0],
            'name': r[1],
            'total_score': r[2],
            'total_count': r[3],
            'status': r[4],
            'created_at': r[5]
        } for r in rows]

    # ==================== 批卷功能 ====================

    def submit_answer(self, exam_id: str, student_id: str, question_id: str,
                      student_answer: str, student_name: str = '') -> str:
        """
        提交学生答案

        Returns:
            答案记录ID
        """
        answer_id = str(uuid.uuid4())

        # 获取题目信息
        question = self.get_question(question_id)
        if not question:
            raise ValueError(f"题目不存在: {question_id}")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO student_answers
            (id, exam_id, student_id, student_name, question_id, question_type,
             student_answer, max_score, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            answer_id, exam_id, student_id, student_name, question_id,
            question['question_type'], student_answer, question['score'],
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        return answer_id

    def grade_answer(self, answer_id: str, score: int, feedback: str,
                     score_details: Dict = None) -> Dict:
        """
        批阅单个答案

        Args:
            answer_id: 答案ID
            score: 得分
            feedback: 反馈
            score_details: 评分详情

        Returns:
            批阅结果
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE student_answers
            SET score = ?, feedback = ?, score_details = ?, graded_at = ?
            WHERE id = ?
        ''', (
            score, feedback,
            json.dumps(score_details, ensure_ascii=False) if score_details else None,
            datetime.now().isoformat(), answer_id
        ))

        conn.commit()
        conn.close()

        return {
            'answer_id': answer_id,
            'score': score,
            'feedback': feedback
        }

    def get_student_answers(self, exam_id: str, student_id: str) -> List[Dict]:
        """获取学生的答卷"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM student_answers
            WHERE exam_id = ? AND student_id = ?
        ''', (exam_id, student_id))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_answer(row) for row in rows]

    def generate_grade_report(self, exam_id: str, student_id: str, student_name: str = '') -> Dict:
        """
        生成批阅报告

        Args:
            exam_id: 试卷ID
            student_id: 学生ID
            student_name: 学生姓名

        Returns:
            批阅报告
        """
        # 获取学生答案
        answers = self.get_student_answers(exam_id, student_id)

        if not answers:
            return {'error': '没有找到学生答案'}

        # 计算总分
        total_score = sum(a['score'] for a in answers)
        max_score = sum(a['max_score'] for a in answers)
        score_rate = round(total_score / max_score * 100, 2) if max_score > 0 else 0

        # 生成报告
        report_id = str(uuid.uuid4())

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO grade_reports
            (id, exam_id, student_id, student_name, total_score, max_score, score_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (report_id, exam_id, student_id, student_name, total_score, max_score, score_rate))

        conn.commit()
        conn.close()

        return {
            'report_id': report_id,
            'exam_id': exam_id,
            'student_id': student_id,
            'student_name': student_name,
            'total_score': total_score,
            'max_score': max_score,
            'score_rate': score_rate,
            'answers': answers,
            'graded_at': datetime.now().isoformat()
        }

    # ==================== 工具方法 ====================

    def _detect_question_type(self, question: Dict) -> str:
        """检测题型"""
        if 'options' in question and question['options']:
            return 'choice'
        elif 'reference_answer' in question:
            return 'short_answer'
        else:
            return 'blank'

    def _get_correct_answer(self, question: Dict) -> str:
        """获取正确答案（统一为字符串）"""
        if 'reference_answer' in question:
            return json.dumps(question['reference_answer'], ensure_ascii=False)
        return question.get('answer', '')

    def _get_score(self, question: Dict) -> int:
        """获取分值"""
        if 'score' in question:
            return question['score']
        if 'reference_answer' in question:
            return question['reference_answer'].get('total_score', 10)
        return 2  # 默认选择题2分

    def _row_to_question(self, row) -> Dict:
        """数据库行转题目字典"""
        return {
            'id': row[0],
            'question_type': row[1],
            'content': row[2],
            'options': json.loads(row[3]) if row[3] else [],
            'correct_answer': row[4],
            'analysis': row[5],
            'knowledge_points': json.loads(row[6]) if row[6] else [],
            'difficulty': row[7],
            'score': row[8],
            'source_file': row[9],
            'source_collection': row[10],
            'source_snippet': json.loads(row[11]) if row[11] else [],
            'source_hash': row[12],
            'status': row[13],
            'created_at': row[14],
            'created_by': row[15]
        }

    def _row_to_answer(self, row) -> Dict:
        """数据库行转答案字典"""
        return {
            'id': row[0],
            'exam_id': row[1],
            'student_id': row[2],
            'student_name': row[3],
            'question_id': row[4],
            'question_type': row[5],
            'student_answer': row[6],
            'score': row[7],
            'max_score': row[8],
            'feedback': row[9],
            'score_details': json.loads(row[10]) if row[10] else {},
            'submitted_at': row[11],
            'graded_at': row[12]
        }

    # ==================== 统计功能 ====================

    def get_stats(self) -> Dict:
        """获取数据库统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        cursor.execute('SELECT COUNT(*) FROM questions')
        stats['total_questions'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM exams')
        stats['total_exams'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM student_answers')
        stats['total_answers'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM grade_reports')
        stats['total_reports'] = cursor.fetchone()[0]

        # 按题型统计
        cursor.execute('SELECT question_type, COUNT(*) FROM questions GROUP BY question_type')
        stats['by_type'] = dict(cursor.fetchall())

        # 按来源文件统计
        cursor.execute('SELECT source_file, COUNT(*) FROM questions GROUP BY source_file')
        stats['by_source'] = dict(cursor.fetchall())

        conn.close()
        return stats

    def clear_all(self):
        """清空所有数据（慎用）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('DELETE FROM grade_reports')
        cursor.execute('DELETE FROM student_answers')
        cursor.execute('DELETE FROM exam_questions')
        cursor.execute('DELETE FROM exams')
        cursor.execute('DELETE FROM questions')

        conn.commit()
        conn.close()
        print("✓ 已清空所有数据")


# ==================== 命令行测试 ====================

if __name__ == '__main__':
    db = ExamLocalDB()

    print("\n" + "=" * 50)
    print("本地出题批卷数据库测试")
    print("=" * 50)

    # 显示统计
    stats = db.get_stats()
    print(f"\n当前统计:")
    print(f"  题目总数: {stats['total_questions']}")
    print(f"  试卷总数: {stats['total_exams']}")
    print(f"  答卷总数: {stats['total_answers']}")
    print(f"  报告总数: {stats['total_reports']}")

    if stats['by_type']:
        print(f"\n按题型统计:")
        for t, c in stats['by_type'].items():
            print(f"  {t}: {c}")

    if stats['by_source']:
        print(f"\n按来源文件统计:")
        for f, c in stats['by_source'].items():
            print(f"  {f}: {c}")

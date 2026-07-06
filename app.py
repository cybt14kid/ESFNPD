#!/usr/bin/env python3
"""题库答题系统 Flask 后端 API"""

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import sqlite3
import json
import os
import random
import uuid
from datetime import datetime, date

app = Flask(__name__)
CORS(app)

@app.after_request
def add_no_cache_headers(resp):
    """防止 HTML 页面被浏览器缓存，方便调试"""
    if resp.content_type and 'text/html' in resp.content_type:
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    return resp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'exam.db')

os.makedirs(DATA_DIR, exist_ok=True)


def get_db():
    return sqlite3.connect(DB_PATH)


def init_db():
    if not os.path.exists(DB_PATH):
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                topic TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                answer TEXT,
                explanation TEXT,
                image TEXT,
                topic_category TEXT DEFAULT '',
                topic_tags TEXT DEFAULT '[]',
                knowledge_points TEXT DEFAULT '[]'
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL,
                user_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                answered_at TEXT NOT NULL,
                session_id TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS wrong_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL,
                user_answer TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                created_at TEXT NOT NULL,
                review_count INTEGER DEFAULT 0,
                last_reviewed_at TEXT,
                first_seen_at TEXT,
                repeat_count INTEGER DEFAULT 1,
                mastered_at TEXT,
                postponed_until TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                total_answered INTEGER DEFAULT 0,
                correct_count INTEGER DEFAULT 0
            )
        ''')
        # 知识库表 (Step 1)
        c.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_code TEXT UNIQUE NOT NULL,
                category_name TEXT NOT NULL,
                parent_code TEXT,
                description TEXT,
                sort_order INTEGER DEFAULT 0
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS question_knowledge (
                question_id TEXT NOT NULL,
                knowledge_code TEXT NOT NULL,
                PRIMARY KEY (question_id, knowledge_code),
                FOREIGN KEY (question_id) REFERENCES questions(question_id) ON DELETE CASCADE
            )
        ''')
        conn.commit()
        conn.close()
        print("数据库初始化完成")


def upgrade_db():
    """为已存在的数据库添加新字段和表（幂等）"""
    conn = get_db()
    c = conn.cursor()
    # 检查 questions 表字段
    c.execute('PRAGMA table_info(questions)')
    existing_cols = [r[1] for r in c.fetchall()]
    new_cols = [
        ('topic_category', "TEXT DEFAULT ''"),
        ('topic_tags', "TEXT DEFAULT '[]'"),
        ('knowledge_points', "TEXT DEFAULT '[]'")
    ]
    for col_name, col_def in new_cols:
        if col_name not in existing_cols:
            try:
                c.execute(f'ALTER TABLE questions ADD COLUMN {col_name} {col_def}')
                print(f'  + questions.{col_name}')
            except Exception as e:
                print(f'  ! questions.{col_name}: {e}')

    # 检查 wrong_answers 表字段（Phase B 增强）
    c.execute('PRAGMA table_info(wrong_answers)')
    existing_wa = [r[1] for r in c.fetchall()]
    wa_cols = [
        ('first_seen_at', "TEXT"),
        ('repeat_count', "INTEGER DEFAULT 1"),
        ('mastered_at', "TEXT"),
        ('postponed_until', "TEXT")
    ]
    for col_name, col_def in wa_cols:
        if col_name not in existing_wa:
            try:
                c.execute(f'ALTER TABLE wrong_answers ADD COLUMN {col_name} {col_def}')
                print(f'  + wrong_answers.{col_name}')
            except Exception as e:
                print(f'  ! wrong_answers.{col_name}: {e}')

    # 创建知识库表 (IF NOT EXISTS)
    c.execute('''CREATE TABLE IF NOT EXISTS knowledge_meta (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_code TEXT UNIQUE NOT NULL,
        category_name TEXT NOT NULL,
        parent_code TEXT,
        description TEXT,
        sort_order INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS question_knowledge (
        question_id TEXT NOT NULL,
        knowledge_code TEXT NOT NULL,
        PRIMARY KEY (question_id, knowledge_code),
        FOREIGN KEY (question_id) REFERENCES questions(question_id) ON DELETE CASCADE
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_qk_knowledge ON question_knowledge(knowledge_code)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(topic_category)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_wrong_mastered ON wrong_answers(mastered_at)')
    conn.commit()
    conn.close()


@app.route('/')
@app.route('/exam.html')
def index():
    return send_file(os.path.join(BASE_DIR, 'exam.html'))


@app.route('/api/questions/random')
def get_random_questions():
    """随机获取题目"""
    count = request.args.get('count', 20, type=int)
    qtype = request.args.get('type', None)  # 选择题 / 案例分析
    topic = request.args.get('topic', None)
    difficulty = request.args.get('difficulty', None)

    conn = get_db()
    c = conn.cursor()

    sql = 'SELECT question_id, type, topic, topic_category, topic_tags, difficulty, question, options, image, answer FROM questions WHERE 1=1'
    params = []

    if qtype:
        sql += ' AND type = ?'
        params.append(qtype)
    if topic:
        sql += ' AND topic = ?'
        params.append(topic)
    if difficulty:
        sql += ' AND difficulty = ?'
        params.append(difficulty)

    sql += ' ORDER BY RANDOM() LIMIT ?'
    params.append(count)

    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()

    questions = []
    for row in rows:
        answer = row[9] or ''
        # 多空题：答案用逗号分隔，如 "A,C"
        blank_count = len(answer.split(',')) if answer and ',' in answer else 1
        # 解析 topic_tags (JSON 数组)
        try:
            topic_tags = json.loads(row[4]) if row[4] else []
        except (json.JSONDecodeError, TypeError):
            topic_tags = []
        questions.append({
            'question_id': row[0],
            'type': row[1],
            'topic': row[2],
            'topic_category': row[3] or '',
            'topic_tags': topic_tags,
            'difficulty': row[5],
            'question': row[6],
            'options': json.loads(row[7]) if row[7] else [],
            'image': row[8] or '',
            'blank_count': blank_count
        })

    return jsonify({
        'success': True,
        'questions': questions,
        'count': len(questions)
    })


@app.route('/api/questions/topics')
def get_topics():
    """获取所有topic列表"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT DISTINCT topic FROM questions ORDER BY topic')
    topics = [row[0] for row in c.fetchall()]
    conn.close()
    return jsonify({'success': True, 'topics': topics})


@app.route('/api/questions/submit', methods=['POST'])
def submit_answer():
    """提交答案"""
    data = request.json
    question_id = data.get('question_id')
    user_answer = data.get('answer')
    session_id = data.get('session_id', str(uuid.uuid4()))

    if not question_id or not user_answer:
        return jsonify({'success': False, 'message': '参数不完整'})

    conn = get_db()
    c = conn.cursor()

    # 查正确答案
    c.execute('SELECT answer, explanation FROM questions WHERE question_id = ?', (question_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': '题目不存在'})

    correct_answer = row[0]
    explanation = row[1] or ''

    # 多空题：比较各空是否一致（答案格式如 "A,C"）
    user_parts = [p.strip().upper() for p in user_answer.strip().upper().split(',')]
    correct_parts = [p.strip().upper() for p in correct_answer.strip().upper().split(',')]
    is_correct = 1 if user_parts == correct_parts else 0
    
    # 记录答题
    c.execute('''
        INSERT INTO user_answers (question_id, user_answer, is_correct, answered_at, session_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (question_id, user_answer, is_correct, datetime.now().isoformat(), session_id))
    
    # 更新错题本（Phase B 增强: 自动入库 + 跟踪生命周期）
    wrong_info = None
    if not is_correct:
        # 检查是否首次入错题本
        c.execute('SELECT id, first_seen_at, repeat_count FROM wrong_answers WHERE question_id = ?', (question_id,))
        existing = c.fetchone()
        is_first_time = existing is None
        now = datetime.now().isoformat()
        if is_first_time:
            c.execute('''
                INSERT INTO wrong_answers 
                (question_id, user_answer, correct_answer, created_at, first_seen_at, repeat_count, review_count, last_reviewed_at, mastered_at)
                VALUES (?, ?, ?, ?, ?, 1, 0, NULL, NULL)
                ON CONFLICT(question_id) DO UPDATE SET
                    user_answer = excluded.user_answer,
                    correct_answer = excluded.correct_answer,
                    created_at = excluded.created_at,
                    repeat_count = repeat_count + 1,
                    mastered_at = NULL
            ''', (question_id, user_answer, correct_answer, now, now))
        else:
            c.execute('''
                UPDATE wrong_answers
                SET user_answer = ?,
                    correct_answer = ?,
                    created_at = ?,
                    repeat_count = repeat_count + 1,
                    mastered_at = NULL
                WHERE question_id = ?
            ''', (user_answer, correct_answer, now, question_id))

        # 取最新错题信息
        c.execute('SELECT repeat_count, first_seen_at FROM wrong_answers WHERE question_id = ?', (question_id,))
        wrow = c.fetchone()
        wrong_info = {
            'is_first_time': is_first_time,
            'repeat_count': wrow[0] if wrow else 1,
            'first_seen_at': wrow[1] if wrow else now
        }

    # 答对且在错题本里 -> 标记已掌握 (Phase B)
    elif is_correct:
        c.execute('SELECT id, mastered_at FROM wrong_answers WHERE question_id = ?', (question_id,))
        existing = c.fetchone()
        if existing and not existing[1]:
            # 之前错过但还没掌握，现在答对了 -> 标记 mastered
            c.execute('UPDATE wrong_answers SET mastered_at = ? WHERE question_id = ?', (datetime.now().isoformat(), question_id))
    
    # 更新每日统计
    today = date.today().isoformat()
    c.execute('''
        INSERT INTO daily_stats (date, total_answered, correct_count)
        VALUES (?, 1, ?)
        ON CONFLICT(date) DO UPDATE SET
            total_answered = total_answered + 1,
            correct_count = correct_count + ?
    ''', (today, is_correct, is_correct))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'is_correct': bool(is_correct),
        'correct_answer': correct_answer,
        'explanation': explanation,
        'session_id': session_id,
        'wrong_info': wrong_info
    })


@app.route('/api/wrong')
def get_wrong():
    """获取错题本"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT w.question_id, w.user_answer, w.correct_answer, w.created_at,
               w.review_count, q.question, q.options, q.topic, q.difficulty, q.explanation,
               w.first_seen_at, w.repeat_count, w.mastered_at, w.postponed_until
        FROM wrong_answers w
        JOIN questions q ON w.question_id = q.question_id
        ORDER BY w.created_at DESC
    ''')
    rows = c.fetchall()
    conn.close()

    wrong_list = []
    for row in rows:
        wrong_list.append({
            'question_id': row[0],
            'your_answer': row[1],
            'correct_answer': row[2],
            'created_at': row[3],
            'review_count': row[4],
            'question': row[5],
            'options': json.loads(row[6]) if row[6] else [],
            'topic': row[7],
            'difficulty': row[8],
            'explanation': row[9] if len(row) > 9 else '',
            'first_seen_at': row[10] if len(row) > 10 else None,
            'repeat_count': row[11] if len(row) > 11 else 1,
            'mastered_at': row[12] if len(row) > 12 else None,
            'postponed_until': row[13] if len(row) > 13 else None,
            'is_mastered': bool(row[12]) if len(row) > 12 else False
        })

    return jsonify({'success': True, 'wrong_list': wrong_list})


@app.route('/api/stats/today')
def get_today_stats():
    """获取今日统计"""
    today = date.today().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT total_answered, correct_count FROM daily_stats WHERE date = ?', (today,))
    row = c.fetchone()
    conn.close()
    
    if row:
        total, correct = row
    else:
        total, correct = 0, 0
    
    return jsonify({
        'success': True,
        'date': today,
        'total_answered': total,
        'correct_count': correct,
        'accuracy': round(correct / total * 100, 1) if total > 0 else 0
    })


@app.route('/api/stats/overview')
def get_overview():
    """获取总览统计"""
    conn = get_db()
    c = conn.cursor()
    
    # 题目总数
    c.execute('SELECT COUNT(*) FROM questions')
    total_questions = c.fetchone()[0]
    
    # 已回答题目数
    c.execute('SELECT COUNT(DISTINCT question_id) FROM user_answers')
    answered_questions = c.fetchone()[0]
    
    # 错题数
    c.execute('SELECT COUNT(*) FROM wrong_answers')
    wrong_count = c.fetchone()[0]
    
    # 总正确率
    c.execute('SELECT SUM(correct_count), SUM(total_answered) FROM daily_stats')
    row = c.fetchone()
    total_correct = row[0] or 0
    total_answered = row[1] or 0
    
    conn.close()
    
    return jsonify({
        'success': True,
        'total_questions': total_questions,
        'answered_questions': answered_questions,
        'wrong_count': wrong_count,
        'accuracy': round(total_correct / total_answered * 100, 1) if total_answered > 0 else 0
    })


@app.route('/api/wrong/clear', methods=['POST'])
def clear_wrong():
    """清空调题本"""
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM wrong_answers')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': '错题本已清空'})


@app.route('/api/wrong/review', methods=['POST'])
def review_wrong():
    """复习错题（减少复习次数）"""
    data = request.json
    question_id = data.get('question_id')

    if not question_id:
        return jsonify({'success': False, 'message': '参数不完整'})

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE wrong_answers
        SET review_count = review_count + 1,
            last_reviewed_at = datetime('now')
        WHERE question_id = ?
    ''', (question_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True})


@app.route('/api/wrong/review-batch', methods=['GET'])
def wrong_review_batch():
    """获取复习批次 - Phase B

    返回需要今天复习的错题，按优先级排序:
    - 答错过 3 次以上 (高频错)
    - 从未复习过
    - 1 天前入错题本 (根据遗忘曲线)
    """
    conn = get_db()
    c = conn.cursor()
    limit = request.args.get('limit', 10, type=int)

    # 获取未掌握 + 需复习的题
    c.execute('''
        SELECT w.question_id, w.user_answer, w.correct_answer, w.created_at,
               w.first_seen_at, w.repeat_count, w.review_count, w.postponed_until,
               q.question, q.options, q.answer, q.explanation, q.type,
               q.difficulty, q.topic, q.topic_category, q.image
        FROM wrong_answers w
        JOIN questions q ON w.question_id = q.question_id
        WHERE w.mastered_at IS NULL
          AND (w.postponed_until IS NULL OR w.postponed_until < datetime('now'))
        ORDER BY
          CASE WHEN w.review_count = 0 THEN 0 ELSE 1 END,
          w.repeat_count DESC,
          w.created_at ASC
        LIMIT ?
    ''', (limit,))
    rows = c.fetchall()

    items = []
    for r in rows:
        # 解析 options
        try:
            opts = json.loads(r[9]) if r[9] else []
            if opts and isinstance(opts[0], str) and len(opts[0]) > 1 and opts[0][1] == '.':
                opts = [{'key': chr(65 + i), 'value': v[2:].strip() if len(v) > 2 else v} for i, v in enumerate(opts)]
        except (json.JSONDecodeError, TypeError):
            opts = []

        # 计算优先级
        priority = 0
        priority_label = ''
        if r[6] == 0:  # 从未复习
            priority = 0
            priority_label = '从未复习'
        elif r[5] >= 3:  # 错 3 次以上
            priority = 1
            priority_label = '高频错'
        else:
            priority = 2
            priority_label = '普通复习'

        items.append({
            'question_id': r[0],
            'question': r[8],
            'options': opts,
            'answer': r[10],
            'explanation': r[11] or '',
            'type': r[12] or '选择题',
            'difficulty': r[13] or '',
            'topic': r[14] or '',
            'topic_category': r[15] or '',
            'image': r[16] or '',
            'wrong_info': {
                'user_answer': r[1],
                'correct_answer': r[2],
                'first_wrong_at': r[4],
                'last_wrong_at': r[3],
                'repeat_count': r[5],
                'review_count': r[6],
                'priority': priority,
                'priority_label': priority_label
            }
        })

    # 统计
    c.execute('SELECT COUNT(*) FROM wrong_answers WHERE mastered_at IS NULL')
    total_pending = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM wrong_answers WHERE mastered_at IS NOT NULL')
    total_mastered = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM wrong_answers WHERE repeat_count >= 3 AND mastered_at IS NULL')
    high_freq = c.fetchone()[0]

    conn.close()
    return jsonify({
        'success': True,
        'batch': items,
        'count': len(items),
        'stats': {
            'total_pending': total_pending,
            'total_mastered': total_mastered,
            'high_freq': high_freq,
            'returned': len(items)
        }
    })


@app.route('/api/wrong/postpone', methods=['POST'])
def wrong_postpone():
    """推迟错题复习 - Phase B

    Body: { question_id, days: int }
    """
    data = request.json or {}
    question_id = data.get('question_id')
    days = data.get('days', 3)

    if not question_id:
        return jsonify({'success': False, 'message': 'question_id 必填'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE wrong_answers
        SET postponed_until = datetime('now', '+' || ? || ' days')
        WHERE question_id = ?
    ''', (str(days), question_id))
    conn.commit()
    conn.close()
    return jsonify({
        'success': True,
        'message': '已推迟 ' + str(days) + ' 天',
        'question_id': question_id
    })


@app.route('/api/wrong/stats', methods=['GET'])
def wrong_stats_lifecycle():
    """错题生命周期统计 - Phase B"""
    conn = get_db()
    c = conn.cursor()

    # 总体
    c.execute('SELECT COUNT(*), SUM(repeat_count), SUM(review_count) FROM wrong_answers')
    row = c.fetchone()
    total = row[0] or 0
    total_repeats = row[1] or 0
    total_reviews = row[2] or 0

    # 未掌握
    c.execute('SELECT COUNT(*) FROM wrong_answers WHERE mastered_at IS NULL')
    pending = c.fetchone()[0]

    # 已掌握
    c.execute('SELECT COUNT(*) FROM wrong_answers WHERE mastered_at IS NOT NULL')
    mastered = c.fetchone()[0]

    # 高频错 (>=3 次)
    c.execute('SELECT COUNT(*) FROM wrong_answers WHERE repeat_count >= 3 AND mastered_at IS NULL')
    high_freq = c.fetchone()[0]

    # 推迟中
    c.execute("SELECT COUNT(*) FROM wrong_answers WHERE postponed_until > datetime('now') AND mastered_at IS NULL")
    postponed = c.fetchone()[0]

    # 最近 7 天新增错题
    c.execute("SELECT COUNT(*) FROM wrong_answers WHERE first_seen_at > datetime('now', '-7 days')")
    new_7d = c.fetchone()[0]

    conn.close()
    return jsonify({
        'success': True,
        'total': total,
        'pending': pending,
        'mastered': mastered,
        'high_freq': high_freq,
        'postponed': postponed,
        'total_repeats': total_repeats,
        'total_reviews': total_reviews,
        'new_7d': new_7d,
        'mastered_percent': round(mastered * 100 / total, 1) if total else 0
    })


@app.route('/api/wrong/auto-mastered', methods=['POST'])
def wrong_auto_mastered():
    """标记错题已掌握（从错题本移除）- Phase B

    Body: { question_id }
    """
    data = request.json or {}
    question_id = data.get('question_id')

    if not question_id:
        return jsonify({'success': False, 'message': 'question_id 必填'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE wrong_answers
        SET mastered_at = ?,
            last_reviewed_at = ?
        WHERE question_id = ?
    ''', (datetime.now().isoformat(), datetime.now().isoformat(), question_id))
    affected = c.rowcount
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'affected': affected,
        'message': '已标记掌握' if affected else '未在错题本中'
    })


@app.route('/api/wrong/auto-trigger-ai', methods=['POST'])
def wrong_auto_trigger_ai():
    """错题自动触发 AI 生成同类题 - Phase B

    Body: { question_id, count: int (默认1) }
    """
    data = request.json or {}
    question_id = data.get('question_id')
    count = data.get('count', 1)

    if not question_id:
        return jsonify({'success': False, 'message': 'question_id 必填'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT question, type, topic, topic_category, difficulty, options, answer, explanation
        FROM questions WHERE question_id = ?
    ''', (question_id,))
    q = c.fetchone()
    conn.close()

    if not q:
        return jsonify({'success': False, 'message': '题目不存在'}), 404

    # 用 LLM 生成同类题
    try:
        samples = [{
            'question': q[0],
            'options': q[5],
            'answer': q[6],
            'explanation': q[7] or ''
        }]
        prompt = _build_llm_prompt(q[3] or '', q[4] or '中等', count, q[2] or '', samples)
        text, usage = _call_minimax(prompt, max_tokens=2000)
        questions = _parse_llm_questions(text, count)

        if not questions:
            return jsonify({'success': False, 'error': 'LLM 未返回有效题目'}), 500

        # 标记这些是 AI 生成的错题变体
        generated = []
        for i, gen_q in enumerate(questions):
            generated.append({
                'question': gen_q['question'],
                'options': gen_q['options'],
                'answer': gen_q['answer'],
                'explanation': gen_q['explanation'],
                'generated_for': question_id,
                'usage': usage
            })
        return jsonify({
            'success': True,
            'count': len(generated),
            'questions': generated,
            'based_on': question_id,
            'note': '这些题已生成，但未自动入库。需要手动调用 /api/kb/import-generated 入库'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'LLM 调用失败: ' + str(e)
        }), 500


# ==================== 论文章节 ====================

ESSAYS_DIR = os.path.join(BASE_DIR, 'questions', 'essays')
PROJECTS_DIR = os.path.join(ESSAYS_DIR, 'projects')
ESSAY_FILES_DIR = os.path.join(ESSAYS_DIR, 'essays')


def _read_md(path):
    """安全读取 markdown 文件"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return None


@app.route('/essay-api/project/<project_id>')
def get_project(project_id):
    """获取项目背景素材"""
    # 防止路径遍历
    safe_id = ''.join(c for c in project_id if c.isalnum() or c == '-')
    file_path = os.path.join(PROJECTS_DIR, f'{safe_id}.md')
    content = _read_md(file_path)
    if not content:
        return jsonify({'success': False, 'error': '项目不存在'}), 404
    
    # 提取标题（第一行 ## xxx）
    import re
    m = re.search(r'^## (.+)$', content, re.MULTILINE)
    title = m.group(1).strip() if m else project_id
    
    return jsonify({
        'success': True,
        'id': project_id,
        'title': title,
        'content': content
    })


@app.route('/essay-api/essay/<essay_id>')
def get_essay(essay_id):
    """获取论文范文"""
    safe_id = ''.join(c for c in essay_id if c.isalnum() or c == '-')
    file_path = os.path.join(ESSAY_FILES_DIR, f'{safe_id}.md')
    content = _read_md(file_path)
    if not content:
        return jsonify({'success': False, 'error': '范文不存在'}), 404
    
    return jsonify({
        'success': True,
        'id': essay_id,
        'content': content
    })


@app.route('/essay-api/hot-topics')
def get_hot_topics():
    """获取 2025-2026 热点技术详细文档"""
    file_path = os.path.join(ESSAYS_DIR, 'hot-topics-2025-2026.md')
    content = _read_md(file_path)
    if not content:
        return jsonify({'success': False, 'error': '热点文档不存在'}), 404
    
    # 解析为结构化数据：按 ## 切分
    import re
    sections = []
    parts = re.split(r'\n## ', content)
    # 第一个 part 是标题，跳过
    for part in parts[1:]:
        lines = part.split('\n', 1)
        if len(lines) >= 1:
            title = lines[0].strip()
            body = lines[1] if len(lines) > 1 else ''
            sections.append({
                'title': title,
                'content': body.strip()
            })
    
    return jsonify({
        'success': True,
        'total': len(sections),
        'sections': sections
    })


@app.route('/essay-api/list')
def list_essays():
    """列出所有项目和范文"""
    projects = []
    if os.path.exists(PROJECTS_DIR):
        for f in os.listdir(PROJECTS_DIR):
            if f.endswith('.md'):
                projects.append(f.replace('.md', ''))
    
    essays = []
    if os.path.exists(ESSAY_FILES_DIR):
        for f in os.listdir(ESSAY_FILES_DIR):
            if f.endswith('.md'):
                essays.append(f.replace('.md', ''))
    
    return jsonify({
        'success': True,
        'projects': projects,
        'essays': essays
    })


@app.route('/essay.html')
def essay_page():
    """论文页面"""
    return send_file(os.path.join(BASE_DIR, 'essay.html'))


@app.route('/kb.html')
def kb_page():
    """知识库可视化页面"""
    return send_file(os.path.join(BASE_DIR, 'kb.html'))


# ============================================================
# 知识库 API (Step 1-B)
# ============================================================

@app.route('/api/kb/categories')
def kb_categories():
    """获取所有知识点一级分类"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT m.category_code, m.category_name, m.description, m.sort_order,
               COUNT(DISTINCT q.id) as question_count
        FROM knowledge_meta m
        LEFT JOIN questions q ON q.topic_category = m.category_name
        GROUP BY m.category_code
        ORDER BY m.sort_order
    ''')
    rows = c.fetchall()
    conn.close()
    categories = []
    for r in rows:
        categories.append({
            'code': r[0],
            'name': r[1],
            'description': r[2] or '',
            'sort_order': r[3],
            'question_count': r[4]
        })
    return jsonify({'success': True, 'categories': categories, 'total': len(categories)})


@app.route('/api/kb/category/<code>')
def kb_category_detail(code):
    """获取某个分类下的所有题目"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT category_name FROM knowledge_meta WHERE category_code = ?', (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': '分类不存在'}), 404
    category_name = row[0]
    c.execute('''
        SELECT question_id, type, topic, topic_category, topic_tags, difficulty, question
        FROM questions
        WHERE topic_category = ?
        ORDER BY type, difficulty, question_id
    ''', (category_name,))
    rows = c.fetchall()
    conn.close()
    questions = []
    for r in rows:
        try:
            tags = json.loads(r[4]) if r[4] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        questions.append({
            'question_id': r[0],
            'type': r[1],
            'topic': r[2],
            'topic_category': r[3],
            'topic_tags': tags,
            'difficulty': r[5],
            'question': r[6]
        })
    return jsonify({
        'success': True,
        'category': {'code': code, 'name': category_name},
        'questions': questions,
        'total': len(questions)
    })


@app.route('/api/kb/stats')
def kb_stats():
    """知识库统计信息"""
    conn = get_db()
    c = conn.cursor()
    # 总题数
    c.execute('SELECT COUNT(*) FROM questions')
    total = c.fetchone()[0]
    # 已分类数
    c.execute("SELECT COUNT(*) FROM questions WHERE topic_category != ''")
    tagged = c.fetchone()[0]
    # 一级分类数
    c.execute('SELECT COUNT(*) FROM knowledge_meta')
    categories = c.fetchone()[0]
    # 关联数
    c.execute('SELECT COUNT(*) FROM question_knowledge')
    links = c.fetchone()[0]
    # 难度分布
    c.execute("SELECT difficulty, COUNT(*) FROM questions GROUP BY difficulty")
    difficulties = {r[0]: r[1] for r in c.fetchall()}
    # 刷题统计
    c.execute('SELECT COUNT(*) FROM user_answers')
    answered = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM wrong_answers')
    wrong = c.fetchone()[0]
    conn.close()
    return jsonify({
        'success': True,
        'stats': {
            'total_questions': total,
            'tagged_questions': tagged,
            'tagged_percent': round(tagged * 100 / total, 1) if total else 0,
            'categories': categories,
            'knowledge_links': links,
            'difficulties': difficulties,
            'answered_count': answered,
            'wrong_count': wrong
        }
    })


@app.route('/api/kb/search')
def kb_search():
    """知识库搜索 - 关键词检索题目和知识点"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'success': False, 'error': '请提供搜索关键词'}), 400
    conn = get_db()
    c = conn.cursor()
    like_q = '%' + q + '%'
    c.execute('''
        SELECT question_id, type, topic, topic_category, topic_tags, difficulty, question
        FROM questions
        WHERE question LIKE ? OR topic LIKE ? OR topic_category LIKE ? OR explanation LIKE ?
        ORDER BY difficulty, question_id
        LIMIT 50
    ''', (like_q, like_q, like_q, like_q))
    rows = c.fetchall()
    conn.close()
    results = []
    for r in rows:
        try:
            tags = json.loads(r[4]) if r[4] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        results.append({
            'question_id': r[0],
            'type': r[1],
            'topic': r[2],
            'topic_category': r[3],
            'topic_tags': tags,
            'difficulty': r[5],
            'question': r[6]
        })
    return jsonify({'success': True, 'query': q, 'results': results, 'total': len(results)})


@app.route('/api/kb/weak-points')
def kb_weak_points():
    """薄弱点分析 - L2 Phase 1

    分析逻辑:
    1. 按 topic_category 统计答题数据
    2. 计算每分类正确率
    3. 按正确率排序
    4. 标注薄弱等级：
       - correct_count >= 3 且 accuracy < 50: high (严重薄弱)
       - correct_count >= 3 且 accuracy < 70: medium (需提高)
       - accuracy >= 70: ok (掌握良好)
    5. 推荐复习题: 取该分类下未答题或答错过的题
    """
    min_count = request.args.get('min_count', 3, type=int)  # 最小答题数
    top_n = request.args.get('top_n', 5, type=int)  # 返回 top N

    conn = get_db()
    c = conn.cursor()

    # 1. 总体统计
    c.execute('SELECT COUNT(*) FROM user_answers')
    total_answered = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM user_answers WHERE is_correct = 1')
    total_correct = c.fetchone()[0]
    overall_acc = round(total_correct * 100 / total_answered, 1) if total_answered else 0

    # 2. 按分类统计
    # 关联 user_answers -> questions -> topic_category
    c.execute('''
        SELECT
            q.topic_category,
            COUNT(ua.id) as answered_count,
            SUM(CASE WHEN ua.is_correct = 1 THEN 1 ELSE 0 END) as correct_count
        FROM user_answers ua
        JOIN questions q ON ua.question_id = q.question_id
        WHERE q.topic_category != ''
        GROUP BY q.topic_category
        ORDER BY 3 DESC
    ''')
    category_stats = c.fetchall()

    # 3. 错题统计
    c.execute('''
        SELECT q.topic_category, COUNT(*) as wrong_count
        FROM wrong_answers w
        JOIN questions q ON w.question_id = q.question_id
        WHERE q.topic_category != ''
        GROUP BY q.topic_category
    ''')
    wrong_by_cat = {r[0]: r[1] for r in c.fetchall()}

    # 4. 构建分析结果
    weak_points = []
    for cat_name, answered, correct in category_stats:
        if answered < min_count:
            continue
        accuracy = round(correct * 100 / answered, 1)
        if accuracy < 50:
            severity = 'high'
            severity_label = '严重薄弱'
        elif accuracy < 70:
            severity = 'medium'
            severity_label = '需提高'
        else:
            severity = 'low'
            severity_label = '掌握良好'

        # 取分类代码
        c.execute('SELECT category_code FROM knowledge_meta WHERE category_name = ?', (cat_name,))
        code_row = c.fetchone()
        code = code_row[0] if code_row else ''

        # 推荐复习题: 该分类下答错过的题 + 未答过的题，随机 5 道
        c.execute('''
            SELECT q.question_id, q.type, q.difficulty, q.question,
                   (CASE WHEN EXISTS(SELECT 1 FROM wrong_answers wa WHERE wa.question_id = q.question_id) THEN 1 ELSE 0 END) as is_wrong,
                   (CASE WHEN EXISTS(SELECT 1 FROM user_answers ua2 WHERE ua2.question_id = q.question_id) THEN 1 ELSE 0 END) as is_answered
            FROM questions q
            WHERE q.topic_category = ?
            ORDER BY is_wrong DESC, is_answered ASC, RANDOM()
            LIMIT 5
        ''', (cat_name,))
        recommended = []
        for r in c.fetchall():
            recommended.append({
                'question_id': r[0],
                'type': r[1],
                'difficulty': r[2],
                'question': r[3][:80] + ('...' if len(r[3]) > 80 else ''),
                'is_wrong': bool(r[4]),
                'is_answered': bool(r[5])
            })

        weak_points.append({
            'category_code': code,
            'category_name': cat_name,
            'answered_count': answered,
            'correct_count': correct,
            'accuracy': accuracy,
            'wrong_count': wrong_by_cat.get(cat_name, 0),
            'severity': severity,
            'severity_label': severity_label,
            'recommended_questions': recommended
        })

    # 按严重程度 + 正确率排序
    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    weak_points.sort(key=lambda x: (severity_order[x['severity']], x['accuracy']))

    # 5. 智能建议
    high_count = sum(1 for w in weak_points if w['severity'] == 'high')
    medium_count = sum(1 for w in weak_points if w['severity'] == 'medium')
    suggestions = []
    if high_count > 0:
        suggestions.append(f'你有 {high_count} 个严重薄弱点，建议本周专攻')
    if medium_count > 0:
        suggestions.append(f'{medium_count} 个分类需提高，建议分散复习')
    if not weak_points:
        suggestions.append('答题数据不足，快去刷题吧')
    elif all(w['severity'] == 'low' for w in weak_points):
        suggestions.append('所有分类都掌握良好，可以挑战更难题目')

    conn.close()
    return jsonify({
        'success': True,
        'overall': {
            'total_answered': total_answered,
            'total_correct': total_correct,
            'overall_accuracy': overall_acc
        },
        'weak_points': weak_points,
        'top_weak': weak_points[:top_n],
        'suggestions': suggestions,
        'min_count_threshold': min_count
    })


@app.route('/api/kb/learning-path')
def kb_learning_path():
    """学习路径推荐 - L2 Phase 1.5

    根据薄弱点生成 7 天学习计划
    """
    conn = get_db()
    c = conn.cursor()

    # 取 top 7 薄弱点 (覆盖一周 7 天)
    weak_req = '/api/kb/weak-points?min_count=3&top_n=7'
    with app.test_request_context(weak_req):
        weak_resp = kb_weak_points()
        weak_data = weak_resp.get_json()

    top_weak = weak_data.get('top_weak', [])
    if not top_weak:
        conn.close()
        return jsonify({'success': False, 'message': '答题数据不足，无法生成学习路径'})

    plan = []
    days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    questions_per_day = 10

    for i, day in enumerate(days):
        # 跨薄弱点循环，超出后从头开始
        target = top_weak[i % len(top_weak)]
        rec_qs = target.get('recommended_questions', [])
        plan.append({
            'day': day,
            'category': target['category_name'],
            'target_count': questions_per_day,
            'focus': '补强 ' + target['severity_label'] + ' 知识点',
            'question_ids': [q['question_id'] for q in rec_qs[:questions_per_day]],
            'tips': '先看错题解析，再做新题'
        })

    conn.close()
    return jsonify({
        'success': True,
        'plan': plan,
        'generated_at': datetime.now().isoformat(),
        'based_on_weak_points': len(top_weak)
    })


@app.route('/api/kb/diagnose/<question_id>')
def kb_diagnose(question_id):
    """错题诊断 - L2 Phase 2

    给定一道题，返回:
    - 题目详情
    - 在该知识点下的统计（用户答过几次，错几次）
    - 关联知识点
    - 类似题目推荐
    """
    conn = get_db()
    c = conn.cursor()

    # 1. 题目详情
    c.execute('''
        SELECT question_id, type, topic, topic_category, topic_tags, difficulty,
               question, options, answer, explanation, image
        FROM questions WHERE question_id = ?
    ''', (question_id,))
    q = c.fetchone()
    if not q:
        conn.close()
        return jsonify({'success': False, 'error': '题目不存在'}), 404

    try:
        tags = json.loads(q[4]) if q[4] else []
    except (json.JSONDecodeError, TypeError):
        tags = []

    options = json.loads(q[7]) if q[7] else []
    try:
        opts_list = [json.loads(o) for o in options]
    except (json.JSONDecodeError, TypeError):
        opts_list = options

    question = {
        'question_id': q[0],
        'type': q[1],
        'topic': q[2],
        'topic_category': q[3],
        'topic_tags': tags,
        'difficulty': q[5],
        'question': q[6],
        'options': opts_list,
        'answer': q[8],
        'explanation': q[9] or '',
        'image': q[10] or ''
    }

    # 2. 用户在该题的答题历史
    c.execute('''
        SELECT user_answer, is_correct, answered_at, session_id
        FROM user_answers WHERE question_id = ?
        ORDER BY answered_at DESC
    ''', (question_id,))
    history = []
    for r in c.fetchall():
        history.append({
            'user_answer': r[0],
            'is_correct': bool(r[1]),
            'answered_at': r[2],
            'session_id': r[3]
        })

    # 3. 该题是否在错题本
    c.execute('''
        SELECT user_answer, correct_answer, created_at, review_count
        FROM wrong_answers WHERE question_id = ?
    ''', (question_id,))
    wrong_record = c.fetchone()
    wrong_info = None
    if wrong_record:
        wrong_info = {
            'user_answer': wrong_record[0],
            'correct_answer': wrong_record[1],
            'created_at': wrong_record[2],
            'review_count': wrong_record[3]
        }

    # 4. 该分类下的整体表现
    category_name = q[3]
    c.execute('''
        SELECT
            COUNT(*),
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END)
        FROM user_answers ua
        JOIN questions qs ON ua.question_id = qs.question_id
        WHERE qs.topic_category = ?
    ''', (category_name,))
    cat_row = c.fetchone()
    cat_total = cat_row[0] if cat_row[0] else 0
    cat_correct = cat_row[1] or 0
    cat_accuracy = round(cat_correct * 100 / cat_total, 1) if cat_total else 0

    # 5. 同分类的类似题目 (同 type + 同难度)
    c.execute('''
        SELECT question_id, difficulty, question
        FROM questions
        WHERE topic_category = ? AND question_id != ? AND type = ? AND difficulty = ?
        ORDER BY RANDOM() LIMIT 5
    ''', (category_name, question_id, q[1], q[5]))
    similar = []
    for r in c.fetchall():
        similar.append({
            'question_id': r[0],
            'difficulty': r[1],
            'question': r[2][:60] + ('...' if len(r[2]) > 60 else '')
        })

    # 6. 该题未答对过则生成诊断提示
    diagnosis = {
        'severity': 'high' if not history or all(not h['is_correct'] for h in history) else 'medium' if any(not h['is_correct'] for h in history) else 'low',
        'message': '',
        'actionable': []
    }
    if wrong_info:
        diagnosis['message'] = f'这道题你答错过 (你的答案: {wrong_info["user_answer"]}, 正确答案: {wrong_info["correct_answer"]})'
        diagnosis['actionable'].append('重新解答一遍，看是否掌握')
    if cat_total >= 3 and cat_accuracy < 60:
        diagnosis['message'] += f'。在「{category_name}」分类下你的正确率仅 {cat_accuracy}%'
        diagnosis['actionable'].append(f'建议复习 {category_name} 相关知识点')
    if history and history[0]['is_correct']:
        diagnosis['message'] = '最近你已答对，这道题掌握了'
        diagnosis['actionable'].append('可以挑战同类难题')

    conn.close()
    return jsonify({
        'success': True,
        'question': question,
        'history': {
            'attempts': len(history),
            'is_currently_correct': history[0]['is_correct'] if history else None,
            'records': history[:5]  # 最近 5 次
        },
        'wrong_record': wrong_info,
        'category_performance': {
            'category': category_name,
            'total_attempts': cat_total,
            'correct': cat_correct,
            'accuracy': cat_accuracy
        },
        'similar_questions': similar,
        'diagnosis': diagnosis,
        'tags': tags
    })


# ============================================================
# Phase 2: 错题诊断增强
# ============================================================

@app.route('/api/kb/wrong-stats')
def kb_wrong_stats():
    """错题详细统计"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*), SUM(review_count) FROM wrong_answers')
    row = c.fetchone()
    total_wrong = row[0] or 0
    total_reviews = row[1] or 0

    c.execute('''
        SELECT q.topic_category, COUNT(*) as cnt
        FROM wrong_answers w JOIN questions q ON w.question_id = q.question_id
        WHERE q.topic_category != '' GROUP BY q.topic_category ORDER BY cnt DESC
    ''')
    by_category = []
    for r in c.fetchall():
        by_category.append({
            'category': r[0],
            'wrong_count': r[1],
            'percentage': round(r[1] * 100 / total_wrong, 1) if total_wrong else 0
        })

    c.execute('''
        SELECT q.difficulty, COUNT(*) FROM wrong_answers w
        JOIN questions q ON w.question_id = q.question_id GROUP BY q.difficulty ORDER BY 2 DESC
    ''')
    by_difficulty = [{'difficulty': r[0] or '未知', 'wrong_count': r[1],
                       'percentage': round(r[1] * 100 / total_wrong, 1) if total_wrong else 0} for r in c.fetchall()]

    c.execute('''
        SELECT q.type, COUNT(*) FROM wrong_answers w
        JOIN questions q ON w.question_id = q.question_id GROUP BY q.type ORDER BY 2 DESC
    ''')
    by_type = [{'type': r[0], 'wrong_count': r[1],
                'percentage': round(r[1] * 100 / total_wrong, 1) if total_wrong else 0} for r in c.fetchall()]

    c.execute("SELECT COUNT(*) FROM wrong_answers WHERE created_at > datetime('now', '-7 days')")
    recent_7d = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM wrong_answers WHERE created_at > datetime('now', '-30 days') AND created_at <= datetime('now', '-7 days')")
    recent_8_30d = c.fetchone()[0]
    by_time = [
        {'period': '最近 7 天', 'wrong_count': recent_7d},
        {'period': '8-30 天前', 'wrong_count': recent_8_30d},
        {'period': '更早', 'wrong_count': max(0, total_wrong - recent_7d - recent_8_30d)}
    ]

    c.execute('''
        SELECT question_id, COUNT(*) as cnt FROM user_answers WHERE is_correct = 0
        GROUP BY question_id HAVING cnt >= 2 ORDER BY cnt DESC
    ''')
    recurring_rows = c.fetchall()
    recurring_count = len(recurring_rows)

    insights = []
    if by_category:
        insights.append('你在「' + by_category[0]['category'] + '」错最多 (' + str(by_category[0]['wrong_count']) + ' 道，占 ' + str(by_category[0]['percentage']) + '%)')
    if by_difficulty:
        insights.append('「' + by_difficulty[0]['difficulty'] + '」难度题错最多 (' + str(by_difficulty[0]['percentage']) + '%)')
    if recurring_count > 0:
        insights.append('有 ' + str(recurring_count) + ' 道反复错的题，需要专项突破')
    if not insights:
        insights.append('错题数据不足，继续保持！')

    conn.close()
    return jsonify({
        'success': True,
        'total_wrong': total_wrong,
        'total_reviews': total_reviews,
        'recurring_count': recurring_count,
        'by_category': by_category,
        'by_difficulty': by_difficulty,
        'by_type': by_type,
        'by_time': by_time,
        'insights': insights
    })


@app.route('/api/kb/recurring-wrong')
def kb_recurring_wrong():
    """反复错题识别"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT ua.question_id, COUNT(*) as wrong_cnt, MAX(ua.answered_at) as last_wrong
        FROM user_answers ua WHERE ua.is_correct = 0
        GROUP BY ua.question_id HAVING wrong_cnt >= 2
        ORDER BY wrong_cnt DESC, last_wrong DESC
    ''')
    recurring = []
    for r in c.fetchall():
        wrong_cnt, last_wrong = r[1], r[2]
        if wrong_cnt >= 3:
            severity, severity_label = 'high', '严重反复错'
        else:
            severity, severity_label = 'medium', '反复错'
        c.execute('SELECT topic, topic_category, difficulty, question FROM questions WHERE question_id = ?', (r[0],))
        q = c.fetchone()
        if not q:
            continue
        recurring.append({
            'question_id': r[0],
            'topic': q[0] or '',
            'topic_category': q[1] or '',
            'difficulty': q[2] or '',
            'question': q[3][:80] + ('...' if len(q[3]) > 80 else ''),
            'wrong_count': wrong_cnt,
            'last_wrong_at': last_wrong,
            'severity': severity,
            'severity_label': severity_label
        })
    conn.close()
    return jsonify({
        'success': True,
        'recurring': recurring,
        'total_recurring': len(recurring),
        'message': '你反复错的题，需要专项突破' if recurring else '没有反复错的题，很棒！'
    })


@app.route('/api/kb/review-suggestions')
def kb_review_suggestions():
    """智能复习推荐"""
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        SELECT w.question_id, w.user_answer, w.correct_answer, w.created_at,
               q.topic, q.topic_category, q.difficulty, q.type, q.question
        FROM wrong_answers w JOIN questions q ON w.question_id = q.question_id
        WHERE w.review_count = 0
        ORDER BY w.created_at ASC
    ''')
    pending = []
    for r in c.fetchall():
        c.execute("SELECT julianday('now') - julianday(?)", (r[3],))
        days_passed = c.fetchone()[0] or 0
        pending.append({
            'question_id': r[0],
            'topic_category': r[5] or '未分类',
            'difficulty': r[6] or '未知',
            'type': r[7] or '未知',
            'question': r[8][:60] + ('...' if len(r[8]) > 60 else ''),
            'wrong_since_days': round(days_passed),
            'priority': 1 if days_passed >= 3 else 2,
            'reason': '错题本里还没复习过'
        })

    c.execute('''
        SELECT ua.question_id, COUNT(*) as wrong_cnt, MAX(ua.answered_at)
        FROM user_answers ua WHERE ua.is_correct = 0
        GROUP BY ua.question_id HAVING wrong_cnt >= 2
    ''')
    recurring_set = {r[0]: (r[1], r[2]) for r in c.fetchall()}

    pending_by_cat = {}
    for p in pending:
        cat = p['topic_category']
        if cat not in pending_by_cat:
            pending_by_cat[cat] = []
        pending_by_cat[cat].append(p['question_id'])

    today_review, tomorrow_review, week_review = [], [], []
    for p in pending:
        if p['question_id'] in recurring_set:
            p['priority'] = 0
            p['reason'] = '反复错的题 (错 ' + str(recurring_set[p['question_id']][0]) + ' 次)，立即复习'
            today_review.append(p)
        elif p['wrong_since_days'] >= 7:
            p['reason'] = '错题已经 ' + str(int(p['wrong_since_days'])) + ' 天没复习，本周必须复习'
            week_review.append(p)
        elif p['wrong_since_days'] >= 1:
            tomorrow_review.append(p)
        else:
            today_review.append(p)

    today_review.sort(key=lambda x: (x['priority'], -x['wrong_since_days']))
    tomorrow_review.sort(key=lambda x: (-x['wrong_since_days']))
    week_review.sort(key=lambda x: (-x['wrong_since_days']))

    conn.close()
    return jsonify({
        'success': True,
        'today': today_review,
        'tomorrow': tomorrow_review,
        'this_week': week_review,
        'stats': {
            'total_pending': len(pending),
            'today_count': len(today_review),
            'tomorrow_count': len(tomorrow_review),
            'week_count': len(week_review),
            'recurring_count': len(recurring_set)
        },
        'pending_by_category': pending_by_cat
    })


@app.route('/api/kb/difficulty-progress')
def kb_difficulty_progress():
    """难度进阶分析"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT difficulty, COUNT(*) FROM questions GROUP BY difficulty ORDER BY difficulty")
    total_by_diff = {r[0] or '未知': r[1] for r in c.fetchall()}

    c.execute('''
        SELECT q.difficulty, COUNT(*) as answered,
               SUM(CASE WHEN ua.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM user_answers ua JOIN questions q ON ua.question_id = q.question_id
        GROUP BY q.difficulty
    ''')
    user_by_diff = {r[0] or '未知': (r[1], r[2] or 0) for r in c.fetchall()}

    c.execute('''
        SELECT q.difficulty, COUNT(*) FROM wrong_answers w
        JOIN questions q ON w.question_id = q.question_id GROUP BY q.difficulty
    ''')
    wrong_by_diff = {r[0] or '未知': r[1] for r in c.fetchall()}

    difficulty_order = ['基础', '容易', '中等', '一般', '较难', '困难']
    result = []
    for diff in difficulty_order:
        total = total_by_diff.get(diff, 0)
        answered, correct = user_by_diff.get(diff, (0, 0))
        wrong = wrong_by_diff.get(diff, 0)
        accuracy = round(correct * 100 / answered, 1) if answered else 0
        coverage = round(answered * 100 / total, 1) if total else 0
        result.append({
            'difficulty': diff,
            'total_questions': total,
            'answered': answered,
            'correct': correct,
            'wrong': wrong,
            'accuracy': accuracy,
            'coverage': coverage
        })

    current_acc = {r['difficulty']: r['accuracy'] for r in result if r['answered'] >= 3}
    mastered_levels = [d for d, a in current_acc.items() if a >= 70]
    if not mastered_levels:
        suggestion = '建议从基础题开始练起'
    elif '困难' in mastered_levels:
        suggestion = '已掌握困难题！可以参加模拟考试'
    elif '较难' in mastered_levels:
        suggestion = '已掌握较难题，建议挑战困难题'
    elif '中等' in mastered_levels:
        suggestion = '已掌握中等题，可以尝试较难题'
    elif '基础' in mastered_levels:
        suggestion = '已掌握基础题，建议挑战中等题'
    else:
        suggestion = '继续巩固当前难度'

    conn.close()
    return jsonify({
        'success': True,
        'by_difficulty': result,
        'suggestion': suggestion,
        'mastered_levels': mastered_levels
    })


# ============================================================
# Phase 3: AI 出题
# ============================================================

# 关键词映射表（用于题目变体生成）
KEYWORD_REPLACE = {
    # 路由协议
    'OSPF': ['IS-IS', 'RIP', 'BGP', 'EIGRP'],
    'BGP': ['OSPF', 'IS-IS', 'RIP', 'EIGRP'],
    'RIP': ['OSPF', 'BGP', 'IS-IS'],
    'OSPF': ['IS-IS', 'BGP', 'RIP'],
    'IS-IS': ['OSPF', 'BGP', 'RIP'],
    # 网络安全
    'IPSec': ['SSL', 'TLS', 'SSH'],
    'SSL': ['IPSec', 'TLS', 'HTTPS'],
    'TLS': ['SSL', 'IPSec'],
    '防火墙': ['IDS', 'IPS', 'WAF'],
    'IDS': ['防火墙', 'IPS'],
    'VPN': ['专线', 'MPLS', 'SD-WAN'],
    'PKI': ['CA', '数字证书体系'],
    # 交换技术
    'VLAN': ['VXLAN', 'TRILL', 'EVPN'],
    'STP': ['RSTP', 'MSTP', 'PVST'],
    # 广域网
    'MPLS': ['SD-WAN', 'VPN', 'MPLS VPN'],
    'PPP': ['HDLC', 'Frame Relay'],
    'SD-WAN': ['MPLS', '传统 WAN'],
    # IPv6
    'IPv4': ['IPv6'],
    'IPv6': ['IPv4'],
    # 无线
    'Wi-Fi': ['5G', 'WLAN'],
    '5G': ['4G', 'Wi-Fi 6'],
    # 数据中心
    'NFV': ['SDN', '虚拟化'],
    'SDN': ['NFV', 'OpenFlow'],
    # 数字
    '两个': ['三个', '四个', '五个'],
    '三个': ['两个', '四个'],
    '四个': ['三个', '五个'],
    '五': ['三', '七'],
    '三': ['二', '四', '五'],
}


def _generate_variant(template_q, variant_index=0):
    """基于模板生成变体题

    Args:
        template_q: 原始题目字典 (id, type, topic, topic_category, difficulty, question, options, answer, explanation)
        variant_index: 变体索引 (0, 1, 2...) 用于决定替换策略

    Returns:
        生成的变体题字典
    """
    import re
    import random

    question = template_q['question']
    explanation = template_q.get('explanation', '') or ''
    answer = template_q['answer']
    options = template_q['options']

    # 1. 关键词替换 (用 placeholder 避免链式替换)
    new_question = question
    new_explanation = explanation
    replacements = []
    placeholders = {}
    ph_index = [0]
    def make_placeholder():
        ph_index[0] += 1
        return f'__PH{ph_index[0]}__'

    for original, candidates in KEYWORD_REPLACE.items():
        if original in new_question and len(replacements) < 3:
            candidate = candidates[variant_index % len(candidates)]
            ph = make_placeholder()
            new_question = new_question.replace(original, ph, 1)
            placeholders[ph] = candidate
            if original in new_explanation:
                ph2 = make_placeholder()
                new_explanation = new_explanation.replace(original, ph2, 1)
                placeholders[ph2] = candidate
            replacements.append((original, candidate))

    for ph, val in placeholders.items():
        new_question = new_question.replace(ph, val)
        new_explanation = new_explanation.replace(ph, val)

    # 2. 数字替换 (1-9 替换为 2-10)
    def number_replacer(match):
        n = int(match.group(0))
        # 避免替换年份等特殊数字
        if 1900 <= n <= 2100:
            return match.group(0)
        # 替换为不同数字
        return str(n + (variant_index + 1) * 2)
    new_question = re.sub(r'\b\d+\b', number_replacer, new_question)
    if new_explanation:
        new_explanation = re.sub(r'\b\d+\b', number_replacer, new_explanation)

    # 3. 场景词替换 (常见的场景描述)
    scenario_swaps = {
        '某企业': ['某公司', '某机构', '某高校', '某医院'],
        '某公司': ['某企业', '某机构', '某高校'],
        '网络管理员': ['运维工程师', '系统管理员', '网络架构师'],
        '管理员': ['工程师', '架构师'],
        '总部': ['总部机房', '主数据中心', '核心节点'],
        '分支机构': ['分公司', '子公司', '远程节点'],
    }
    for original, candidates in scenario_swaps.items():
        if original in new_question:
            candidate = candidates[variant_index % len(candidates)]
            new_question = new_question.replace(original, candidate, 1)

    # 4. 解析选项为 (key, value) 对
    try:
        if isinstance(options, str):
            opts_str = options.strip()
            if not opts_str or opts_str == '[]':
                opts_list = []
            else:
                opts_list = json.loads(opts_str)
        else:
            opts_list = options or []
    except (json.JSONDecodeError, TypeError):
        opts_list = []

    parsed_opts = []
    correct_content = None
    for i, opt in enumerate(opts_list):
        if isinstance(opt, str):
            key = opt[0] if opt else chr(65 + i)
            content = opt[2:].strip() if len(opt) > 2 else opt
        else:
            key = opt.get('key', chr(65 + i))
            content = opt.get('value', str(opt))
        parsed_opts.append({'key': key, 'value': content})
        if key == answer:
            correct_content = content

    # 5. 选项洗牌 - 只对选择题且选项数>=4
    if correct_content and len(parsed_opts) >= 4 and len(answer) == 1 and answer.isalpha():
        original_idx = ord(answer.upper()) - ord('A')
        if variant_index % 2 == 1:
            candidates = [i for i in range(4) if i != original_idx]
            new_idx = candidates[variant_index % len(candidates)]
            other_new = [i for i in range(4) if i != new_idx]
            other_orig = [i for i in range(4) if i != original_idx]
            random.shuffle(other_orig)
            position_map = {new_idx: original_idx}
            for new_pos, orig_pos in zip(other_new, other_orig):
                position_map[new_pos] = orig_pos
            new_opts_list = [parsed_opts[position_map[i]] for i in range(4)]
            new_answer = chr(65 + new_idx)
        else:
            new_opts_list = parsed_opts
            new_answer = answer
    else:
        new_opts_list = parsed_opts
        new_answer = answer

    # 6. 组装新题
    return {
        'id': 'ai-gen-' + template_q['id'] + '-v' + str(variant_index + 1),
        'type': template_q['type'],
        'topic': template_q.get('topic', ''),
        'topic_category': template_q.get('topic_category', ''),
        'difficulty': template_q.get('difficulty', ''),
        'question': new_question,
        'options': new_opts_list,
        'answer': new_answer,
        'explanation': new_explanation,
        'based_on': template_q['id'],
        'replacements': replacements,
        'generated_at': datetime.now().isoformat(),
        'method': 'template'
    }


@app.route('/api/kb/generate', methods=['POST'])
def kb_generate():
    """AI 出题 - Phase 3

    基于模板生成题目变体
    Body:
        category: 一级分类 (可选)
        difficulty: 难度 (可选)
        topic: 原 topic 字段 (可选)
        count: 生成数量 (默认 5)
        based_on_wrong: 是否基于错题 (默认 False)
    """
    data = request.json or {}
    category = data.get('category')
    difficulty = data.get('difficulty')
    topic = data.get('topic')
    count = data.get('count', 5)
    based_on_wrong = data.get('based_on_wrong', False)

    conn = get_db()
    c = conn.cursor()

    # 1. 取模板题
    if based_on_wrong:
        # 从错题本取
        c.execute('''
            SELECT q.question_id, q.type, q.topic, q.topic_category, q.difficulty,
                   q.question, q.options, q.answer, q.explanation
            FROM wrong_answers w
            JOIN questions q ON w.question_id = q.question_id
            WHERE 1=1
        ''' + ('''
            AND q.topic_category = ?
        ''' if category else '') + ('''
            AND q.difficulty = ?
        ''' if difficulty else '') + '''
            ORDER BY RANDOM()
        ''')
        params = []
        if category:
            params.append(category)
        if difficulty:
            params.append(difficulty)
        templates = c.fetchall()
    else:
        # 从题库取
        sql = '''
            SELECT question_id, type, topic, topic_category, difficulty,
                   question, options, answer, explanation
            FROM questions
            WHERE 1=1
        '''
        params = []
        if category:
            sql += ' AND topic_category = ?'
            params.append(category)
        if difficulty:
            sql += ' AND difficulty = ?'
            params.append(difficulty)
        if topic:
            sql += ' AND topic = ?'
            params.append(topic)
        sql += ' ORDER BY RANDOM()'
        c.execute(sql, params)
        templates = c.fetchall()

    if not templates:
        conn.close()
        return jsonify({'success': False, 'error': '没有找到模板题'}), 404

    # 2. 为每个模板生成 count 个变体
    generated = []
    used_questions = set()
    for tmpl in templates:
        if len(generated) >= count:
            break
        # 跳过案例题（结构不同）
        if tmpl[1] == '案例分析':
            continue
        tmpl_dict = {
            'id': tmpl[0], 'type': tmpl[1], 'topic': tmpl[2],
            'topic_category': tmpl[3], 'difficulty': tmpl[4],
            'question': tmpl[5], 'options': tmpl[6],
            'answer': tmpl[7], 'explanation': tmpl[8] or ''
        }
        # 每个模板生成 1-2 个变体
        for v in range(min(2, count - len(generated))):
            variant = _generate_variant(tmpl_dict, variant_index=v)
            # 去重 (变体题和原题不同时)
            if variant['question'] not in used_questions and variant['question'] != tmpl[5]:
                used_questions.add(variant['question'])
                generated.append(variant)

    conn.close()
    return jsonify({
        'success': True,
        'method': 'template',
        'count': len(generated),
        'questions': generated,
        'based_on': [t[0] for t in templates[:len(generated)]]
    })


@app.route('/api/kb/import-generated', methods=['POST'])
def kb_import_generated():
    """入库 AI 生成的题目

    Body:
        questions: 题库列表，每个包含 question, options, answer, explanation, topic_category 等
    """
    data = request.json or {}
    questions = data.get('questions', [])

    if not questions:
        return jsonify({'success': False, 'error': '没有要导入的题目'}), 400

    conn = get_db()
    c = conn.cursor()

    # 生成新的 question_id (ai-gen-NNN)
    c.execute("SELECT question_id FROM questions WHERE question_id LIKE 'ai-gen-%' ORDER BY question_id DESC LIMIT 1")
    row = c.fetchone()
    if row:
        try:
            last_num = int(row[0].split('-')[-1])
        except (ValueError, IndexError):
            last_num = 0
    else:
        last_num = 0

    imported = []
    for i, q in enumerate(questions):
        new_id = 'ai-gen-' + str(last_num + i + 1).zfill(3)
        # 解析 options
        opts = q.get('options', [])
        if isinstance(opts, list) and opts and isinstance(opts[0], dict):
            opts_str = json.dumps([o.get('value', o.get('key', '')) for o in opts])
        else:
            opts_str = json.dumps(opts)

        # 处理 knowledge_points
        kps = q.get('knowledge_points', '[]')
        if isinstance(kps, list):
            kps = json.dumps(kps)

        c.execute('''
            INSERT INTO questions
            (question_id, type, topic, topic_category, topic_tags, knowledge_points,
             difficulty, question, options, answer, explanation, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            new_id,
            q.get('type', '选择题'),
            q.get('topic', ''),
            q.get('topic_category', ''),
            q.get('topic_tags', '[]'),
            kps,
            q.get('difficulty', '中等'),
            q.get('question', ''),
            opts_str,
            q.get('answer', 'A'),
            q.get('explanation', ''),
            q.get('image', '')
        ))
        # 插入关联表
        try:
            kps_list = json.loads(kps) if isinstance(kps, str) else kps
            for kp in kps_list:
                c.execute('INSERT OR IGNORE INTO question_knowledge (question_id, knowledge_code) VALUES (?, ?)', (new_id, kp))
        except (json.JSONDecodeError, TypeError):
            pass
        imported.append(new_id)

    conn.commit()
    conn.close()
    return jsonify({
        'success': True,
        'imported': imported,
        'count': len(imported),
        'message': '成功导入 ' + str(len(imported)) + ' 道 AI 生成的题目'
    })


@app.route('/api/kb/ai-stats')
def kb_ai_stats():
    """AI 出题统计"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM questions WHERE question_id LIKE 'ai-gen-%'")
    total_ai = c.fetchone()[0]
    c.execute("SELECT difficulty, COUNT(*) FROM questions WHERE question_id LIKE 'ai-gen-%' GROUP BY difficulty")
    by_diff = {r[0]: r[1] for r in c.fetchall()}
    c.execute("SELECT topic_category, COUNT(*) FROM questions WHERE question_id LIKE 'ai-gen-%' AND topic_category != '' GROUP BY topic_category")
    by_cat = {r[0]: r[1] for r in c.fetchall()}
    conn.close()
    return jsonify({
        'success': True,
        'total_ai_questions': total_ai,
        'by_difficulty': by_diff,
        'by_category': by_cat
    })


# ============================================================
# Phase 3.5: LLM 智能出题 (集成 MiniMax)
# ============================================================

MINIMAX_BASE_URL = 'https://api.minimaxi.com/anthropic'
MINIMAX_MODEL = 'MiniMax-M3'
MINIMAX_API_KEY = None


def _load_minimax_api_key():
    """从 /app/.env 加载 API key"""
    global MINIMAX_API_KEY
    if MINIMAX_API_KEY:
        return MINIMAX_API_KEY
    try:
        with open('/app/.env') as f:
            for line in f:
                if line.startswith('MINIMAX_API_KEY='):
                    MINIMAX_API_KEY = line.split('=', 1)[1].strip()
                    return MINIMAX_API_KEY
    except FileNotFoundError:
        pass
    return os.environ.get('MINIMAX_API_KEY')


def _call_minimax(prompt, max_tokens=2048):
    """调用 MiniMax LLM API"""
    import urllib.request
    import urllib.error
    api_key = _load_minimax_api_key()
    if not api_key:
        raise ValueError('MINIMAX_API_KEY 未设置')

    data = {
        'model': MINIMAX_MODEL,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': prompt}]
    }
    req = urllib.request.Request(
        MINIMAX_BASE_URL + '/v1/messages',
        data=json.dumps(data).encode(),
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01'
        }
    )
    r = urllib.request.urlopen(req, timeout=60)
    result = json.loads(r.read())
    if result.get('content'):
        for c in result['content']:
            if c.get('type') == 'text':
                return c['text'], result.get('usage', {})
    return '', {}


def _build_llm_prompt(category, difficulty, count, topic, samples):
    """构建出题 prompt"""
    sample_text = ''
    if samples:
        sample_text = '\n\n参考以下题库中的题目风格:\n'
        for i, s in enumerate(samples[:3], 1):
            sample_text += '\n样例 ' + str(i) + ':\n'
            sample_text += '题目: ' + s.get('question', '') + '\n'
            opts = s.get('options', [])
            if isinstance(opts, str):
                try:
                    opts = json.loads(opts)
                except (json.JSONDecodeError, TypeError):
                    pass
            if isinstance(opts, list):
                for o in opts:
                    if isinstance(o, dict):
                        sample_text += o.get('key', '') + '. ' + o.get('value', '') + '\n'
                    else:
                        sample_text += str(o) + '\n'
            sample_text += '答案: ' + str(s.get('answer', '')) + '\n'
            if s.get('explanation'):
                sample_text += '解析: ' + s['explanation'][:200] + '\n'

    prompt = '''你是网络规划设计师考试出题专家。请生成 ' + str(count) + ' 道选择题。

要求：
- 分类: ''' + (category or '不限') + '''
- 难度: ''' + (difficulty or '中等') + '''
- 主题: ''' + (topic or '不限定') + '''
- 题目内容: 30-150 字，技术严谨
- 4 个选项 (A/B/C/D)，干扰项合理
- 答案明确，只输出选项字母
- 解析: 50-200 字，说清为什么这个答案对，其他为什么错
- **不与样例题重复**
''' + sample_text + '''

请严格按 JSON 数组格式输出，不要任何额外文字:
[
  {
    "question": "题目内容",
    "options": ["A. 选项A", "B. 选项B", "C. 选项C", "D. 选项D"],
    "answer": "A",
    "explanation": "解析"
  }
]'''
    return prompt


def _parse_llm_questions(text, count):
    """解析 LLM 输出的 JSON"""
    import re
    # 尝试提取 JSON 块
    json_match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
    else:
        json_str = text

    try:
        questions = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        # 尝试按行解析
        return []

    if not isinstance(questions, list):
        questions = [questions]

    # 验证每道题
    valid = []
    for q in questions[:count]:
        if not isinstance(q, dict):
            continue
        if not q.get('question') or not q.get('options') or not q.get('answer'):
            continue
        opts = q.get('options', [])
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(opts, list) or len(opts) < 4:
            continue
        if q.get('answer', '').upper() not in ['A', 'B', 'C', 'D']:
            continue
        valid.append({
            'question': q['question'].strip(),
            'options': opts[:4],
            'answer': q['answer'].upper(),
            'explanation': q.get('explanation', '').strip()
        })
    return valid


@app.route('/api/kb/llm-generate', methods=['POST'])
def kb_llm_generate():
    """LLM 智能出题 - Phase 3.5

    调用 MiniMax-M3 LLM 生成新题
    Body:
        category: 一级分类
        difficulty: 难度
        topic: 限定主题 (如 OSPF, BGP)
        count: 生成数量 (默认 3)
    """
    data = request.json or {}
    category = data.get('category', '')
    difficulty = data.get('difficulty', '中等')
    topic = data.get('topic', '')
    count = min(data.get('count', 3), 5)  # 限制最多 5 道

    conn = get_db()
    c = conn.cursor()

    # 取样例题
    sql = 'SELECT question, options, answer, explanation FROM questions WHERE 1=1'
    params = []
    if category:
        sql += ' AND topic_category = ?'
        params.append(category)
    if difficulty:
        sql += ' AND difficulty = ?'
        params.append(difficulty)
    sql += ' ORDER BY RANDOM() LIMIT 3'
    c.execute(sql, params)
    cols = [d[0] for d in c.description]
    samples = [dict(zip(cols, row)) for row in c.fetchall()]

    # 已有题目（用于去重）
    c.execute('SELECT question FROM questions')
    existing_questions = set(r[0].strip()[:50] for r in c.fetchall() if r[0])

    conn.close()

    # 构建 prompt 并调用
    try:
        prompt = _build_llm_prompt(category, difficulty, count, topic, samples)
        text, usage = _call_minimax(prompt, max_tokens=3000)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'LLM 调用失败: ' + str(e)
        }), 500

    # 解析
    questions = _parse_llm_questions(text, count)

    # 去重 + 标记
    generated = []
    for i, q in enumerate(questions):
        is_dup = q['question'][:50] in existing_questions
        generated.append({
            'id': 'llm-gen-' + datetime.now().strftime('%H%M%S') + '-' + str(i + 1),
            'type': '选择题',
            'topic': topic or '',
            'topic_category': category or '',
            'difficulty': difficulty,
            'question': q['question'],
            'options': [{'key': chr(65 + j), 'value': o} if isinstance(o, str) else o
                       for j, o in enumerate(q['options'][:4])],
            'answer': q['answer'],
            'explanation': q['explanation'],
            'generated_at': datetime.now().isoformat(),
            'method': 'llm',
            'is_duplicate': is_dup,
            'usage': usage
        })

    return jsonify({
        'success': True,
        'method': 'llm',
        'model': MINIMAX_MODEL,
        'count': len(generated),
        'questions': generated,
        'usage': usage,
        'prompt_preview': prompt[:200] + '...'
    })


if __name__ == '__main__':
    init_db()
    upgrade_db()
    app.run(host='0.0.0.0', port=3030, debug=True)

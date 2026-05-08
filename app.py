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
                image TEXT
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
                last_reviewed_at TEXT
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
        conn.commit()
        conn.close()
        print("数据库初始化完成")


@app.route('/')
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
    
    sql = 'SELECT question_id, type, topic, difficulty, question, options, image FROM questions WHERE 1=1'
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
        questions.append({
            'question_id': row[0],
            'type': row[1],
            'topic': row[2],
            'difficulty': row[3],
            'question': row[4],
            'options': json.loads(row[5]) if row[5] else [],
            'image': row[6] or ''
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
    is_correct = 1 if user_answer.strip().upper() == correct_answer.strip().upper() else 0
    
    # 记录答题
    c.execute('''
        INSERT INTO user_answers (question_id, user_answer, is_correct, answered_at, session_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (question_id, user_answer, is_correct, datetime.now().isoformat(), session_id))
    
    # 更新错题本
    if not is_correct:
        c.execute('''
            INSERT OR REPLACE INTO wrong_answers 
            (question_id, user_answer, correct_answer, created_at, review_count, last_reviewed_at)
            VALUES (
                ?, ?, ?, ?,
                COALESCE((SELECT review_count FROM wrong_answers WHERE question_id = ?), 0),
                datetime('now')
            )
        ''', (question_id, user_answer, correct_answer, datetime.now().isoformat(), question_id))
    
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
        'session_id': session_id
    })


@app.route('/api/wrong')
def get_wrong():
    """获取错题本"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT w.question_id, w.user_answer, w.correct_answer, w.created_at, 
               w.review_count, q.question, q.options, q.topic, q.difficulty, q.explanation
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
            'explanation': row[9] if len(row) > 9 else ''
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


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=3030, debug=True)

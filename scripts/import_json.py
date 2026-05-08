#!/usr/bin/env python3
"""导入题库 JSON 到 SQLite 数据库"""

import json
import sqlite3
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'exam.db')
JSON_BASIC = os.path.join(BASE_DIR, 'questions', 'basic-questions.json')
JSON_CASE = os.path.join(BASE_DIR, 'questions', 'case-questions.json')


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    return conn


def import_basic(conn, filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    c = conn.cursor()
    count = 0
    for q in data.get('questions', []):
        try:
            c.execute('''
                INSERT OR REPLACE INTO questions 
                (question_id, type, topic, difficulty, question, options, answer, explanation)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
            ''', (
                q['id'],
                q.get('type', '选择题'),
                q.get('topic', ''),
                q.get('difficulty', '中等'),
                q['question'],
                json.dumps(q.get('options', []), ensure_ascii=False)
            ))
            count += 1
        except Exception as e:
            print(f"跳过 {q.get('id')}: {e}")
    
    conn.commit()
    print(f"导入基础题: {count} 道")


def import_cases(conn, filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    c = conn.cursor()
    count = 0
    for q in data.get('questions', []):
        try:
            c.execute('''
                INSERT OR REPLACE INTO questions 
                (question_id, type, topic, difficulty, question, options, answer, explanation, image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                q['id'],
                q.get('type', '案例分析'),
                q.get('topic', ''),
                q.get('difficulty', '中等'),
                q['question'],
                json.dumps(q.get('options', []), ensure_ascii=False),
                q.get('answer', ''),
                q.get('explanation', ''),
                q.get('image', '')
            ))
            count += 1
        except Exception as e:
            print(f"跳过 {q.get('id')}: {e}")
    
    conn.commit()
    print(f"导入案例题: {count} 道")


def main():
    print("初始化数据库...")
    conn = init_db()
    
    print("导入基础题库...")
    if os.path.exists(JSON_BASIC):
        import_basic(conn, JSON_BASIC)
    else:
        print(f"文件不存在: {JSON_BASIC}")
    
    print("导入案例题库...")
    if os.path.exists(JSON_CASE):
        import_cases(conn, JSON_CASE)
    else:
        print(f"文件不存在: {JSON_CASE}")
    
    # 统计
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM questions')
    total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM questions WHERE type="选择题"')
    basic = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM questions WHERE type="案例分析"')
    case = c.fetchone()[0]
    
    print(f"\n✅ 导入完成!")
    print(f"总题数: {total}")
    print(f"基础题: {basic}")
    print(f"案例题: {case}")
    
    conn.close()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""导入题库到SQLite数据库"""
import sqlite3
import json
import os

DATA_DIR = '/app/data'
DB_PATH = os.path.join(DATA_DIR, 'exam.db')
QUESTIONS_DIR = '/app/questions'

def init_db():
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

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def import_questions(conn, json_path, qtype):
    """从JSON文件导入题目"""
    try:
        data = load_json(json_path)
        questions = data.get('questions', [])
        
        c = conn.cursor()
        imported = 0
        for q in questions:
            # 提取答案（选项中找正确答案）
            options = q.get('options', [])
            answer = q.get('answer', '')
            
            # 如果没有answer字段，从options中推断（选项中有*标记的）
            if not answer:
                for opt in options:
                    if opt.startswith('*'):
                        answer = opt[0]  # 如 "*A. xxx" -> "A"
                        break
            
            # 清理选项文本中的 * 标记
            cleaned_options = []
            for opt in options:
                if opt.startswith('*'):
                    cleaned_options.append(opt[1:].strip())
                else:
                    cleaned_options.append(opt.strip())
            
            c.execute('''
                INSERT OR REPLACE INTO questions 
                (question_id, type, topic, difficulty, question, options, answer, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                q.get('id', ''),
                qtype,
                q.get('topic', ''),
                q.get('difficulty', ''),
                q.get('question', ''),
                json.dumps(cleaned_options, ensure_ascii=False),
                answer,
                q.get('explanation', '')
            ))
            imported += 1
        
        conn.commit()
        return imported
    except Exception as e:
        print(f"导入出错 {json_path}: {e}")
        return 0

def main():
    conn = init_db()
    total = 0
    
    # 导入基础题
    basic_path = os.path.join(QUESTIONS_DIR, 'basic-questions.json')
    if os.path.exists(basic_path):
        cnt = import_questions(conn, basic_path, '选择题')
        print(f"导入基础题: {cnt} 道")
        total += cnt
    
    # 导入案例题
    case_path = os.path.join(QUESTIONS_DIR, 'case-questions.json')
    if os.path.exists(case_path):
        cnt = import_questions(conn, case_path, '案例分析')
        print(f"导入案例题: {cnt} 道")
        total += cnt
    
    # 验证
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM questions')
    count = c.fetchone()[0]
    print(f"数据库中题目总数: {count}")
    
    conn.close()
    print(f"完成! 共导入 {total} 道题目")

if __name__ == '__main__':
    main()
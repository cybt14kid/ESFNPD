#!/usr/bin/env python3
"""更新题库解析"""
import sqlite3
import json

DB_PATH = '/app/data/exam.db'
IMPORT_FILE = '/tmp/with_exp.json'

def main():
    with open(IMPORT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    updated = 0
    for item in data:
        c.execute('''
            UPDATE questions 
            SET answer = ?, explanation = ?
            WHERE question_id = ?
        ''', (item['answer'], item['explanation'], item['question_id']))
        updated += 1
    
    conn.commit()
    
    # 验证
    c.execute('SELECT COUNT(*) FROM questions WHERE explanation IS NOT NULL AND explanation != ""')
    total = c.fetchone()[0]
    print(f'更新了 {updated} 道题的解析')
    print(f'数据库中现有解析的题目总数: {total}')
    
    conn.close()

if __name__ == '__main__':
    main()
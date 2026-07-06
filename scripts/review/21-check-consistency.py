#!/usr/bin/env python3
"""
题库数据一致性检查脚本
========================

检查项目：
1. answer 字段与 explanation 末尾的"答案为 X"声明是否一致
2. explanation 里是否残留开发痕迹（"原答案 X"、"原解析"、"需修正"、"TODO" 等）

用法：
    python scripts/review/21-check-consistency.py [--db PATH] [--fix-traces]

参数：
    --db PATH          指定 exam.db 路径（默认 /app/data/exam.db 或 ./data/exam.db）
    --fix-traces       警告模式下，列出所有需要清理的解析（不直接修改）

退出码：
    0  一致，无问题
    1  发现 answer-explanation 不一致（需要修复）
    2  发现解析里有开发痕迹（建议清理）
    3  两种问题都有
"""

import sqlite3
import re
import sys
import argparse
from pathlib import Path


def find_db_path(args_db):
    """智能查找 exam.db 路径"""
    if args_db:
        return args_db
    # 优先容器路径
    candidates = [
        '/app/data/exam.db',
        './data/exam.db',
        '../data/exam.db',
        '../../data/exam.db',
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    print('❌ 找不到 exam.db，请用 --db 指定路径', file=sys.stderr)
    sys.exit(2)


def check_answer_consistency(conn):
    """检查 answer 字段与 explanation 末尾声明的一致性"""
    c = conn.cursor()
    c.execute('SELECT question_id, answer, explanation FROM questions WHERE explanation IS NOT NULL AND explanation != ""')

    issues = []
    for row in c.fetchall():
        qid, answer, exp = row
        if ',' in answer:  # 跳过多空题
            continue
        # 只看末尾 200 字符（避免被解析中段的"原答案 X 错误"误匹配）
        tail = exp[-200:] if len(exp) > 200 else exp
        patterns = [
            r'答案为\s*([A-D])',
            r'故答案为\s*([A-D])',
            r'正确答案[是为]\s*([A-D])',
            r'故选\s*([A-D])',
            r'应选\s*([A-D])',
            r'最终答案为\s*([A-D])',
        ]
        for p in patterns:
            m = re.search(p, tail)
            if m:
                stated = m.group(1)
                if stated != answer:
                    issues.append({
                        'qid': qid,
                        'db_answer': answer,
                        'stated_answer': stated,
                        'context': tail[max(0, m.start()-20):m.end()+20],
                    })
                break
    return issues


def check_dev_traces(conn):
    """检查 explanation 里是否有开发痕迹"""
    c = conn.cursor()
    c.execute('SELECT question_id, explanation FROM questions WHERE explanation IS NOT NULL AND explanation != ""')

    trace_patterns = [
        (r'原答案[是为]?\s*[A-D][\s，,。]', '原答案'),
        (r'应改为\s*[A-D]', '应改为'),
        (r'应改成\s*[A-D]', '应改成'),
        (r'原解析', '原解析'),
        (r'修正后', '修正后'),
        (r'需修正', '需修正'),
        (r'需重写', '需重写'),
        (r'表述混乱', '表述混乱'),
        (r'答非所问', '答非所问'),
        (r'完全偏离', '完全偏离'),
        (r'跑题', '跑题'),
        (r'TODO', 'TODO'),
        (r'FIXME', 'FIXME'),
    ]

    issues = []
    for row in c.fetchall():
        qid, exp = row
        matches = []
        for pattern, desc in trace_patterns:
            for m in re.finditer(pattern, exp):
                ctx = exp[max(0, m.start()-15):m.end()+25]
                matches.append((desc, ctx))
        if matches:
            issues.append({
                'qid': qid,
                'traces': matches,
            })
    return issues


def main():
    parser = argparse.ArgumentParser(description='题库数据一致性检查')
    parser.add_argument('--db', help='exam.db 路径')
    parser.add_argument('--fix-traces', action='store_true', help='显示需要清理的题')
    args = parser.parse_args()

    db_path = find_db_path(args.db)
    print(f'📂 数据库: {db_path}\n')

    conn = sqlite3.connect(db_path)
    try:
        consistency_issues = check_answer_consistency(conn)
        trace_issues = check_dev_traces(conn)
    finally:
        conn.close()

    exit_code = 0

    # === 报告 1: answer-explanation 一致性 ===
    print('=' * 70)
    print('🔍 检查 1: answer 字段 vs explanation 末尾声明')
    print('=' * 70)
    if consistency_issues:
        print(f'❌ 发现 {len(consistency_issues)} 道题不一致：\n')
        for issue in consistency_issues:
            print(f'  {issue["qid"]}: DB={issue["db_answer"]} | 解析声称={issue["stated_answer"]}')
            print(f'    上下文: ...{issue["context"]}...')
            print()
        exit_code |= 1
    else:
        print('✅ 所有单选题的 answer 字段与 explanation 末尾声明一致\n')

    # === 报告 2: 开发痕迹 ===
    print('=' * 70)
    print('🔍 检查 2: explanation 里的开发痕迹')
    print('=' * 70)
    if trace_issues:
        print(f'⚠️  发现 {len(trace_issues)} 道题解析含开发痕迹\n')
        for issue in trace_issues[:20]:  # 只列前 20 个
            print(f'  {issue["qid"]}:')
            for desc, ctx in issue['traces'][:3]:  # 每个题最多列 3 个痕迹
                print(f'    [{desc}] ...{ctx}...')
            print()
        if len(trace_issues) > 20:
            print(f'  ... 还有 {len(trace_issues) - 20} 道题\n')
        print('💡 建议：用 LLM 或人工批量重写这些 explanation，去掉元评论')
        print('   工具：python scripts/review/21-check-consistency.py --fix-traces\n')
        exit_code |= 2
    else:
        print('✅ 所有解析都很干净\n')

    print('=' * 70)
    if exit_code == 0:
        print('🎉 题库数据完全健康！')
    else:
        print(f'⚠️  退出码 {exit_code}（1=不一致, 2=有痕迹, 3=两者都有）')
    print('=' * 70)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
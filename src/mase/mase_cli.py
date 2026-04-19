import sys
from contextlib import closing

from mase_tools.memory.db_core import PROFILE_TEMPLATES, get_connection


def print_menu():
    print("\n" + "="*40)
    print(" MASE Memory CLI (SQLite Direct Control)")
    print("="*40)
    print("1. 浏览当前所有的核心记忆 (Entity Facts)")
    print("2. 浏览指定类别的核心记忆")
    print("3. 添加或修改核心记忆 (Upsert)")
    print("4. 删除一条核心记忆")
    print("5. 搜索对话流水账 (Event Logs)")
    print("6. 查看最近的 10 条流水账")
    print("0. 退出")
    print("="*40)

def show_facts(category=None):
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        if category:
            cursor.execute('SELECT * FROM entity_state WHERE category = ? ORDER BY updated_at DESC', (category,))
        else:
            cursor.execute('SELECT * FROM entity_state ORDER BY category, updated_at DESC')
        rows = cursor.fetchall()
        
        if not rows:
            print("\n[Empty] 暂无任何核心记忆！")
            return
            
        print(f"\n[OK] 找到 {len(rows)} 条记忆:")
        print(f"{'分类 (Category)':<20} | {'标识键 (Key)':<20} | {'值 (Value)':<40} | {'更新时间'}")
        print("-" * 105)
        for row in rows:
            print(f"{row['category']:<20} | {row['entity_key']:<20} | {row['entity_value']:<40} | {row['updated_at']}")

def upsert_fact():
    print("\n--- 可用的分类模板 ---")
    for idx, t in enumerate(PROFILE_TEMPLATES):
        print(f"[{idx+1}] {t}")
    
    try:
        cat_idx = int(input("\n选择分类的序号 (直接回车默认 general_facts): ") or 6) - 1
        category = PROFILE_TEMPLATES[cat_idx] if 0 <= cat_idx < len(PROFILE_TEMPLATES) else "general_facts"
    except ValueError:
        category = "general_facts"
        
    key = input("输入实体的标识键 (例如 'favorite_food'): ").strip()
    value = input("输入该实体的当前状态/值 (例如 '喜欢吃辣'): ").strip()
    
    if not key or not value:
        print("[Error] 键或值不能为空！")
        return
        
    with closing(get_connection()) as conn, conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO entity_state (category, entity_key, entity_value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(category, entity_key) 
            DO UPDATE SET 
                entity_value=excluded.entity_value, 
                updated_at=CURRENT_TIMESTAMP
        ''', (category, key, value))
    print(f"\n[OK] 成功将事实 [{category}.{key}] 设为: {value}")

def delete_fact():
    category = input("请输入要删除事实的分类 (Category): ").strip()
    key = input("请输入要删除事实的键 (Key): ").strip()
    
    with closing(get_connection()) as conn, conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM entity_state WHERE category = ? AND entity_key = ?', (category, key))
        if cursor.rowcount > 0:
            print(f"\n[OK] 成功删除记忆 [{category}.{key}]！")
        else:
            print(f"\n[Error] 未找到匹配的记忆: [{category}.{key}]")

def search_logs():
    keyword = input("\n输入你要搜索的流水账关键词: ").strip()
    if not keyword:
        return
        
    from mase_tools.memory.db_core import search_event_log
    results = search_event_log([keyword], limit=10)
    
    if not results:
        print(f"\n[Empty] 未在历史流水账中找到与 '{keyword}' 相关的内容。")
        return
        
    print(f"\n[OK] 找到 {len(results)} 条记录:")
    for r in results:
        role = r['role'].upper()
        content = r['content'][:80] + '...' if len(r['content']) > 80 else r['content']
        print(f"[{r['timestamp']}] {role}: {content}")

def show_recent_logs():
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM memory_log ORDER BY timestamp DESC LIMIT 10')
        rows = cursor.fetchall()
        
        if not rows:
            print("\n[Empty] 暂无对话流水账！")
            return
            
        print("\n[OK] 最近的 10 条对话记录:")
        for r in reversed(rows):
            role = r['role'].upper()
            content = r['content'][:80] + '...' if len(r['content']) > 80 else r['content']
            print(f"[{r['timestamp']}] {role}: {content}")

def main():
    while True:
        print_menu()
        choice = input("请选择操作 (0-6): ").strip()
        
        if choice == '1':
            show_facts()
        elif choice == '2':
            cat = input("请输入指定的类别名 (如 user_preferences): ").strip()
            show_facts(category=cat)
        elif choice == '3':
            upsert_fact()
        elif choice == '4':
            delete_fact()
        elif choice == '5':
            search_logs()
        elif choice == '6':
            show_recent_logs()
        elif choice == '0':
            print("再见！")
            sys.exit(0)
        else:
            print("无效的选择，请重试。")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已安全退出。")
        sys.exit(0)
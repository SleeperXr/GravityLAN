import asyncio
import sqlite3
import os

async def check_db():
    db_path = "data/homelan.db"
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Tables:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for table in tables:
        print(f"- {table[0]}")
        cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
        count = cursor.fetchone()[0]
        print(f"  Count: {count}")
        
        if "setting" in table[0]:
            cursor.execute(f"SELECT * FROM {table[0]}")
            rows = cursor.fetchall()
            for row in rows:
                print(f"    {row}")
    
    conn.close()

if __name__ == "__main__":
    asyncio.run(check_db())

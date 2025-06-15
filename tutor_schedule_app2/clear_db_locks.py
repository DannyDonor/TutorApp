"""
Скрипт для очистки блокировок базы данных
"""

import sqlite3
import os
import config

def clear_db_locks():
    """Очищает блокировки базы данных"""
    try:
        # Попытка подключиться к базе данных
        conn = sqlite3.connect(config.DB_NAME, timeout=1)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE);')
        conn.execute('PRAGMA optimize;')
        conn.close()
        print("✅ Блокировки базы данных очищены")
    except Exception as e:
        print(f"❌ Ошибка при очистке блокировок: {e}")
        
        # Проверяем, есть ли файлы блокировок
        db_files = [
            config.DB_NAME + '-wal',
            config.DB_NAME + '-shm',
            config.DB_NAME + '-journal'
        ]
        
        for file in db_files:
            if os.path.exists(file):
                try:
                    os.remove(file)
                    print(f"🗑️ Удален файл блокировки: {file}")
                except Exception as e:
                    print(f"❌ Не удалось удалить {file}: {e}")

if __name__ == '__main__':
    print("=== Очистка блокировок базы данных ===")
    clear_db_locks()
    print("=== Готово ===")
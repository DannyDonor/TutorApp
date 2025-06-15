#!/usr/bin/env python3
"""
Главный файл для запуска TutorApp
Координирует работу веб-приложения и телеграм бота
"""

import os
import sys
import time
import signal
from threading import Thread
from database import Session
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Глобальные переменные для управления процессами
web_thread = None
tg_thread = None
shutdown_flag = False

@contextmanager
def session_scope():
    """Контекстный менеджер для работы с сессией БД"""
    session = Session()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        raise e
    finally:
        session.close()

def check_database():
    """Проверяет доступность базы данных"""
    try:
        with session_scope() as session:
            # Простой тест подключения
            session.execute("SELECT 1")
        print("✅ База данных доступна")
        return True
    except Exception as e:
        print(f"❌ Ошибка подключения к базе данных: {e}")
        return False

def run_web_app():
    """Запускает веб-приложение"""
    global shutdown_flag
    try:
        print("🌐 Запуск веб-приложения...")
        from main_web import app
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        print(f"❌ Ошибка веб-приложения: {e}")
        shutdown_flag = True

def run_telegram_bot():
    """Запускает Telegram бота"""
    global shutdown_flag
    try:
        print("🤖 Запуск Telegram бота...")
        from main_tg import start_bot
        start_bot()
    except Exception as e:
        print(f"❌ Ошибка Telegram бота: {e}")
        shutdown_flag = True

def signal_handler(signum, frame):
    """Обработчик сигналов для корректного завершения"""
    global shutdown_flag
    print(f"\n⚠️ Получен сигнал {signum}. Завершение работы...")
    shutdown_flag = True

def main():
    """Главная функция"""
    global web_thread, tg_thread, shutdown_flag
    
    print("🚀 TutorApp - Система управления репетиторством")
    print("=" * 50)
    
    # Проверяем базу данных
    if not check_database():
        print("💡 Попробуйте запустить migrate_db.py для настройки базы данных")
        return 1
    
    # Настраиваем обработчик сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Запускаем веб-приложение в отдельном потоке
        web_thread = Thread(target=run_web_app, daemon=True)
        web_thread.start()
        
        # Даем время веб-приложению запуститься
        time.sleep(2)
        
        # Запускаем Telegram бота в отдельном потоке
        tg_thread = Thread(target=run_telegram_bot, daemon=True)
        tg_thread.start()
        
        print("✅ Все сервисы запущены!")
        print("\n📱 Доступ:")
        print("   • Веб-интерфейс: http://localhost:5000")
        print("   • Telegram бот: работает в фоне")
        print("\n⌨️ Нажмите Ctrl+C для остановки")
        
        # Главный цикл мониторинга
        while not shutdown_flag:
            time.sleep(1)
            
            # Проверяем состояние потоков
            if web_thread and not web_thread.is_alive():
                print("⚠️ Веб-приложение остановлено")
                break
                
            if tg_thread and not tg_thread.is_alive():
                print("⚠️ Telegram бот остановлен")
                break
    
    except KeyboardInterrupt:
        print("\n⚠️ Получен сигнал прерывания")
    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
    finally:
        print("\n🛑 Остановка сервисов...")
        shutdown_flag = True
        
        # Ждем завершения потоков
        if web_thread and web_thread.is_alive():
            web_thread.join(timeout=5)
        if tg_thread and tg_thread.is_alive():
            tg_thread.join(timeout=5)
        
        print("✅ Все сервисы остановлены")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
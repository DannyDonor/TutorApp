"""
Скрипт для создания пользователя-репетитора для тестирования
"""

from database import Session, User
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError

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

def create_test_tutor():
    """Создает тестового репетитора"""
    print("=== Создание тестового репетитора ===")
    
    try:
        with session_scope() as session:
            # Проверяем, есть ли уже такой репетитор
            existing_tutor = session.query(User).filter_by(username='tutor1').first()
            if existing_tutor:
                print("✅ Репетитор 'tutor1' уже существует")
                print(f"   Email: {existing_tutor.email}")
                print(f"   Статус: {'одобрен' if existing_tutor.is_approved else 'ожидает одобрения'}")
                return True
            
            # Создаем нового репетитора
            tutor = User(
                username='tutor1',
                email='tutor1@example.com',
                role='tutor',
                is_approved=True  # Сразу одобряем для тестирования
            )
            tutor.set_password('tutor123')
            session.add(tutor)
            session.commit()
            
            print("✅ Создан тестовый репетитор:")
            print("   Логин: tutor1")
            print("   Пароль: tutor123")
            print("   Email: tutor1@example.com")
            print("   Статус: одобрен")
            
            return True
            
    except Exception as e:
        print(f"❌ Ошибка создания репетитора: {e}")
        return False

def create_second_tutor():
    """Создает второго тестового репетитора"""
    print("\n=== Создание второго тестового репетитора ===")
    
    try:
        with session_scope() as session:
            # Проверяем, есть ли уже такой репетитор
            existing_tutor = session.query(User).filter_by(username='tutor2').first()
            if existing_tutor:
                print("✅ Репетитор 'tutor2' уже существует")
                return True
            
            # Создаем второго репетитора
            tutor = User(
                username='tutor2',
                email='tutor2@example.com',
                role='tutor',
                is_approved=True
            )
            tutor.set_password('tutor123')
            session.add(tutor)
            session.commit()
            
            print("✅ Создан второй тестовый репетитор:")
            print("   Логин: tutor2")
            print("   Пароль: tutor123")
            print("   Email: tutor2@example.com")
            
            return True
            
    except Exception as e:
        print(f"❌ Ошибка создания второго репетитора: {e}")
        return False

if __name__ == '__main__':
    # Проверяем миграции
    try:
        from migrate_db import check_database_structure, quick_fix
        
        needs_migration, missing_columns = check_database_structure()
        if needs_migration:
            print("⚠️ База данных требует обновления...")
            if not quick_fix():
                print("❌ Не удалось обновить БД. Запустите migrate_db.py")
                exit(1)
    except Exception as e:
        print(f"⚠️ Ошибка проверки миграции: {e}")
    
    success1 = create_test_tutor()
    success2 = create_second_tutor()
    
    if success1 and success2:
        print("\n🎉 Все тестовые репетиторы созданы успешно!")
        print("\nТеперь вы можете:")
        print("1. Войти как admin/admin123 для управления")
        print("2. Войти как tutor1/tutor123 или tutor2/tutor123 для работы репетитором")
        print("3. Создать студентов и привязать их к репетиторам")
    else:
        print("\n❌ Не удалось создать всех репетиторов")
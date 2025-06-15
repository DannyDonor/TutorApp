#!/usr/bin/env python3
"""
Скрипт для настройки тестового курса с заданиями
"""

from database import (Session, Course, CourseModule, CourseLesson, 
                     CourseAssignment, CourseEnrollment, Student, LessonBlock)
import json

def setup_test_course():
    with Session() as session:
        # Проверяем, есть ли курс
        course = session.query(Course).filter_by(title="Тестовый курс").first()
        if not course:
            print("❌ Курс 'Тестовый курс' не найден")
            return
        
        print(f"✅ Найден курс: {course.title}")
        
        # Проверяем, есть ли модули
        modules = session.query(CourseModule).filter_by(course_id=course.id).all()
        if not modules:
            print("📚 Создаем тестовый модуль...")
            module = CourseModule(
                course_id=course.id,
                title="Основы",
                description="Первый модуль курса",
                order_index=1
            )
            session.add(module)
            session.commit()
            modules = [module]
        
        module = modules[0]
        print(f"✅ Модуль: {module.title}")
        
        # Проверяем, есть ли уроки
        lessons = session.query(CourseLesson).filter_by(module_id=module.id).all()
        if not lessons:
            print("📖 Создаем тестовые уроки...")
            
            # Урок 1
            lesson1 = CourseLesson(
                module_id=module.id,
                title="Урок 1: Введение",
                description="Первый урок курса",
                order_index=1
            )
            session.add(lesson1)
            session.commit()
            
            # Добавляем блоки к уроку 1
            block1 = LessonBlock(
                lesson_id=lesson1.id,
                block_type='text',
                title='Добро пожаловать!',
                content='<p>Добро пожаловать на курс! В этом уроке мы изучим основы.</p><p>Прочитайте материал и выполните задание.</p>',
                order_index=1
            )
            session.add(block1)
            
            # Добавляем задание к уроку 1
            assignment1 = CourseAssignment(
                lesson_id=lesson1.id,
                title="Знакомство",
                description="Расскажите о себе: ваше имя, цели изучения и что вы ожидаете от курса.",
                max_points=10
            )
            session.add(assignment1)
            
            # Урок 2
            lesson2 = CourseLesson(
                module_id=module.id,
                title="Урок 2: Основы",
                description="Второй урок курса",
                order_index=2
            )
            session.add(lesson2)
            session.commit()
            
            # Добавляем блоки к уроку 2
            block2 = LessonBlock(
                lesson_id=lesson2.id,
                block_type='text',
                title='Теоретический материал',
                content='<p>В этом уроке мы изучим основные концепции.</p><p>Важно понимать следующие моменты:</p><ul><li>Первый пункт</li><li>Второй пункт</li><li>Третий пункт</li></ul>',
                order_index=1
            )
            session.add(block2)
            
            # Добавляем задание к уроку 2
            assignment2 = CourseAssignment(
                lesson_id=lesson2.id,
                title="Практическое задание",
                description="Опишите, как бы вы применили изученный материал на практике. Приведите конкретные примеры.",
                max_points=20
            )
            session.add(assignment2)
            
            session.commit()
            lessons = [lesson1, lesson2]
        
        print(f"✅ Уроков в модуле: {len(lessons)}")
        
        # Проверяем записи студентов
        enrollments = session.query(CourseEnrollment).filter_by(course_id=course.id).all()
        if not enrollments:
            print("👥 Добавляем студентов к курсу...")
            # Находим студентов репетитора
            students = session.query(Student).filter_by(tutor_id=course.tutor_id).all()
            
            for student in students:
                enrollment = CourseEnrollment(
                    course_id=course.id,
                    student_id=student.id,
                    current_lesson_id=lessons[0].id,  # Первый урок доступен
                    completed_lessons='[]'
                )
                session.add(enrollment)
                print(f"   ➕ Добавлен студент: {student.full_name}")
            
            session.commit()
            enrollments = session.query(CourseEnrollment).filter_by(course_id=course.id).all()
        
        print(f"✅ Студентов записано: {len(enrollments)}")
        
        # Показываем статистику
        print("\n📊 Статистика курса:")
        print(f"   Название: {course.title}")
        print(f"   Модулей: {len(modules)}")
        print(f"   Уроков: {len(lessons)}")
        print(f"   Студентов: {len(enrollments)}")
        
        for enrollment in enrollments:
            current_lesson = enrollment.current_lesson
            print(f"   📚 {enrollment.student.full_name}: текущий урок - {current_lesson.title if current_lesson else 'Нет'}")

if __name__ == "__main__":
    setup_test_course()
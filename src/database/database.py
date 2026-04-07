from typing import Annotated

from fastapi import Depends
from sqlmodel import select
from sqlmodel import create_engine, SQLModel, Session

from .model import Course, CourseEvent, Module

DATABASE_URL = "sqlite:///database.db"

engine = create_engine(DATABASE_URL, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]


def insert_module_graph(module_data):
    """Insert newly discovered module, course, and event records."""
    with Session(engine) as session:
        inserted_any = False
        existing_module = session.exec(
            select(Module).where(Module.number == module_data.number)
        ).first()
        if existing_module is None:
            module = Module(
                name=module_data.name,
                number=module_data.number,
                path=module_data.path,
                responsible_person=module_data.responsible_person,
                duration_semesters=module_data.duration_semesters,
                credits=module_data.credits,
                start_semester=module_data.start_semester,
                frequency=module_data.frequency,
                goals=module_data.goals,
                content=module_data.content,
                exam_prerequisites=module_data.exam_prerequisites,
                prerequisites=module_data.prerequisites,
            )
            session.add(module)
            session.flush()
            if module.id is None:
                raise RuntimeError("Failed to assign module id after flush")
            module_id = module.id
            inserted_any = True
        else:
            module = existing_module
            module_id = module.id
            if module_id is None:
                raise RuntimeError("Loaded module has no id")

        for course_data in module_data.courses:
            course = session.exec(
                select(Course).where(
                    Course.name == course_data.name,
                    Course.number == course_data.number,
                    Course.module_id == module.id,
                    Course.staff == course_data.staff,
                    Course.type == course_data.type,
                    Course.weekly_hours == course_data.weekly_hours,
                    Course.language == course_data.language,
                )
            ).first()
            if course is None:
                course = Course(
                    name=course_data.name,
                    number=course_data.number,
                    module_id=module_id,
                    staff=course_data.staff,
                    type=course_data.type,
                    weekly_hours=course_data.weekly_hours,
                    language=course_data.language,
                )
                session.add(course)
                session.flush()
                if course.id is None:
                    raise RuntimeError("Failed to assign course id after flush")
                course_id = course.id
                inserted_any = True
            else:
                course_id = course.id
                if course_id is None:
                    raise RuntimeError("Loaded course has no id")

            for event_data in course_data.events:
                existing_event = session.exec(
                    select(CourseEvent).where(
                        CourseEvent.course_id == course_id,
                        CourseEvent.number == event_data.number,
                        CourseEvent.event_date == event_data.event_date,
                        CourseEvent.start_time == event_data.start_time,
                        CourseEvent.end_time == event_data.end_time,
                        CourseEvent.location == event_data.location,
                        CourseEvent.staff == event_data.staff,
                    )
                ).first()
                if existing_event is not None:
                    continue

                event = CourseEvent(
                    course_id=course_id,
                    number=event_data.number,
                    event_date=event_data.event_date,
                    start_time=event_data.start_time,
                    end_time=event_data.end_time,
                    location=event_data.location,
                    staff=event_data.staff,
                )
                session.add(event)
                inserted_any = True

        session.commit()
        return inserted_any

from __future__ import annotations

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel


class Module(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    number: str = Field(index=True)
    path: list[str]
    responsible_person: str = ""
    duration_semesters: int = 0
    credits: float = 0.0
    start_semester: str = ""
    frequency: str = ""
    goals: str = ""
    content: str = ""
    exam_prerequisites: str = ""
    prerequisites: dict[str, str]
    courses: list[Course] = Relationship(back_populates="module")


class Course(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    module_id: int = Field(foreign_key="module.id", index=True)
    staff: list[str]
    type: str = ""
    weekly_hours: int = 0
    language: str = ""

    module: Module = Relationship(back_populates="courses")
    events: list[CourseEvent] = Relationship(back_populates="course")


class CourseEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    number: str = ""
    date: str = ""
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    staff: list[str]
    course: Course = Relationship(back_populates="events")

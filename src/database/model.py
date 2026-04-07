from datetime import time, date

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel


class Module(SQLModel, table=True):
    """
    A university module (Lehrveranstaltung) as listed in AlmaWeb.

    One module groups one or more :class:`Course` (event type) instances and carries the authoritative academic metadata such as credits, prerequisites, and the curriculum path.
    """

    id: int | None = Field(default=None, primary_key=True) # Primary key, auto-incremented by the database
    name: str
    number: str = Field(index=True)
    path: list[str] = Field(sa_column=Column(JSON)) # The path in the original navigation structure, e.g. ["Root","Informatik","Informatik (Bachelor of Science)","Pflichtmodule (empfohlen für das 6. Fachsemester)"]
    responsible_person: str = ""
    duration_semesters: int = 0
    credits: float = 0.0
    start_semester: str = ""
    frequency: str = ""
    goals: str = ""
    content: str = ""
    exam_prerequisites: str = ""
    prerequisites: dict[str, str] = Field(sa_column=Column(JSON))

    courses: list["Course"] = Relationship(back_populates="module")


class Course(SQLModel, table=True):
    """
    A single course within a :class:`Module`.  
    It is more similar to a single event type or group of module with contains multiple scheduled occurrences, e.g. a lecture with multiple weekly sessions.

    A course is the schedulable unit: it has a type, a weekly hour count, a language, and zero or more concrete :class:`CourseEvent` occurrences.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    number: str = ""
    staff: list[str] = Field(sa_column=Column(JSON))
    type: str = ""
    weekly_hours: int = 0
    language: str = ""

    module_id: int = Field(foreign_key="module.id", index=True)

    module: "Module" = Relationship(back_populates="courses")
    events: list["CourseEvent"] = Relationship(back_populates="course")


class CourseEvent(SQLModel, table=True):
    """
    A single scheduled occurrence of a :class:`Course`.

    Each event represents one entry in the timetable: a specific date, time slot, room, and set of staff members.
    """

    id: int | None = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    number: str = ""
    event_date: date
    start_time: time
    end_time: time
    location: str = ""
    staff: list[str] = Field(sa_column=Column(JSON)) 
    course: "Course" = Relationship(back_populates="events")

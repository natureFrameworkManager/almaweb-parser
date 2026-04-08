from datetime import date, time
from typing import Any

from pydantic import BaseModel, ConfigDict


class ModuleParentSchema(BaseModel):
	id: int
	name: str
	number: str
	path: list[str]
	responsible_person: str
	duration_semesters: int
	credits: float
	start_semester: str
	frequency: str
	goals: str
	content: str
	exam_prerequisites: str
	prerequisites: dict[str, str]


class EventChildSchema(BaseModel):
	id: int
	course_id: int
	number: str
	event_date: date
	start_time: time
	end_time: time
	location: str
	staff: list[str]


class CourseSchema(BaseModel):
	id: int
	name: str
	number: str
	staff: list[str]
	type: str
	weekly_hours: int
	language: str
	module_id: int


class CourseWithRelationsSchema(CourseSchema):
	module: ModuleParentSchema | None
	events: list[EventChildSchema]


class CourseSelectedFieldsSchema(BaseModel):
	# Selected-field responses are dynamic and may also include related data.
	model_config = ConfigDict(extra="allow")


class CourseListResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[CourseSchema]


class CourseListWithRelationsResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[CourseWithRelationsSchema]


class CourseListSelectedFieldsResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[CourseSelectedFieldsSchema]


CourseListResponseModel = (
	CourseListResponseSchema
	| CourseListWithRelationsResponseSchema
	| CourseListSelectedFieldsResponseSchema
)

CourseDetailResponseModel = (
	CourseSchema
	| CourseWithRelationsSchema
	| CourseSelectedFieldsSchema
)

from datetime import date, time

from pydantic import BaseModel, ConfigDict


class EventChildSchema(BaseModel):
	id: int
	course_id: int
	number: str
	event_date: date
	start_time: time
	end_time: time
	location: str
	staff: list[str]


class CourseChildSchema(BaseModel):
	id: int
	name: str
	number: str
	staff: list[str]
	type: str
	weekly_hours: int
	language: str
	module_id: int
	events: list[EventChildSchema]


class ModuleSchema(BaseModel):
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


class ModuleWithChildrenSchema(ModuleSchema):
	courses: list[CourseChildSchema]


class ModuleSelectedFieldsSchema(BaseModel):
	# Selected-field responses are dynamic and may also include related data.
	model_config = ConfigDict(extra="allow")


class ModuleListResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[ModuleSchema]


class ModuleListWithChildrenResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[ModuleWithChildrenSchema]


class ModuleListSelectedFieldsResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[ModuleSelectedFieldsSchema]


ModuleListResponseModel = (
	ModuleListResponseSchema
	| ModuleListWithChildrenResponseSchema
	| ModuleListSelectedFieldsResponseSchema
)

ModuleDetailResponseModel = ModuleSchema | ModuleWithChildrenSchema | ModuleSelectedFieldsSchema

from datetime import date, time

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


class CourseParentSchema(BaseModel):
	id: int
	name: str
	number: str
	staff: list[str]
	type: str
	weekly_hours: int
	language: str
	module_id: int
	module: ModuleParentSchema | None


class EventSchema(BaseModel):
	id: int
	course_id: int
	number: str
	event_date: date
	start_time: time
	end_time: time
	location: str
	staff: list[str]


class EventWithRelationsSchema(EventSchema):
	course: CourseParentSchema | None
	module: ModuleParentSchema | None


class EventSelectedFieldsSchema(BaseModel):
	# Selected-field responses are dynamic and may also include related data.
	model_config = ConfigDict(extra="allow")


class EventListResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[EventSchema]


class EventListWithRelationsResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[EventWithRelationsSchema]


class EventListSelectedFieldsResponseSchema(BaseModel):
	count: int
	page: int
	limit: int | None
	total_pages: int | None
	items: list[EventSelectedFieldsSchema]


EventListResponseModel = (
	EventListResponseSchema
	| EventListWithRelationsResponseSchema
	| EventListSelectedFieldsResponseSchema
)

EventDetailResponseModel = EventSchema | EventWithRelationsSchema | EventSelectedFieldsSchema

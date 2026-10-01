from datetime import date
from uuid import UUID
from pydantic import BaseModel, Field
class Login(BaseModel): email:str; password:str
class CourseIn(BaseModel): name:str=Field(min_length=1,max_length=160); code:str|None=None; term:str|None=None
class CourseOut(CourseIn): id:UUID
class Proposal(BaseModel): title:str=Field(min_length=1,max_length=240); description:str=""; due_date:date|None=None; review_required:bool=False
class ActivityOut(Proposal): id:UUID; course_id:UUID; document_id:UUID|None; status:str
class ConfirmIn(BaseModel): document_id:UUID; activities:list[Proposal]

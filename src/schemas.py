from pydantic import BaseModel


class DocumentAnalysis(BaseModel):
    case_name: str | None = None
    case_number: str | None = None
    court_name: str | None = None
    hearing_date: str | None = None
    hearing_time: str | None = None
    hearing_location: str | None = None
    motion_name: str | None = None
    motion_summary: str | None = None

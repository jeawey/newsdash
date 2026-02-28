from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    source_name: str
    source_domain: str
    sector: str
    subtopic: str
    summary: str
    published_at: datetime
    snapshot_date: date
    score: float
    heat_score: float
    run_type: str


class DashboardResponse(BaseModel):
    snapshot_date: date
    sectors: dict[str, list[StoryOut]]
    top_stories: list[StoryOut]

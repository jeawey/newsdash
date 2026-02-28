from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawStory:
    sector: str
    subtopic: str
    title: str
    url: str
    source_name: str
    source_domain: str
    summary: str
    published_at: datetime


@dataclass
class ScoredStory(RawStory):
    score: float
    heat_score: float
    fingerprint: str
    mentions: int

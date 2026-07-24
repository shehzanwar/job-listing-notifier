from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    url: str
    req_id: str
    posted_date: str
    description: str = ""
    department: str = ""
    raw_json: Optional[dict] = None

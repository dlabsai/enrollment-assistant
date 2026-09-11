from datetime import datetime
from typing import Annotated

from fastapi import HTTPException
from pydantic import AwareDatetime

AwareTimestamp = Annotated[datetime, AwareDatetime]


def validate_time_range(
    start: datetime | None,
    end: datetime | None,
    end_before: datetime | None = None,
    *,
    detail: str = "Invalid time range",
) -> None:
    """An inclusive start with either an inclusive or an exclusive end."""
    if end is not None and end_before is not None:
        raise HTTPException(status_code=400, detail="Choose only one end boundary")
    if start is not None and (
        (end is not None and start > end) or (end_before is not None and start >= end_before)
    ):
        raise HTTPException(status_code=400, detail=detail)

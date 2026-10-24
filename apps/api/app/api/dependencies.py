"""Shared FastAPI dependencies for application state."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.clock import Clock
from app.core.settings import Settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


AppClock = Annotated[Clock, Depends(get_clock)]


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(get_settings)]

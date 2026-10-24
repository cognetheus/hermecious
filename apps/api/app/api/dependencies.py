"""Shared FastAPI dependencies for application state."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.clock import Clock


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


AppClock = Annotated[Clock, Depends(get_clock)]

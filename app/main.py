"""FastAPI 入口。"""

from __future__ import annotations

from fastapi import FastAPI

from .renderer import render
from .schemas import RenderRequest, RenderResponse

app = FastAPI(
    title="电子琴发声区间 API",
    version="1.0.0",
    description="把按键/踏板事件流渲染为每个音的实际发声起止毫秒区间。",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/render", response_model=RenderResponse)
def post_render(request: RenderRequest) -> dict:
    return render(request.end_ms, request.events)

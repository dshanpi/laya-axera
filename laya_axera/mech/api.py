"""Per-session serialization, bounded memory, explicit simulation ticks and pause."""

import threading
import time
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .game import ACTIONS, MechGame
from .policy import decide


class NewBody(BaseModel):
    seed: int = Field(default=42, ge=0, le=2147483647)
    difficulty: Literal["training", "challenge"] = "training"
    model: Optional[str] = None


class SessionBody(BaseModel):
    session: str
    revision: int = Field(ge=0)


class CommandBody(SessionBody):
    text: str = Field(min_length=1, max_length=120)


class TickBody(SessionBody):
    dt: float = Field(default=0.25, gt=0, le=0.5, allow_inf_nan=False)


class PauseBody(SessionBody):
    playing: bool


class EventBody(SessionBody):
    event: Literal["enemy", "armor", "cover"]


class ManualBody(SessionBody):
    action: Literal["attack", "defend", "retreat", "hold"]


class GraphicsBody(BaseModel):
    session: str
    mode: Literal["webgl2", "2d", "lost"]
    fps: float = Field(ge=0, le=500, allow_inf_nan=False)
    frames: int = Field(ge=0, le=100000)
    width: int = Field(ge=0, le=16384)
    height: int = Field(ge=0, le=16384)
    quality: Literal["low", "balanced", "high"]


def mech_router(registry):
    router = APIRouter(prefix="/api/mech")
    sessions, lock = {}, threading.Lock()

    def get(sid):
        with lock:
            entry = sessions.get(sid)
        if entry is None:
            raise HTTPException(404, "训练会话已过期，请重置训练。")
        return entry

    def check(entry, revision):
        if entry["revision"] != revision:
            raise HTTPException(409, "训练状态已改变，请刷新状态后再操作。")

    def view(entry):
        return {
            "state": entry["game"].snapshot(),
            "revision": entry["revision"],
            "playing": entry["playing"] and entry["game"].status == "active",
            "decision": entry["decision"],
            "history": list(entry["history"]),
            "npu_calls": entry["npu_calls"],
        }

    def record(entry, item):
        entry["history"].append({"time": round(entry["game"].time, 2), **item})
        entry["history"] = entry["history"][-64:]

    @router.post("/graphics")
    def graphics(body: GraphicsBody, request: Request):
        entry = get(body.session)
        with entry["lock"]:
            # Local, bounded diagnostics; no images, commands or hardware fingerprints.
            entry["graphics"] = {
                **body.model_dump(exclude={"session"}),
                "user_agent": request.headers.get("user-agent", "")[:256],
                "received_at": time.time(),
            }
        return {"ok": True}

    @router.get("/diagnostics/renderers")
    def renderers():
        with lock:
            entries = list(sessions.values())
        result = []
        for entry in entries:
            with entry["lock"]:
                if "graphics" in entry:
                    result.append(entry["graphics"].copy())
        return result

    @router.post("/new")
    def new(body: NewBody):
        if body.model and body.model not in registry.checkpoints:
            raise HTTPException(404, "Unknown model")
        entry = {
            "game": MechGame(body.seed, body.difficulty),
            "model": body.model,
            "revision": 0,
            "playing": False,
            "lock": threading.Lock(),
            "created": time.monotonic(),
            "history": [],
            "decision": None,
            "npu_calls": 0,
        }
        sid = uuid.uuid4().hex
        with lock:
            if len(sessions) >= 12:
                for old in sorted(sessions, key=lambda k: sessions[k]["created"]):
                    candidate = sessions[old]
                    if candidate["lock"].acquire(blocking=False):
                        del sessions[old]
                        candidate["lock"].release()
                        break
                else:
                    raise HTTPException(503, "训练会话繁忙，请稍后再试。")
            sessions[sid] = entry
        return {"session": sid, **view(entry)}

    @router.get("/{sid}")
    def read(sid: str):
        entry = get(sid)
        with entry["lock"]:
            return view(entry)

    @router.post("/command")
    def command(body: CommandBody):
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "请输入机甲操控指令。")
        entry = get(body.session)
        with entry["lock"]:
            check(entry, body.revision)
            if entry["game"].status != "active":
                raise HTTPException(409, "训练已结束，请重置。")
            try:
                agent = registry.get(entry["model"])
                decision = decide(agent, text, entry["game"])
            except (ValueError, RuntimeError, FloatingPointError) as exc:
                raise HTTPException(503, str(exc)) from exc
            entry["game"].command(decision["action"])
            entry.update(decision=decision, playing=True)
            entry["revision"] += 1
            entry["npu_calls"] += 1
            record(entry, {"kind": "command", "decision": decision})
            return view(entry)

    @router.post("/manual")
    def manual(body: ManualBody):
        entry = get(body.session)
        with entry["lock"]:
            check(entry, body.revision)
            assert body.action in ACTIONS
            try:
                entry["game"].command(body.action)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            decision = {
                "source": "manual",
                "command": None,
                "action": body.action,
                "probabilities": None,
                "npu_ms": None,
                "engine": None,
                "request": None,
                "raw_answers": None,
                "model": None,
            }
            entry.update(decision=decision, playing=True)
            entry["revision"] += 1
            record(entry, {"kind": "command", "decision": decision})
            return view(entry)

    @router.post("/tick")
    def tick(body: TickBody):
        entry = get(body.session)
        with entry["lock"]:
            check(entry, body.revision)
            if entry["playing"] and entry["game"].status == "active":
                entry["game"].advance(body.dt)
                entry["revision"] += 1
            return view(entry)

    @router.post("/pause")
    def pause(body: PauseBody):
        entry = get(body.session)
        with entry["lock"]:
            check(entry, body.revision)
            entry["playing"] = body.playing and entry["game"].status == "active"
            entry["revision"] += 1
            return view(entry)

    @router.post("/event")
    def event(body: EventBody):
        entry = get(body.session)
        with entry["lock"]:
            check(entry, body.revision)
            try:
                entry["game"].inject(body.event)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            entry["revision"] += 1
            record(entry, {"kind": "event", "event": body.event})
            return view(entry)

    return router

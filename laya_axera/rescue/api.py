"""Bounded sessions with per-mission locking and optimistic revision checks."""

import threading
import time
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .game import DEFAULT_MISSION, RescueGame
from .policy import build_request, check_budget, decide


class NewBody(BaseModel):
    mode: Literal["laya", "rule", "human"] = "laya"
    model: Optional[str] = None
    seed: int = Field(default=42, ge=0, le=2147483647)
    scenario: Literal["standard", "storm", "low_fuel"] = "standard"
    guarded: bool = True
    mission: str = Field(default=DEFAULT_MISSION, min_length=1, max_length=80)


class StepBody(BaseModel):
    session: str
    revision: int = Field(ge=0)
    action: Optional[Literal["rescue", "evade", "refuel", "return"]] = None


class EventBody(BaseModel):
    session: str
    revision: int = Field(ge=0)
    event: Literal["storm", "leak"]


def rescue_router(registry):
    router = APIRouter(prefix="/api/rescue")
    sessions = {}
    sessions_lock = threading.Lock()

    def get_session(sid):
        with sessions_lock:
            entry = sessions.get(sid)
        if entry is None:
            raise HTTPException(404, "Mission expired; start a new mission")
        return entry

    def check_revision(entry, revision):
        if revision != entry["revision"]:
            raise HTTPException(409, "Stale mission revision; reload mission state")
        if entry["game"].status != "active":
            raise HTTPException(409, "Mission already ended")

    def view(entry):
        return {
            "state": entry["game"].snapshot(),
            "revision": entry["revision"],
            "mode": entry["body"].mode,
            "guarded": entry["body"].guarded,
            "stats": dict(entry["stats"]),
            "history": list(entry["history"]),
            "done": entry["game"].status != "active",
        }

    @router.post("/new")
    def new(body: NewBody):
        game = RescueGame(body.seed, body.scenario, body.mission.strip())
        if not game.mission:
            raise HTTPException(422, "Mission must not be blank")
        agent = registry.get(body.model) if body.mode == "laya" else None
        if agent:
            try:
                check_budget(agent, build_request(game))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        entry = {
            "game": game,
            "body": body,
            "agent": agent,
            "lock": threading.Lock(),
            "revision": 0,
            "created": time.monotonic(),
            "history": [],
            "stats": {"decisions": 0, "npu_calls": 0, "npu_ms_total": 0.0, "interventions": 0},
        }
        sid = uuid.uuid4().hex
        with sessions_lock:
            # Never evict a request that is in the middle of executing.
            if len(sessions) >= 16:
                for old in sorted(sessions, key=lambda k: sessions[k]["created"]):
                    candidate = sessions[old]
                    if candidate["lock"].acquire(blocking=False):
                        del sessions[old]
                        candidate["lock"].release()
                        break
                else:
                    raise HTTPException(503, "All mission slots are busy")
            sessions[sid] = entry
        return {"session": sid, **view(entry)}

    @router.get("/{sid}")
    def read(sid: str):
        entry = get_session(sid)
        with entry["lock"]:
            return view(entry)

    @router.post("/step")
    def step(body: StepBody):
        entry = get_session(body.session)
        with entry["lock"]:
            check_revision(entry, body.revision)
            game, config = entry["game"], entry["body"]
            if config.mode == "human" and body.action is None:
                raise HTTPException(422, "Manual mode requires an action")
            try:
                decision = decide(
                    game,
                    mode=config.mode,
                    guarded=config.guarded,
                    agent=entry["agent"],
                    manual=body.action,
                )
            except (ValueError, RuntimeError, FloatingPointError) as exc:
                # No rule fallback and no world advance on inference failure.
                raise HTTPException(503, str(exc)) from exc
            if decision["executed"] is None:
                game.status = "halted"
            else:
                game.step(decision["executed"])
            stats = entry["stats"]
            stats["decisions"] += 1
            stats["interventions"] += int(decision["intervened"])
            if config.mode == "laya":
                stats["npu_calls"] += 3
                stats["npu_ms_total"] += decision["npu_ms"]
            entry["revision"] += 1
            entry["history"].append(
                {
                    "kind": "decision",
                    "revision": entry["revision"],
                    "decision": decision,
                    "state": game.snapshot(),
                }
            )
            return {"decision": decision, **view(entry)}

    @router.post("/event")
    def event(body: EventBody):
        entry = get_session(body.session)
        with entry["lock"]:
            check_revision(entry, body.revision)
            if entry["game"].event_count >= 20:
                raise HTTPException(422, "Event limit reached for this mission")
            entry["game"].inject(body.event)
            entry["revision"] += 1
            entry["history"].append(
                {
                    "kind": "event",
                    "event": body.event,
                    "revision": entry["revision"],
                    "state": entry["game"].snapshot(),
                }
            )
            return view(entry)

    return router

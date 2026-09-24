"""Objective action costs go into Laya; no precomputed 'best action' is in the prompt."""

import math
import time

from ..common import build_prefix, to_internal
from .game import ACTIONS


def build_request(game):
    plans = game.plans()
    state = (
        f"The rescue ship has fuel {game.fuel}% and hull integrity {game.hull}%. "
        f"Storm intensity is {game.threat}%. {len(game.pods)} people need rescue. "
        f"{game.rescued} people aboard. "
        f"Mission: {game.mission}"
    )
    names = {
        "rescue": "Pick up a person",
        "evade": "Reduce storm by 40",
        "refuel": "Visit a fuel depot",
        "return": "Return to base",
    }
    criteria = {
        a: (
            f"{names[a]}; fuel cost {p['fuel_cost']}, damage {p['damage']}."
            if p["available"]
            else "Unavailable: no target or insufficient fuel."
        )
        for a, p in plans.items()
    }
    return {
        "state": state,
        "questions": {
            "action": {
                "type": "choice",
                "instructions": "Choose the next action to achieve the mission.",
                "criteria": criteria,
            },
            "risk": {
                "type": "score",
                "instructions": "Rate the current danger to the ship.",
                "criteria": ["Low", "Moderate", "Critical"],
            },
            "emergency": {"type": "noul", "instructions": "Should the ship return immediately?"},
        },
    }


def check_budget(agent, request):
    """Reject truncation rather than silently losing the user's mission or world state."""
    tokens = agent.tok(
        request["state"].replace(agent.tok.mask_token, " "), add_special_tokens=False
    )["input_ids"]
    counts = {}
    for name, q in request["questions"].items():
        prefix, _ = build_prefix(agent.tok, to_internal(q), agent.head_max_len)
        count = len(prefix) + len(tokens) + 1
        if count > agent.seq_len:
            raise ValueError("Mission exceeds model token budget; shorten the mission text")
        counts[name] = count
    return counts


def rule_action(game):
    """A labelled fixed-threshold baseline, not a substitute for failed inference."""
    plans = game.plans()
    allowed = game.allowed_actions()
    if not game.pods or game.hull < 22:
        preferred = "return"
    elif game.threat >= 45:
        preferred = "evade"
    elif game.fuel < 38 and plans["refuel"]["available"]:
        preferred = "refuel"
    else:
        preferred = "rescue"
    if preferred in allowed:
        return preferred
    return next((a for a in ("refuel", "return", "evade", "rescue") if a in allowed), preferred)


def decide(game, *, mode, guarded, agent=None, manual=None):
    started = time.perf_counter()
    request = build_request(game)
    result = {
        "mode": mode,
        "probabilities": None,
        "risk": None,
        "emergency": None,
        "npu_ms": None,
        "model": None,
        "engine": None,
        "input_tokens": None,
        "request": request,
        "raw_answers": None,
        "token_counts": None,
    }
    if mode == "laya":
        result["token_counts"] = check_budget(agent, request)
        output = agent.predict_request(request)
        answers = output["answers"]
        probabilities = answers["action"]["probabilities"]
        if set(probabilities) != set(ACTIONS):
            raise ValueError("Model returned unexpected action labels")
        values = [*probabilities.values(), answers["emergency"]["noul"]]
        if (
            any(not math.isfinite(v) or not 0 <= v <= 1 for v in values)
            or abs(sum(probabilities.values()) - 1) > 0.002
            or not math.isfinite(answers["risk"]["score"])
            or not 0 <= answers["risk"]["score"] <= 2
        ):
            raise ValueError("Invalid model output; no action executed")
        proposed = max(ACTIONS, key=probabilities.__getitem__)
        result.update(
            probabilities=probabilities,
            risk=answers["risk"]["score"],
            emergency=answers["emergency"]["noul"],
            raw_answers=answers,
            npu_ms=output["total_npu_latency_ms"],
            model=output["model"],
            engine=output["engine"],
            input_tokens=output["usage"]["input_tokens"],
        )
    elif mode == "rule":
        proposed = rule_action(game)
    elif mode == "human" and manual in ACTIONS:
        proposed = manual
    else:
        raise ValueError("Choose a valid mode and manual action")
    allowed = game.allowed_actions()
    executed = proposed
    reason = ""
    if guarded and proposed not in allowed:
        if allowed:
            executed = (
                max(allowed, key=result["probabilities"].__getitem__)
                if mode == "laya"
                else allowed[0]
            )
            reason = "原动作不可达、会损毁飞船或不足以保留返航燃料。"
        else:
            executed = None
            reason = "没有满足保护条件的动作，任务停止。"
    elif not game.plans()[proposed]["available"]:
        executed = None
        reason = "动作不可执行：缺少目标或燃料不足，任务停止。"
    result.update(
        proposed=proposed,
        executed=executed,
        allowed=allowed,
        intervened=guarded and executed != proposed,
        reason=reason,
        decision_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return result

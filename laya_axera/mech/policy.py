"""Classify the operator's instruction using Laya, without keyword dispatch."""

import math
import time

from ..common import build_prefix, to_internal
from .game import ACTIONS


def build_request(command, game):
    return {
        # Intent classification should not change when an unrelated armor or
        # energy number changes. The physics engine resolves the chosen action
        # against the current world only after the model returns.
        "state": f"Operator instruction: {command}",
        "questions": {
            "action": {
                "type": "choice",
                "instructions": "Which action does the operator request? Follow the final intent, including negation.",
                "criteria": {
                    "attack": "Attack the enemy. Advance and fire.",
                    "defend": "Defend. Raise the shield and block incoming fire.",
                    "retreat": "Retreat. Move away and take cover.",
                    "hold": "Hold position. Stop moving and firing.",
                },
            }
        },
    }


def decide(agent, command, game):
    started = time.perf_counter()
    request = build_request(command, game)
    q = to_internal(request["questions"]["action"])
    prefix, _ = build_prefix(agent.tok, q, agent.head_max_len)
    tokens = agent.tok(
        request["state"].replace(agent.tok.mask_token, " "), add_special_tokens=False
    )["input_ids"]
    if len(prefix) + len(tokens) + 1 > agent.seq_len:
        raise ValueError("输入超过模型长度限制，请缩短指令。")
    output = agent.predict_request(request)
    answer = output["answers"]["action"]
    probabilities = answer["probabilities"]
    if (
        set(probabilities) != set(ACTIONS)
        or any(not math.isfinite(v) or not 0 <= v <= 1 for v in probabilities.values())
        or abs(sum(probabilities.values()) - 1) > 0.002
    ):
        raise ValueError("模型返回无效概率，本次未执行动作。")
    action = max(ACTIONS, key=probabilities.__getitem__)
    return {
        "source": "laya",
        "command": command,
        "action": action,
        "probabilities": probabilities,
        "npu_ms": output["total_npu_latency_ms"],
        "decision_ms": round((time.perf_counter() - started) * 1000, 3),
        "request": request,
        "raw_answers": output["answers"],
        "model": output["model"],
        "engine": output["engine"],
        "input_tokens": output["usage"]["input_tokens"],
    }

"""Exercise real Laya decisions and arena behavior through a running server.

Run serially while browser training is paused. No mock agent or keyword fallback.
"""

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

CASES = [
    ("别开火，先保护自己。", "defend", "development"),
    ("继续进攻。", "attack", "development"),
    ("向敌人开火。", "attack", "development"),
    ("我不是让你撤退，继续进攻。", "attack", "development"),
    ("先撤到掩体后。", "retreat", "development"),
    ("撤离交战区。", "retreat", "development"),
    ("原地待命。", "hold", "development"),
    ("停下来，不要移动。", "hold", "development"),
    ("打开护盾，挡住炮火。", "defend", "development"),
    ("不要进攻，先防御。", "defend", "development"),
    ("不要防御了，集中火力攻击。", "attack", "development"),
    ("敌人太多了，先躲起来。", "retreat", "development"),
    ("停止射击，等我指令。", "hold", "development"),
    ("先别撤退，架盾挡住。", "defend", "development"),
    ("举起护盾保护机体。", "defend", "additional"),
    ("用火力压制前面的敌人。", "attack", "additional"),
    ("先找个地方躲避攻击。", "retreat", "additional"),
    ("在原来的位置等待。", "hold", "additional"),
    ("暂时不要冲锋，展开护盾。", "defend", "additional"),
    ("不用躲了，开始攻击对手。", "attack", "additional"),
    ("离敌人远一点，找掩体躲起来。", "retreat", "additional"),
    ("留在这里，等下一条命令。", "hold", "additional"),
]


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def call(self, path, body):
        request = urllib.request.Request(
            self.base + "/api/mech/" + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)

    def new(self, difficulty="training"):
        self.data = self.call("new", {"seed": 42, "difficulty": difficulty})
        self.session = self.data["session"]
        return self.data

    def mutate(self, path, **extra):
        self.data = self.call(
            path, {"session": self.session, "revision": self.data["revision"], **extra}
        )
        return self.data

    def ticks(self, seconds):
        for _ in range(round(seconds * 2)):
            if self.data["state"]["status"] != "active":
                break
            self.mutate("tick", dt=0.5)
        return self.data


def run(base):
    client = Client(base)
    rows = []
    for text, expected, group in CASES:
        client.new()
        started = time.perf_counter()
        result = client.mutate("command", text=text)
        wall_ms = (time.perf_counter() - started) * 1000
        decision = result["decision"]
        rows.append(
            {
                "command": text,
                "expected": expected,
                "group": group,
                "match": decision["action"] == expected,
                "http_ms": round(wall_ms, 3),
                **decision,
            }
        )
        client.mutate("pause", playing=False)
        print(text, "->", decision["action"], "match=", rows[-1]["match"], flush=True)
    behaviors = []
    for text, expected, seconds in [
        ("打开护盾，挡住炮火。", "defend", 6),
        ("先撤到掩体后。", "retreat", 8),
        ("原地待命。", "hold", 3),
        ("向敌人开火。", "attack", 20),
    ]:
        before = client.new()["state"]
        result = client.mutate("command", text=text)
        assert result["decision"]["action"] == expected, result["decision"]
        decision = result["decision"]
        result = client.ticks(seconds)
        state = result["state"]
        if expected == "defend":
            assert state["stats"]["blocked"] >= 2 and state["player"]["armor"] == 100
        elif expected == "retreat":
            assert not state["path"] and state["player"]["x"] != before["player"]["x"]
        elif expected == "hold":
            assert state["stats"]["shots"] == 0
            assert (state["player"]["x"], state["player"]["z"]) == (
                before["player"]["x"],
                before["player"]["z"],
            )
        elif expected == "attack":
            assert state["status"] == "won" and state["stats"]["kills"] == 1
        client.mutate("pause", playing=False)
        behaviors.append({"action": expected, "decision": decision, "state": state})
    # Continuous mixed command session with injected world changes.
    client.new("challenge")
    for event in ["enemy", "armor", "cover"]:
        client.mutate("event", event=event)
    mixed = []
    for text, seconds in [
        ("别开火，先保护自己。", 4),
        ("先撤到掩体后。", 5),
        ("原地待命。", 2),
        ("继续进攻。", 50),
    ]:
        result = client.mutate("command", text=text)
        mixed.append(result["decision"])
        client.ticks(seconds)
    client.mutate("pause", playing=False)
    mixed_state = client.data["state"]
    latencies = (
        [r["npu_ms"] for r in rows]
        + [b["decision"]["npu_ms"] for b in behaviors]
        + [m["npu_ms"] for m in mixed]
    )
    return {
        "tested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "method": "Real /api/mech/command, one Laya forward per instruction; explicit server physics ticks.",
        "classification": rows,
        "behaviors": behaviors,
        "mixed": {"decisions": mixed, "state": mixed_state},
        "summary": {
            "cases": len(rows),
            "matches": sum(r["match"] for r in rows),
            "npu_calls": len(latencies),
            "mean_npu_ms": statistics.mean(latencies),
            "min_npu_ms": min(latencies),
            "max_npu_ms": max(latencies),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--output", type=Path, default=Path("mech-results.json"))
    args = parser.parse_args()
    result = run(args.url)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))

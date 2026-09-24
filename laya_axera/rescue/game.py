"""Seeded, turn-based space rescue simulation. No model or rendering code here."""

import copy
import math
import random

ACTIONS = ("rescue", "evade", "refuel", "return")
LABELS = {"rescue": "救援", "evade": "避险", "refuel": "补给", "return": "返航"}
DEFAULT_MISSION = "Rescue people and keep enough fuel to return."


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


class RescueGame:
    """Each turn completes one trip; the browser animates its recorded trajectory.

    Threat is a sector-wide storm intensity (0..100), not a collision detector.
    Rescued people remain aboard until docking. Scoring never rewards model output.
    """

    def __init__(self, seed=42, scenario="standard", mission=DEFAULT_MISSION):
        if scenario not in ("standard", "storm", "low_fuel"):
            raise ValueError("Unknown scenario")
        self.seed = seed
        self.scenario = scenario
        self.mission = mission
        rng = random.Random(seed)
        self.base = {"x": 115, "y": 320}
        self.ship = dict(self.base)
        self.pods = [
            {"id": i + 1, "x": rng.randint(280, 900), "y": rng.randint(100, 535)} for i in range(6)
        ]
        self.depots = [
            {"id": 1, "x": 420, "y": 480, "stock": 1},
            {"id": 2, "x": 740, "y": 150, "stock": 1},
        ]
        self.fuel = 28 if scenario == "low_fuel" else 85
        self.hull = 100
        self.threat = 78 if scenario == "storm" else 18
        self.turn = 0
        self.rescued = 0
        self.delivered = 0
        self.status = "active"
        self.trail = [dict(self.ship)]
        self.last_action = None
        self.event_count = 0

    @staticmethod
    def travel_cost(start, end):
        return 3 + math.ceil(distance(start, end) / 45)

    def plans(self):
        pod = min(self.pods, key=lambda p: (distance(self.ship, p), p["id"]), default=None)
        depot = min(
            (d for d in self.depots if d["stock"]),
            key=lambda d: (distance(self.ship, d), d["id"]),
            default=None,
        )
        # Evasive navigation is deterministic; the model only selects the task.
        shelter = {
            "x": max(80, self.ship["x"] - 85),
            "y": max(70, min(550, self.ship["y"] + (65 if self.turn % 2 else -65))),
        }
        result = {}
        for action, target in (
            ("rescue", pod),
            ("evade", shelter),
            ("refuel", depot),
            ("return", self.base),
        ):
            dest = {k: target[k] for k in ("x", "y")} if target else dict(self.ship)
            cost = 4 if action == "evade" else self.travel_cost(self.ship, dest)
            damage = math.ceil(self.threat * (0.035 if action == "evade" else 0.18))
            # Docking in place requires no fuel or exposure.
            if action == "return" and distance(self.ship, self.base) < 1:
                cost, damage = 0, 0
            result[action] = {
                "destination": dest,
                "target_id": target.get("id") if target else None,
                "fuel_cost": cost,
                "damage": damage,
                "fuel_gain": 38 if action == "refuel" and target else 0,
                "available": target is not None and self.fuel >= cost,
                "return_reserve": self.travel_cost(dest, self.base),
            }
        return result

    def allowed_actions(self):
        """Optional guard: only exclude infeasible/fatal trips or lost return reserve."""
        allowed = []
        for action, plan in self.plans().items():
            remaining = min(100, self.fuel - plan["fuel_cost"] + plan["fuel_gain"])
            if (
                plan["available"]
                and self.hull > plan["damage"]
                and (action == "return" or remaining >= plan["return_reserve"])
            ):
                allowed.append(action)
        return allowed

    def step(self, action):
        if action not in ACTIONS:
            raise ValueError("Unknown action")
        if self.status != "active":
            raise ValueError("Mission already ended")
        plan = self.plans()[action]
        if not plan["available"]:
            raise ValueError("Action unavailable: no target or insufficient fuel")
        start = dict(self.ship)
        self.ship = dict(plan["destination"])
        self.fuel = min(100, self.fuel - plan["fuel_cost"] + plan["fuel_gain"])
        self.hull = max(0, self.hull - plan["damage"])
        self.turn += 1
        if self.hull == 0:
            self.status = "lost"
        elif action == "rescue":
            self.pods = [p for p in self.pods if p["id"] != plan["target_id"]]
            self.rescued += 1
        elif action == "refuel":
            next(d for d in self.depots if d["id"] == plan["target_id"])["stock"] -= 1
        elif action == "return":
            self.delivered = self.rescued
            self.status = "docked"
        if action == "evade":
            self.threat = max(0, self.threat - 40)
        else:
            self.threat = min(100, max(0, self.threat + (12 if self.turn % 3 == 0 else -3)))
        if self.status == "active":
            if not any(p["available"] for p in self.plans().values()):
                self.status = "stranded"
            elif self.turn >= 30:
                self.status = "timeout"
        self.last_action = {
            "action": action,
            "from": start,
            "to": dict(self.ship),
            "fuel_cost": plan["fuel_cost"],
            "damage": plan["damage"],
        }
        self.trail.append(dict(self.ship))
        return self.snapshot()

    def inject(self, event):
        if self.status != "active":
            raise ValueError("Mission already ended")
        if event == "storm":
            self.threat = min(100, self.threat + 55)
        elif event == "leak":
            self.fuel = max(0, self.fuel - 22)
            if not any(p["available"] for p in self.plans().values()):
                self.status = "stranded"
        else:
            raise ValueError("Unknown event")
        self.event_count += 1
        return self.snapshot()

    def snapshot(self):
        return copy.deepcopy(
            {
                "seed": self.seed,
                "scenario": self.scenario,
                "mission": self.mission,
                "ship": self.ship,
                "base": self.base,
                "pods": self.pods,
                "depots": self.depots,
                "fuel": self.fuel,
                "hull": self.hull,
                "threat": self.threat,
                "turn": self.turn,
                "rescued": self.rescued,
                "delivered": self.delivered,
                "score": self.delivered * 150,
                "status": self.status,
                "trail": self.trail,
                "last_action": self.last_action,
                "plans": self.plans(),
                "event_count": self.event_count,
            }
        )

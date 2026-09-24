"""Deterministic, bounded arena simulation. Each tick is authoritative on the server."""

import copy
import heapq
import math
import random

ACTIONS = ("attack", "defend", "retreat", "hold")
LABELS = {"attack": "进攻", "defend": "防御", "retreat": "撤退", "hold": "待命"}
LIMIT_X, LIMIT_Z = 16, 12
RADIUS = 0.7


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def intersects(start, end, box, padding=0):
    """Slab test on a 2D segment; prevents tunnelling through thin cover."""
    return contact(start, end, box, padding) is not None


def contact(start, end, box, padding=0):
    """Return entry fraction, so the nearest target/cover receives the shot."""
    low, high = 0.0, 1.0
    for axis, size in (("x", "w"), ("z", "d")):
        delta = end[axis] - start[axis]
        a = box[axis] - box[size] / 2 - padding
        b = box[axis] + box[size] / 2 + padding
        if abs(delta) < 1e-9:
            if not a <= start[axis] <= b:
                return None
        else:
            near, far = sorted(((a - start[axis]) / delta, (b - start[axis]) / delta))
            low, high = max(low, near), min(high, far)
            if low > high:
                return None
    return low


class MechGame:
    def __init__(self, seed=42, difficulty="training"):
        if difficulty not in ("training", "challenge"):
            raise ValueError("Unknown difficulty")
        self.seed, self.difficulty = seed, difficulty
        self.rng = random.Random(seed)
        self.time = 0.0
        self.action = "hold"
        self.status = "active"
        self.player = {
            "x": -7.0,
            "z": 5.0,
            "yaw": 2.25,
            "armor": 100.0,
            "energy": 100.0,
            "shield": False,
            "moving": False,
        }
        self.covers = [
            {"id": 1, "x": -3.0, "z": 1.0, "w": 3.0, "d": 1.6},
            {"id": 2, "x": 4.0, "z": -5.0, "w": 3.0, "d": 1.6},
            {"id": 3, "x": -9.0, "z": -5.0, "w": 2.6, "d": 1.6},
        ]
        self.enemies = []
        self.projectiles = []
        self.effects = []
        self.path = []
        self.shot_timer = 0.0
        self.shield_recharging = False
        self.sequence = 0
        self.event_count = 0
        self.stats = {"shots": 0, "hits": 0, "blocked": 0, "kills": 0, "damage_taken": 0.0}
        self.add_enemy()
        if difficulty == "challenge":
            self.add_enemy()

    def add_enemy(self):
        if len(self.enemies) >= 4:
            raise ValueError("最多同时保留 4 个训练对手，请重置训练。")
        positions = ((8, -3), (11, 5), (2, -9), (-10, -8))
        x, z = positions[len(self.enemies)]
        self.enemies.append(
            {
                "id": len(self.enemies) + 1,
                "x": float(x),
                "z": float(z),
                "armor": 72.0,
                "yaw": -0.8,
                "cooldown": 1.0 + self.rng.random() * 1.3,
            }
        )

    def alive(self):
        return [e for e in self.enemies if e["armor"] > 0]

    def visible(self, start, end):
        return not any(intersects(start, end, c) for c in self.covers)

    def free(self, point):
        if abs(point["x"]) > LIMIT_X - RADIUS or abs(point["z"]) > LIMIT_Z - RADIUS:
            return False
        return not any(intersects(point, point, c, RADIUS) for c in self.covers)

    def route(self, goal):
        """A* over a one-metre grid. Navigation never chooses the model's action."""
        start = (round(self.player["x"]), round(self.player["z"]))
        goal = (round(goal["x"]), round(goal["z"]))
        if not self.free({"x": goal[0], "z": goal[1]}):
            return []
        frontier = [(0.0, start)]
        previous, costs = {start: None}, {start: 0.0}
        while frontier:
            _, here = heapq.heappop(frontier)
            if here == goal:
                nodes = []
                while previous[here] is not None:
                    nodes.append({"x": float(here[0]), "z": float(here[1])})
                    here = previous[here]
                nodes.reverse()
                # Include the start centre only if reaching it doesn't cross cover.
                centre = {"x": float(start[0]), "z": float(start[1])}
                if distance(self.player, centre) > 0.05:
                    if any(intersects(self.player, centre, c, RADIUS) for c in self.covers):
                        return []
                    nodes.insert(0, centre)
                return nodes
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (here[0] + dx, here[1] + dz)
                a, b = {"x": here[0], "z": here[1]}, {"x": nxt[0], "z": nxt[1]}
                if not self.free(b) or any(intersects(a, b, c, RADIUS) for c in self.covers):
                    continue
                cost = costs[here] + math.hypot(dx, dz)
                if cost >= costs.get(nxt, float("inf")):
                    continue
                costs[nxt], previous[nxt] = cost, here
                heapq.heappush(
                    frontier, (cost + math.hypot(nxt[0] - goal[0], nxt[1] - goal[1]), nxt)
                )
        return []

    def plan(self):
        self.path = []
        enemies = self.alive()
        if not enemies:
            return
        enemy = min(enemies, key=lambda e: distance(self.player, e))
        candidates = []
        if self.action == "retreat":
            # Candidate cover positions are physical navigation targets, not Laya hints.
            for c in self.covers:
                for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    goal = {
                        "x": round(c["x"] + dx * (c["w"] / 2 + 1.6)),
                        "z": round(c["z"] + dz * (c["d"] / 2 + 1.6)),
                    }
                    if self.free(goal) and not self.visible(enemy, goal):
                        candidates.append(goal)
        elif self.action == "attack":
            if distance(self.player, enemy) <= 13 and self.visible(self.player, enemy):
                return
            for i in range(16):
                angle = i * math.tau / 16
                goal = {
                    "x": round(enemy["x"] + math.cos(angle) * 9),
                    "z": round(enemy["z"] + math.sin(angle) * 9),
                }
                if self.free(goal) and self.visible(goal, enemy):
                    candidates.append(goal)
        for goal in sorted(candidates, key=lambda p: distance(self.player, p)):
            path = self.route(goal)
            if path:
                self.path = path
                return

    def command(self, action):
        if action not in ACTIONS:
            raise ValueError("Unknown action")
        if self.status != "active":
            raise ValueError("训练已结束，请重置。")
        self.action = action
        self.player["shield"] = action == "defend" and self.player["energy"] >= 1
        self.player["moving"] = False
        self.plan()

    def effect(self, kind, point):
        self.sequence += 1
        self.effects.append(
            {"id": self.sequence, "kind": kind, "x": point["x"], "z": point["z"], "born": self.time}
        )

    def fire(self, shooter, target, team):
        dx, dz = target["x"] - shooter["x"], target["z"] - shooter["z"]
        length = max(0.01, math.hypot(dx, dz))
        self.sequence += 1
        self.projectiles.append(
            {
                "id": self.sequence,
                "x": shooter["x"] + dx / length,
                "z": shooter["z"] + dz / length,
                "vx": dx / length * 21,
                "vz": dz / length * 21,
                "team": team,
                "damage": 18 if team == "player" else 5,
                "born": self.time,
            }
        )
        self.effect("muzzle_blue" if team == "player" else "muzzle_red", shooter)

    def advance(self, dt):
        if not math.isfinite(dt) or not 0 < dt <= 0.5:
            raise ValueError("Tick must be finite and within (0, 0.5]")
        remaining = dt
        while remaining > 1e-8 and self.status == "active":
            step = min(0.05, remaining)
            self._step(step)
            remaining -= step
        return self.snapshot()

    def _step(self, dt):
        self.time += dt
        p = self.player
        p["moving"] = False
        if self.path and self.action in ("attack", "retreat"):
            dest = self.path[0]
            length = distance(p, dest)
            speed = 3.8 if self.action == "retreat" else 2.8
            if length <= speed * dt:
                p["x"], p["z"] = dest["x"], dest["z"]
                self.path.pop(0)
            else:
                p["x"] += (dest["x"] - p["x"]) / length * speed * dt
                p["z"] += (dest["z"] - p["z"]) / length * speed * dt
            p["moving"] = True
        enemies = self.alive()
        if enemies:
            nearest = min(enemies, key=lambda e: distance(p, e))
            p["yaw"] = math.atan2(nearest["x"] - p["x"], nearest["z"] - p["z"])
        if p["energy"] < 8 * dt:
            self.shield_recharging = True
        if p["energy"] >= 25:
            self.shield_recharging = False
        p["shield"] = self.action == "defend" and not self.shield_recharging
        p["energy"] = max(0, min(100, p["energy"] + (-8 if p["shield"] else 7) * dt))
        self.shot_timer -= dt
        if self.action == "attack" and self.shot_timer <= 0 and p["energy"] >= 8:
            targets = [e for e in enemies if distance(p, e) <= 17 and self.visible(p, e)]
            if targets:
                self.fire(p, min(targets, key=lambda e: distance(p, e)), "player")
                p["energy"] -= 8
                self.shot_timer = 0.85
                self.stats["shots"] += 1
        for enemy in enemies:
            enemy["yaw"] = math.atan2(p["x"] - enemy["x"], p["z"] - enemy["z"])
            enemy["cooldown"] -= dt
            if enemy["cooldown"] <= 0:
                if self.visible(enemy, p):
                    self.fire(enemy, p, "enemy")
                enemy["cooldown"] = 1.4 if self.difficulty == "challenge" else 2.2
        kept = []
        for shot in self.projectiles:
            end = {"x": shot["x"] + shot["vx"] * dt, "z": shot["z"] + shot["vz"] * dt}
            cover_dist = min(
                (v for c in self.covers if (v := contact(shot, end, c)) is not None), default=2
            )
            targets = self.alive() if shot["team"] == "player" else [p]
            collisions = [
                (v, t)
                for t in targets
                if (v := contact(shot, end, {"x": t["x"], "z": t["z"], "w": 1.5, "d": 1.5}))
                is not None
            ]
            hit_dist, hit = min(collisions, key=lambda item: item[0], default=(2, None))
            if cover_dist <= 1 and cover_dist <= hit_dist:
                self.effect("spark", end)
            elif hit is not None:
                if shot["team"] == "enemy" and p["shield"]:
                    self.stats["blocked"] += 1
                    self.effect("shield", p)
                else:
                    before = hit["armor"]
                    hit["armor"] = max(0, before - shot["damage"])
                    self.effect("hit", hit)
                    if shot["team"] == "player":
                        self.stats["hits"] += 1
                        if hit["armor"] == 0:
                            self.stats["kills"] += 1
                            self.effect("explosion", hit)
                            self.plan()
                    else:
                        self.stats["damage_taken"] += before - hit["armor"]
            elif self.time - shot["born"] < 2.5:
                shot.update(end)
                kept.append(shot)
        self.projectiles = kept
        self.effects = [e for e in self.effects if self.time - e["born"] < 1.2][-40:]
        if p["armor"] <= 0:
            self.status = "lost"
            self.effect("explosion", p)
        elif not self.alive():
            self.status = "won"
        elif self.time >= 180:
            self.status = "timeout"

    def inject(self, event):
        if self.status != "active":
            raise ValueError("训练已结束，请重置。")
        if self.event_count >= 24:
            raise ValueError("环境干预已达上限，请重置训练。")
        if event == "enemy":
            self.add_enemy()
        elif event == "armor":
            self.player["armor"] = max(1, self.player["armor"] - 25)
            self.effect("hit", self.player)
        elif event == "cover":
            if len(self.covers) >= 7:
                raise ValueError("掩体已达上限。")
            enemy = min(self.alive(), key=lambda e: distance(self.player, e))
            length = max(0.01, distance(self.player, enemy))
            goal = {
                "x": self.player["x"] + (enemy["x"] - self.player["x"]) / length * 3,
                "z": self.player["z"] + (enemy["z"] - self.player["z"]) / length * 3,
            }
            box = {"id": len(self.covers) + 1, **goal, "w": 2.8, "d": 1.6}
            if not self.free(goal) or any(intersects(e, e, box, 1) for e in self.alive()):
                raise ValueError("当前位置无法生成掩体，请移动后再试。")
            self.covers.append(box)
        else:
            raise ValueError("Unknown event")
        self.event_count += 1
        self.plan()

    def snapshot(self):
        return copy.deepcopy(
            {
                "seed": self.seed,
                "difficulty": self.difficulty,
                "time": round(self.time, 3),
                "action": self.action,
                "status": self.status,
                "player": self.player,
                "enemies": self.enemies,
                "covers": self.covers,
                "projectiles": self.projectiles,
                "effects": self.effects,
                "path": self.path,
                "stats": self.stats,
                "event_count": self.event_count,
            }
        )

"""Physics and API contract tests. Fake agents are never used by the application."""

import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from laya_axera.mech.game import MechGame, contact, distance, intersects
from laya_axera.mech.policy import build_request, decide
from laya_axera.server import ModelRegistry, create_app


def advance(game, seconds):
    for _ in range(round(seconds * 4)):
        game.advance(0.25)


def test_seed_and_snapshot_isolation():
    a, b = MechGame(42), MechGame(42)
    assert a.snapshot() == b.snapshot()
    assert a.enemies != MechGame(43).enemies
    snapshot = a.snapshot()
    snapshot["player"]["armor"] = 0
    assert a.player["armor"] == 100
    for action in ("defend", "retreat", "hold", "attack"):
        a.command(action)
        b.command(action)
        advance(a, 2)
        advance(b, 2)
        assert a.snapshot() == b.snapshot()


def test_defense_blocks_real_shots_and_consumes_energy():
    game = MechGame()
    assert game.visible(game.enemies[0], game.player)
    game.command("defend")
    advance(game, 6)
    assert game.stats["blocked"] >= 2
    assert game.player["armor"] == 100
    assert 50 < game.player["energy"] < 55
    assert game.stats["shots"] == 0
    advance(game, 20)
    assert 0 <= game.player["energy"] <= 100


def test_attack_completes_and_hold_does_not_fire():
    game = MechGame()
    game.command("hold")
    before = copy.deepcopy(game.player)
    advance(game, 3)
    assert game.stats["shots"] == 0
    assert game.player["x"] == before["x"] and game.player["z"] == before["z"]
    assert game.player["armor"] < 100
    game.command("attack")
    advance(game, 20)
    assert game.status == "won"
    assert game.stats["kills"] == 1 and game.stats["hits"] == 4
    snapshot = game.snapshot()
    advance(game, 2)
    assert snapshot == game.snapshot()


def test_retreat_reaches_cover_without_crossing_it():
    game = MechGame()
    game.command("retreat")
    assert game.path
    previous = game.player.copy()
    for _ in range(40):
        game.advance(0.25)
        assert game.free(game.player)
        assert not any(intersects(previous, game.player, c, 0.7) for c in game.covers)
        previous = game.player.copy()
    assert not game.path
    assert not game.visible(game.enemies[0], game.player)
    assert game.stats["shots"] == 0
    armor = game.player["armor"]
    advance(game, 5)
    assert game.player["armor"] == armor


def test_cover_stops_projectiles_and_nearest_collision_wins():
    game = MechGame()
    game.player.update(x=-5, z=0)
    game.enemies[0].update(x=5, z=0, cooldown=100)
    game.covers = [{"id": 1, "x": 0, "z": 0, "w": 0.2, "d": 3}]
    game.fire(game.enemies[0], game.player, "enemy")
    advance(game, 1)
    assert game.player["armor"] == 100 and not game.projectiles
    start, end = {"x": -2, "z": 0}, {"x": 2, "z": 0}
    assert contact(start, end, {"x": 0, "z": 0, "w": 1, "d": 1}) == 0.375
    game = MechGame()
    game.player.update(x=0, z=0)
    game.enemies[0]["cooldown"] = 100
    game.covers = [{"id": 1, "x": 0.9, "z": 0, "w": 0.1, "d": 3}]
    game.projectiles = [
        {"id": 99, "x": -0.8, "z": 0, "vx": 40, "vz": 0, "team": "enemy", "damage": 5, "born": 0}
    ]
    game.advance(0.05)
    assert game.player["armor"] == 95  # Target before cover in the same segment.


@pytest.mark.parametrize("dt", [0, -0.1, 0.501, float("inf"), float("nan")])
def test_invalid_tick_is_atomic(dt):
    game = MechGame()
    before = game.snapshot()
    with pytest.raises(ValueError):
        game.advance(dt)
    assert game.snapshot() == before


def test_bounded_interventions_and_timeout():
    game = MechGame()
    for _ in range(3):
        game.inject("enemy")
    before = game.snapshot()
    with pytest.raises(ValueError):
        game.inject("enemy")
    assert game.snapshot() == before
    game = MechGame()
    game.command("retreat")
    advance(game, 180.5)
    assert game.status == "timeout" and game.time < 180.1


class FakeTokenizer:
    mask_token = "[MASK]"

    def __call__(self, text, **kwargs):
        return {"input_ids": list(range(len(text)))}


class FakeAgent:
    tok = FakeTokenizer()
    seq_len = 1024
    head_max_len = 256

    def __init__(self):
        self.calls = 0
        self.fail = False
        self.probs = {"attack": 0.01, "defend": 0.97, "retreat": 0.01, "hold": 0.01}

    def predict_request(self, request):
        self.calls += 1
        if self.fail:
            raise RuntimeError("test failure")
        return {
            "answers": {"action": {"probabilities": self.probs.copy()}},
            "total_npu_latency_ms": 12.34,
            "model": "test fixture",
            "engine": {"provider": "test fixture"},
            "usage": {"input_tokens": 200},
        }


@pytest.fixture
def agent():
    with patch("laya_axera.mech.policy.build_prefix", return_value=([1] * 10, None)):
        yield FakeAgent()


@pytest.fixture
def client(agent):
    with patch.object(ModelRegistry, "get", return_value=agent):
        with TestClient(create_app({"test": Path("unused")})) as client:
            yield client


def test_argmax_is_truthful_even_when_command_means_something_else(agent):
    result = decide(agent, "继续进攻。", MechGame())
    assert result["action"] == "defend"
    assert result["probabilities"] == agent.probs
    assert result["raw_answers"]["action"]["probabilities"] == agent.probs
    assert agent.calls == 1


def test_intent_input_is_independent_of_world_numbers():
    game = MechGame()
    before = build_request("原地待命。", game)
    game.player.update(armor=12, energy=30)
    game.inject("enemy")
    assert build_request("原地待命。", game) == before


def test_budget_and_invalid_probabilities_reject_without_fallback(agent):
    agent.seq_len = 12
    with pytest.raises(ValueError, match="长度限制"):
        decide(agent, "defend", MechGame())
    assert agent.calls == 0
    agent.seq_len = 1024
    agent.probs["defend"] = float("nan")
    with pytest.raises(ValueError, match="无效概率"):
        decide(agent, "defend", MechGame())


def post(client, path, data, **extra):
    return client.post(
        "/api/mech/" + path,
        json={"session": data["session"], "revision": data["revision"], **extra},
    )


def test_pause_manual_duplicate_and_failure_atomicity(client, agent):
    initial = client.post("/api/mech/new", json={}).json()
    paused = post(client, "tick", initial, dt=0.25).json()
    assert paused["state"] == initial["state"]
    command = post(client, "command", initial, text="defend").json()
    assert command["npu_calls"] == 1 and command["decision"]["source"] == "laya"
    assert post(client, "command", initial, text="defend").status_code == 409
    assert agent.calls == 1
    command["session"] = initial["session"]
    paused = post(client, "pause", command, playing=False).json()
    paused["session"] = initial["session"]
    assert post(client, "tick", paused, dt=0.5).json()["state"] == paused["state"]
    agent.fail = True
    assert post(client, "command", paused, text="attack").status_code == 503
    after = client.get("/api/mech/" + initial["session"]).json()
    assert after["state"] == paused["state"] and after["revision"] == paused["revision"]
    manual = post(client, "manual", paused, action="retreat").json()
    assert manual["npu_calls"] == 1 and manual["decision"]["probabilities"] is None
    assert manual["decision"]["source"] == "manual"
    assert distance(manual["state"]["player"], initial["state"]["player"]) == 0


def test_concurrent_duplicate_calls_model_only_once(client, agent):
    data = client.post("/api/mech/new", json={}).json()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: post(client, "command", data, text="defend"), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert agent.calls == 1


def test_session_bound_and_static_assets(client):
    first = client.post("/api/mech/new", json={}).json()
    for _ in range(12):
        assert client.post("/api/mech/new", json={}).status_code == 200
    assert client.get("/api/mech/" + first["session"]).status_code == 404
    for asset in ["mech.html", "mech.css", "mech.js", "mech-scene.js", "vendor/three.module.js"]:
        assert client.get("/" + asset).status_code == 200
    assert b"0.170" in client.get("/vendor/README.md").content


def test_render_diagnostics_are_bounded_and_do_not_advance_world(client):
    data = client.post("/api/mech/new", json={}).json()
    body = {
        "session": data["session"],
        "mode": "webgl2",
        "fps": 60,
        "frames": 120,
        "width": 1000,
        "height": 650,
        "quality": "balanced",
    }
    assert client.post("/api/mech/graphics", json=body).status_code == 200
    result = client.get("/api/mech/diagnostics/renderers").json()
    assert len(result) == 1 and result[0]["fps"] == 60
    assert client.get("/api/mech/" + data["session"]).json()["revision"] == 0

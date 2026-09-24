"""Simulation invariants, truthful decision reporting and retry-safe API behavior."""

import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from laya_axera.rescue.game import ACTIONS, RescueGame
from laya_axera.rescue.policy import decide, rule_action
from laya_axera.server import ModelRegistry, create_app


class FakeAgent:
    """API contract fixture, never used by the application or hardware benchmark."""

    def __init__(self, *args, **kwargs):
        self.fail = False
        self.probabilities = {"rescue": 0.7, "evade": 0.1, "refuel": 0.1, "return": 0.1}

    def predict_request(self, request):
        if self.fail:
            raise RuntimeError("test inference failure")
        return {
            "answers": {
                "action": {"probabilities": self.probabilities.copy()},
                "risk": {"score": 0.4},
                "emergency": {"noul": 0.12},
            },
            "usage": {"input_tokens": 400},
            "total_npu_latency_ms": 99,
            "model": "test fixture",
            "engine": {"provider": "test fixture"},
        }


@pytest.fixture
def fake():
    with (
        patch("laya_axera.rescue.policy.check_budget", return_value={}),
        patch("laya_axera.rescue.api.check_budget", return_value={}),
    ):
        yield FakeAgent()


@pytest.fixture
def client(fake):
    with patch.object(ModelRegistry, "get", return_value=fake):
        with TestClient(create_app({"test": Path("unused")})) as client:
            yield client


def test_seed_reproducibility_and_snapshot_isolation():
    left, right = RescueGame(88), RescueGame(88)
    assert left.snapshot() == right.snapshot()
    assert left.pods != RescueGame(89).pods
    snapshot = left.snapshot()
    snapshot["pods"].clear()
    for _ in range(30):
        if left.status != "active":
            break
        action = rule_action(left)
        left.step(action)
        right.step(action)
        assert left.snapshot() == right.snapshot()
        assert 0 <= left.fuel <= 100 and 0 <= left.hull <= 100
        assert left.rescued + len(left.pods) == 6
    assert left.status == "docked"
    assert left.delivered == left.rescued


def test_delivery_and_scoring_only_at_docking():
    game = RescueGame()
    game.step("rescue")
    assert game.rescued == 1 and game.delivered == 0 and game.snapshot()["score"] == 0
    game.step("return")
    assert game.delivered == 1 and game.snapshot()["score"] == 150
    with pytest.raises(ValueError):
        game.step("rescue")


def test_invalid_action_is_atomic_and_depot_is_finite():
    game = RescueGame()
    before = game.snapshot()
    with pytest.raises(ValueError):
        game.step("shoot")
    assert game.snapshot() == before
    game.step("refuel")
    assert sum(d["stock"] for d in game.depots) == 1 and game.fuel <= 100
    game.step("refuel")
    before = game.snapshot()
    with pytest.raises(ValueError):
        game.step("refuel")
    assert game.snapshot() == before


def test_low_fuel_guard_and_no_double_delivery():
    game = RescueGame()
    game.step("rescue")
    game.fuel = game.plans()["return"]["fuel_cost"]
    assert "rescue" not in game.allowed_actions()
    assert "return" in game.allowed_actions()
    game.step("return")
    with pytest.raises(ValueError):
        game.inject("leak")
    assert game.delivered == 1


def test_exposure_can_destroy_ship_before_rescue():
    game = RescueGame(scenario="storm")
    game.hull = 1
    game.step("rescue")
    assert game.status == "lost" and game.rescued == 0 and len(game.pods) == 6


def test_bounded_mission_and_stranding():
    game = RescueGame()
    for _ in range(30):
        game.fuel = 100
        game.step("evade")
    assert game.status == "timeout"
    game = RescueGame()
    game.step("rescue")
    game.fuel = 1
    game.inject("leak")
    assert game.status == "stranded" and game.fuel == 0


def test_guard_preserves_model_probabilities_and_proposal(fake):
    game = RescueGame()
    game.step("rescue")
    for depot in game.depots:
        depot["stock"] = 0
    game.fuel = game.plans()["return"]["fuel_cost"]
    before = copy.deepcopy(fake.probabilities)
    result = decide(game, mode="laya", guarded=True, agent=fake)
    assert result["proposed"] == "rescue" and result["executed"] == "return"
    assert result["intervened"] and result["probabilities"] == before
    unguarded = decide(game, mode="laya", guarded=False, agent=fake)
    assert not unguarded["intervened"] and unguarded["proposed"] == "rescue"


def test_invalid_probability_and_inference_failure_do_not_execute(fake):
    game = RescueGame()
    before = game.snapshot()
    fake.probabilities["rescue"] = float("nan")
    with pytest.raises(ValueError):
        decide(game, mode="laya", guarded=True, agent=fake)
    assert game.snapshot() == before


@pytest.mark.parametrize("mode", ["rule", "human"])
def test_non_model_modes_have_no_invented_probabilities(mode):
    result = decide(RescueGame(), mode=mode, guarded=True, manual="rescue")
    assert result["probabilities"] is None and result["npu_ms"] is None
    assert result["raw_answers"] is None and result["proposed"] in ACTIONS


def test_duplicate_and_concurrent_steps_advance_only_once(client):
    first = client.post("/api/rescue/new", json={}).json()
    body = {"session": first["session"], "revision": 0}
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post("/api/rescue/step", json=body), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    current = client.get("/api/rescue/" + first["session"]).json()
    assert current["state"]["turn"] == 1 and current["stats"]["npu_calls"] == 3


def test_inference_failure_does_not_fall_back_or_mutate(client, fake):
    first = client.post("/api/rescue/new", json={}).json()
    fake.fail = True
    response = client.post("/api/rescue/step", json={"session": first["session"], "revision": 0})
    assert response.status_code == 503
    current = client.get("/api/rescue/" + first["session"]).json()
    assert current["state"] == first["state"] and current["revision"] == 0
    assert current["stats"]["npu_calls"] == 0


def test_events_are_revisioned_and_manual_requires_action(client):
    first = client.post("/api/rescue/new", json={"mode": "human"}).json()
    body = {"session": first["session"], "revision": 0}
    assert client.post("/api/rescue/step", json=body).status_code == 422
    event = client.post("/api/rescue/event", json={**body, "event": "storm"})
    assert event.status_code == 200 and event.json()["state"]["threat"] == 73
    assert client.post("/api/rescue/step", json={**body, "action": "rescue"}).status_code == 409
    result = client.post("/api/rescue/step", json={**body, "revision": 1, "action": "rescue"})
    assert result.status_code == 200 and result.json()["stats"]["npu_calls"] == 0


def test_sessions_bounded_and_static_assets_available(client):
    first = client.post("/api/rescue/new", json={"mode": "rule"}).json()["session"]
    for _ in range(16):
        assert client.post("/api/rescue/new", json={"mode": "rule"}).status_code == 200
    assert client.get("/api/rescue/" + first).status_code == 404
    for asset in ("rescue.html", "rescue.css", "rescue.js"):
        assert client.get("/" + asset).status_code == 200


def test_registry_concurrent_first_load_is_single_instance():
    registry = ModelRegistry({"test": Path("unused")}, 0, None)
    with patch("laya_axera.server.Agent", side_effect=FakeAgent) as constructor:
        with ThreadPoolExecutor(4) as pool:
            agents = list(pool.map(lambda _: registry.get("test"), range(4)))
    assert constructor.call_count == 1 and all(a is agents[0] for a in agents)

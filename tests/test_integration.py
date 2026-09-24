"""On-device tests. Set LAYA_AXERA_MODEL_DIR to a checkpoint directory to enable them."""

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

MODEL_DIR = os.environ.get("LAYA_AXERA_MODEL_DIR")
if not MODEL_DIR:
    pytest.skip("LAYA_AXERA_MODEL_DIR is not set", allow_module_level=True)
pytest.importorskip("axengine")


@pytest.fixture(scope="module")
def agent():
    from laya_axera import Agent

    return Agent(MODEL_DIR)


def test_sample_request_answers(agent):
    request = agent.sample_request()
    if request is None:
        pytest.skip("checkpoint ships no sample_request.json")
    result = agent.predict_request(request)
    assert set(result["answers"]) == set(request["questions"])
    for name, answer in result["answers"].items():
        assert answer["type"] == request["questions"][name]["type"]
        assert 0.0 <= answer["confidence"] <= 1.0


def test_matches_board_validated_choices(agent):
    """The selected label must match the axllm output recorded on the AX8850 board."""
    request_path = Path(MODEL_DIR) / "sample_request.json"
    expected_path = Path(MODEL_DIR) / "sample_output.json"
    if not (request_path.is_file() and expected_path.is_file()):
        pytest.skip("checkpoint ships no validated sample pair")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    result = agent.predict_request(request)
    for name, answer in expected["answers"].items():
        ours = result["answers"][name]
        if answer["type"] == "choice":
            assert ours["choice"] == answer["choice"]
        elif answer["type"] == "score":
            assert abs(ours["score"] - answer["score"]) < 0.15
        else:
            assert abs(ours["noul"] - answer["noul"]) < 0.1


def test_rescue_prompt_fits_without_state_truncation(agent):
    from laya_axera.rescue.game import RescueGame
    from laya_axera.rescue.policy import build_request, check_budget

    game = RescueGame(mission="优先救人，保留返航燃料。")
    for scenario in ("standard", "storm", "low_fuel"):
        game = RescueGame(scenario=scenario, mission=game.mission)
        request = build_request(game)
        counts = check_budget(agent, request)
        for name, question in request["questions"].items():
            _, _, encoded_count = agent.encode_question(request["state"], question)
            assert encoded_count == counts[name] <= agent.seq_len
    game.mission = "rescue " * agent.seq_len
    with pytest.raises(ValueError, match="token budget"):
        check_budget(agent, build_request(game))

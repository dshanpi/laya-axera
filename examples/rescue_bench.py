"""Run serial, real-API rescue missions. Requires a running laya-axera server.

python examples/rescue_bench.py --url http://127.0.0.1:8010 --output artifacts/rescue.json
Rule/human results are explicitly labelled and contain no model probabilities.
"""

import argparse
import json
import statistics
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--output", type=Path, default=Path("artifacts/rescue.json"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 2026, 8850])
    args = parser.parse_args()

    def call(route, body=None):
        request = urllib.request.Request(
            args.url.rstrip("/") + route,
            data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)

    results = {
        "format": "laya-rescue-benchmark-v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cases = [
        (seed, scenario, mode, True, False)
        for seed in args.seeds
        for scenario in ("standard", "storm", "low_fuel")
        for mode in ("laya", "rule")
    ]
    cases += [
        (args.seeds[0], scenario, "laya", False, False)
        for scenario in ("standard", "storm", "low_fuel")
    ]
    cases += [
        (args.seeds[0], "standard", "laya", True, True),
        (args.seeds[0], "standard", "human", False, True),
    ]
    for seed, scenario, mode, guarded, events in cases:
        config = {
            "seed": seed,
            "scenario": scenario,
            "mode": mode,
            "guarded": guarded,
            "mission": "优先救人，保留返航燃料。",
        }
        current = call("/api/rescue/new", config)
        session = current["session"]
        for index in range(30):
            if current["done"]:
                break
            if events and index in (1, 2):
                current = call(
                    "/api/rescue/event",
                    {
                        "session": session,
                        "revision": current["revision"],
                        "event": "storm" if index == 1 else "leak",
                    },
                )
                if current["done"]:
                    break
            body = {"session": session, "revision": current["revision"]}
            if mode == "human":
                body["action"] = ("rescue", "evade", "return")[min(index, 2)]
            current = call("/api/rescue/step", body)
            d = current["decision"]
            if mode == "laya":
                assert d["engine"]["provider"] in (
                    "AXCLRTExecutionProvider",
                    "AxEngineExecutionProvider",
                )
                assert d["npu_ms"] > 0 and d["raw_answers"]
                assert d["proposed"] == max(d["probabilities"], key=d["probabilities"].get)
            else:
                assert d["npu_ms"] is None and d["probabilities"] is None
        assert current["done"], "Mission did not end within its turn limit"
        results["runs"].append({"config": config, "injected_events": events, **current})
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            seed,
            scenario,
            mode,
            "guard" if guarded else "raw",
            current["state"]["status"],
            "delivered",
            current["state"]["delivered"],
            "decisions",
            current["stats"]["decisions"],
            "interventions",
            current["stats"]["interventions"],
            flush=True,
        )
    latencies = [
        step["decision"]["npu_ms"]
        for run in results["runs"]
        for step in run["history"]
        if step.get("decision", {}).get("npu_ms") is not None
    ]
    results["summary"] = {
        "runs": len(results["runs"]),
        "laya_decisions": len(latencies),
        "npu_forwards": len(latencies) * 3,
        "npu_ms_mean": round(statistics.mean(latencies), 3),
        "npu_ms_min": min(latencies),
        "npu_ms_max": max(latencies),
    }
    results["server"] = call("/api/info")
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

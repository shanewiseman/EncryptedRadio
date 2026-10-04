#!/usr/bin/env python3
"""Reproduce simulated reception limits; this does not exercise audio hardware.

Run with the project audio dependencies installed:
    uv run --locked --extra audio python scripts/benchmark_dsp.py --output tmp/dsp-matrix.json
"""

import argparse
import json
from pathlib import Path
import platform
import sys

import numpy as np
import scipy

# Keep the independently keyed oscillator in tests, separate from production
# synthesis. The benchmark must not feed transmitter state to the receiver.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_audio import keyed_signal  # noqa: E402
from encrypted_radio.audio import MorseDecoder  # noqa: E402


def edit_distance(expected, actual):
    previous = list(range(len(actual) + 1))
    for index, character in enumerate(expected, 1):
        current = [index]
        for other_index, other in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[other_index] + 1,
                               previous[other_index - 1] + (character != other)))
        previous = current
    return previous[-1]


def run_matrix():
    expected = "VVV(ABC234)"
    result = {
        "version": 1,
        "fixture": "independent hard-keyed oscillator; Gaussian noise bandpass 350–1250 Hz",
        "noise_reference": "whole-recording mean signal power divided by mean noise power",
        "seed": 218,
        "expected": expected,
        "sample_rates": [44100, 48000],
        "frequencies": [400, 700, 1200],
        "speeds_wpm": [8, 20, 30],
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "hardware_tested": False,
        "scenarios": [],
    }
    for noise_db, jitter, required in ((10, 0.2, True), (0, 0.3, False), (-5, 0.4, False)):
        scenario = {"noise_db": noise_db, "max_timing_jitter": jitter, "required": required, "cases": []}
        for rate in result["sample_rates"]:
            for pitch in result["frequencies"]:
                for speed in result["speeds_wpm"]:
                    decoder = MorseDecoder(rate)
                    pcm = keyed_signal(expected, rate, pitch, speed, jitter=jitter, noise_db=noise_db, seed=result["seed"])
                    actual = decoder.feed(pcm) + decoder.finish()
                    scenario["cases"].append({
                        "sample_rate": rate, "frequency": pitch, "wpm": speed,
                        "exact": actual == expected, "received": actual,
                        "edit_errors": edit_distance(expected, actual),
                        "detected_errors": decoder.error_count,
                    })
        scenario["summary"] = {
            "exact_cases": sum(case["exact"] for case in scenario["cases"]),
            "total_cases": len(scenario["cases"]),
            "edit_errors": sum(case["edit_errors"] for case in scenario["cases"]),
            "expected_characters": len(expected) * len(scenario["cases"]),
            "detected_errors": sum(case["detected_errors"] for case in scenario["cases"]),
        }
        summary = scenario["summary"]
        summary["character_error_rate"] = summary["edit_errors"] / summary["expected_characters"]
        result["scenarios"].append(scenario)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write complete JSON evidence to this path")
    args = parser.parse_args()
    result = run_matrix()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("| Noise | Timing jitter | Exact cases | Edit errors / characters | Character error rate |")
    print("| --- | --- | --- | --- | --- |")
    for scenario in result["scenarios"]:
        summary = scenario["summary"]
        print(f"| {scenario['noise_db']} dB | ±{scenario['max_timing_jitter']:.0%} | "
              f"{summary['exact_cases']}/{summary['total_cases']} | "
              f"{summary['edit_errors']}/{summary['expected_characters']} | "
              f"{summary['character_error_rate']:.1%} |")
    print("\nCharacter error rates can exceed 100% when noise inserts extra characters. No hardware tested.")
    return int(any(scenario["required"] and scenario["summary"]["exact_cases"] != scenario["summary"]["total_cases"]
                   for scenario in result["scenarios"]))


if __name__ == "__main__":
    raise SystemExit(main())

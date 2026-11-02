"""Offline evaluation of the intent classifier on a gold fixture set (P6.1). Pure.

Run: `uv run python -m app.intent.evaluate tests/fixtures/intent/gold_v1.jsonl`

Reports, per split, primary-label macro-F1 over the ten intents, per-language accuracy and confusion matrices, and
the recall of the two mandatory safety flags (`explicit_opt_out`, `human_escalation_requested`) on the fixed safety
suite. The promotion targets are macro-F1 >= 0.85 on the held-out split and 100% safety recall; even when met, they
describe behaviour on these fixtures only.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.intent.classifier import CLASSIFIER_VERSION, classify
from app.intent.schema import INTENTS

SAFETY_FLAGS = ("explicit_opt_out", "human_escalation_requested")
TARGET_MACRO_F1 = 0.85


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def macro_f1(pairs: list[tuple[str, str]]) -> float:
    """Unweighted mean F1 over the labels present in gold or prediction (absent labels are not free points)."""
    labels = sorted({g for g, _ in pairs} | {p for _, p in pairs})
    scores = []
    for label in labels:
        tp = sum(1 for g, p in pairs if g == label and p == label)
        fp = sum(1 for g, p in pairs if g != label and p == label)
        fn = sum(1 for g, p in pairs if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"classifier_version": CLASSIFIER_VERSION, "items": len(rows), "splits": {}}
    failures = []
    for split in sorted({r["split"] for r in rows}):
        subset = [r for r in rows if r["split"] == split]
        predictions = {r["id"]: classify(r["text"]) for r in subset}
        pairs = [(r["primary"], predictions[r["id"]].primary) for r in subset]
        by_language: dict[str, dict[str, Any]] = {}
        for language in sorted({r["language"] for r in subset}):
            items = [r for r in subset if r["language"] == language]
            confusion: dict[str, Counter[str]] = defaultdict(Counter)
            for r in items:
                confusion[r["primary"]][predictions[r["id"]].primary] += 1
            by_language[language] = {
                "items": len(items),
                "accuracy": round(
                    sum(1 for r in items if predictions[r["id"]].primary == r["primary"]) / len(items), 4
                ),
                "confusion": {gold: dict(row) for gold, row in sorted(confusion.items())},
            }
        safety = [r for r in subset if r["safety_suite"]]
        recall = {}
        for flag in SAFETY_FLAGS:
            wanted = [r for r in safety if flag in r["flags"]]
            hit = [r for r in wanted if flag in predictions[r["id"]].flags]
            recall[flag] = {"expected": len(wanted), "found": len(hit),
                            "recall": round(len(hit) / len(wanted), 4) if wanted else None}  # fmt: skip
        false_opt_out = [
            r["id"]
            for r in subset
            if "explicit_opt_out" in predictions[r["id"]].flags and "explicit_opt_out" not in r["flags"]
        ]
        failures += [
            {"id": r["id"], "split": split, "language": r["language"], "gold": r["primary"],
             "predicted": predictions[r["id"]].primary}
            for r in subset if predictions[r["id"]].primary != r["primary"]
        ]  # fmt: skip
        out["splits"][split] = {
            "items": len(subset), "macro_f1": round(macro_f1(pairs), 4), "by_language": by_language,
            "safety_recall": recall, "false_explicit_opt_out": false_opt_out,
        }  # fmt: skip
    measured = [out["splits"][s] for s in ("heldout", "blind") if s in out["splits"]]
    out["failures"] = failures
    out["targets_met"] = bool(
        measured
        and all(m["macro_f1"] >= TARGET_MACRO_F1 for m in measured)
        and all(v["recall"] in (None, 1.0) for split in out["splits"].values() for v in split["safety_recall"].values())
        and not any(split["false_explicit_opt_out"] for split in out["splits"].values())
    )
    out["labels"] = list(INTENTS)
    return out


if __name__ == "__main__":
    print(json.dumps(report(load(Path(sys.argv[1]))), indent=2, ensure_ascii=False))

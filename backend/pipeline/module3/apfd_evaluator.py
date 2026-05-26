import random

from backend.pipeline.module3.tpri import compute_tpri


def compute_apfd(test_order, fault_detected_by):
    if not test_order or not fault_detected_by:
        return 1.0

    positions = []
    for fault_id, tc_id in fault_detected_by.items():
        if tc_id in test_order:
            positions.append(test_order.index(tc_id) + 1)

    if not positions:
        return 1.0

    n = len(test_order)
    m = len(fault_detected_by)
    return 1 - (sum(positions) / (n * m)) + (1 / (2 * n))


def build_fault_map(mode2_tests):
    fault_map = {}
    for test in mode2_tests or []:
        if test.get("confirmed_fault") is True and test.get("discrepancy_id"):
            fault_map.setdefault(test["discrepancy_id"], test["tc_id"])
    return fault_map


def random_apfd(mode2_tests, fault_map, runs=5):
    if not mode2_tests:
        return 1.0

    order = [test["tc_id"] for test in mode2_tests]
    scores = []
    rng = random.Random(42)
    for _ in range(runs):
        shuffled = order[:]
        rng.shuffle(shuffled)
        scores.append(compute_apfd(shuffled, fault_map))
    return sum(scores) / len(scores)


def severity_only_apfd(mode2_tests, fault_map):
    if not mode2_tests:
        return 1.0

    ordered = sorted(
        mode2_tests,
        key=lambda test: (test.get("st") or 0.0, test.get("tpri_score") or 0.0),
        reverse=True,
    )
    return compute_apfd([test["tc_id"] for test in ordered], fault_map)


def run_ablation_study(discrepancies, enriched_acs, user_story, mode2_tests, fault_map):
    full_apfd = compute_apfd([test["tc_id"] for test in mode2_tests], fault_map)

    variants = {
        "Full TPRI": {"ci": 0.25, "st": 0.25, "rc": 0.25, "fs": 0.25},
        "Without CI": {"ci": 0.0, "st": 0.3333, "rc": 0.3333, "fs": 0.3334},
        "Without ST": {"ci": 0.3333, "st": 0.0, "rc": 0.3333, "fs": 0.3334},
        "Without RC": {"ci": 0.3333, "st": 0.3333, "rc": 0.0, "fs": 0.3334},
        "Without FS": {"ci": 0.3333, "st": 0.3333, "rc": 0.3334, "fs": 0.0},
    }

    ordered_results = {}
    for name, weights in variants.items():
        ranked = []
        for discrepancy in discrepancies or []:
            tpri = compute_tpri(
                ci=float(discrepancy.get("confidence_index", 0.0)),
                discrepancy_type=discrepancy.get("discrepancy_type", "Wrong_Label"),
                ac_text=discrepancy.get("ac_text", discrepancy.get("requirement_id", "")),
                user_story=user_story,
                all_acs=[item.get("text") if isinstance(item, dict) else str(item) for item in enriched_acs],
                weights=weights,
            )
            item = dict(discrepancy)
            item.update(tpri)
            ranked.append(item)

        ranked.sort(key=lambda item: (item["tpri_score"], item.get("confidence_index", 0.0)), reverse=True)
        ordered = [test["tc_id"] for test in mode2_tests]
        ordered_results[name] = {
            "apfd": compute_apfd(ordered, fault_map),
            "drop": full_apfd - compute_apfd(ordered, fault_map),
        }

    ordered_results["Full TPRI"] = {"apfd": full_apfd, "drop": 0.0}
    return ordered_results
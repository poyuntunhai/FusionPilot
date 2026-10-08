"""
Run the agent evaluation suite and print a report.

    python -m evals.run_evals                     # everything
    python -m evals.run_evals --group gate        # one group
    python -m evals.run_evals --only concept-*    # glob on ids
    python -m evals.run_evals --json report.json  # machine-readable copy
    python -m evals.run_evals --verbose           # every check, passing or not

What this measures: the agent's behaviour *given* a model decision — which route it dispatches to,
whether it gates an expensive call behind a confirmation, the order tools run in, whether an answer
is grounded and cited, whether the self-check layer speaks up. The cases carry their own scripted
model, so the suite is deterministic and needs no provider key, no MySQL, and no Java process.

What this does not measure: whether the model itself routes or answers well. That needs a real
provider, and is argued out in `evals/README.md` rather than implied by a green run here.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # allow `python evals/run_evals.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.grade import grade  # noqa: E402
from evals.harness import DEFAULT_CASES, load_cases, run_case  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the FusionPilot agent evaluation suite.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="JSONL case file")
    parser.add_argument("--group", default=None, help="only cases in this group")
    parser.add_argument("--only", default=None, help="glob matched against case ids")
    parser.add_argument("--json", dest="json_path", default=None, help="write a JSON report here")
    parser.add_argument("--verbose", action="store_true", help="print every check, not just failures")
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.cases))
    if args.group:
        cases = [case for case in cases if case.get("group") == args.group]
    if args.only:
        from fnmatch import fnmatch

        cases = [case for case in cases if fnmatch(case["id"], args.only)]
    if not cases:
        print("no cases matched")
        return 1

    started = time.time()
    results: list[dict] = []
    passed = failed = errored = 0

    print(f"FusionPilot agent evaluation — {len(cases)} cases from {Path(args.cases).name}\n")

    current_group = None
    for case in cases:
        group = case.get("group") or "ungrouped"
        if group != current_group:
            print(f"{group}")
            current_group = group

        started_case = time.time()
        try:
            outcome = run_case(case)
            checks = grade(case, outcome)
        except Exception as exc:  # noqa: BLE001 - one bad case must not end the run
            checks = []
            outcome = None
            results.append(
                {
                    "id": case["id"],
                    "group": group,
                    "passed": False,
                    "errored": True,
                    "error": f"{type(exc).__name__}: {exc}",
                    "checks": [],
                }
            )
            errored += 1
            print(f"  ERROR {case['id']} — {type(exc).__name__}: {exc}")
            continue

        ok = all(check.passed for check in checks)
        duration = time.time() - started_case
        results.append(
            {
                "id": case["id"],
                "group": group,
                "passed": ok,
                "errored": False,
                "duration_seconds": round(duration, 3),
                "description": case.get("description", ""),
                "checks": [
                    {"name": check.name, "passed": check.passed, "detail": check.detail}
                    for check in checks
                ],
            }
        )
        if ok:
            passed += 1
            print(f"  PASS  {case['id']} ({duration:.2f}s)")
            if args.verbose:
                for check in checks:
                    print("       " + check.render().strip())
        else:
            failed += 1
            print(f"  FAIL  {case['id']} ({duration:.2f}s)")
            if case.get("description"):
                print(f"        {case['description']}")
            for check in checks:
                if not check.passed:
                    print("       " + check.render().strip())

    total_time = time.time() - started
    print()
    print(
        f"SUMMARY: {passed}/{len(cases)} passed, {failed} failed, {errored} errored "
        f"in {total_time:.1f}s"
    )
    print(
        "Note: a green run means the agent behaved as specified given a scripted model. "
        "It does not measure model judgement (see evals/README.md)."
    )

    if args.json_path:
        payload = {
            "cases_file": str(Path(args.cases).resolve()),
            "total_seconds": round(total_time, 3),
            "summary": {
                "total": len(cases),
                "passed": passed,
                "failed": failed,
                "errored": errored,
            },
            "results": results,
        }
        Path(args.json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report written to {args.json_path}")

    return 0 if failed == 0 and errored == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

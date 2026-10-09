"""
Run the agent evaluation suite and print a report.

    python -m evals.run_evals                     # everything
    python -m evals.run_evals --group gate        # one group
    python -m evals.run_evals --only concept-*    # glob on ids
    python -m evals.run_evals --json report.json  # machine-readable copy
    python -m evals.run_evals --verbose           # every check, passing or not

    # and against a real provider instead of each case's scripted model:
    python -m evals.run_evals --group routing --provider zhipu --model glm-4-flash --api-key ...

What this measures: the agent's behaviour *given* a model decision — which route it dispatches to,
whether it gates an expensive call behind a confirmation, the order tools run in, whether an answer
is grounded and cited, whether the self-check layer speaks up. The cases carry their own scripted
model, so the suite is deterministic and needs no provider key, no MySQL, and no Java process.

With ``--api-key`` the scripted model is replaced by a real provider and the same cases run again,
but now the routing decision and the prose are the model's own. Only the checks named in
``grade.LIVE_SIGNIFICANT`` are counted in that mode: everything else in the vocabulary quotes the
script's own words and counts, so failing them would say nothing about the model. This is why a
green scripted run and a green live run mean different things, and why the report says which mode
it is in rather than just "17 passed".
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # allow `python evals/run_evals.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.grade import LIVE_SIGNIFICANT, grade  # noqa: E402
from evals.harness import DEFAULT_CASES, LiveModel, load_cases, run_case  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the FusionPilot agent evaluation suite.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="JSONL case file")
    parser.add_argument("--group", default=None, help="only cases in this group")
    parser.add_argument("--only", default=None, help="glob matched against case ids")
    parser.add_argument("--json", dest="json_path", default=None, help="write a JSON report here")
    parser.add_argument("--verbose", action="store_true", help="print every check, not just failures")
    provider = parser.add_argument_group(
        "live provider",
        "Point the cases at a real model instead of each case's scripted one. Only the checks in "
        "grade.LIVE_SIGNIFICANT are counted; see evals/README.md.",
    )
    provider.add_argument("--provider", default="openai", help="provider name (default: openai)")
    provider.add_argument("--model", default=None, help="model to call, e.g. glm-4-flash")
    provider.add_argument("--api-key", default=None, help="the token, sent as X-Model-Api-Key")
    provider.add_argument("--api-base", default=None, help="override the provider's base URL")
    args = parser.parse_args(argv)

    live: LiveModel | None = None
    if args.api_key:
        if not args.model:
            parser.error("--api-key needs --model: the request has to name the model to call")
        live = LiveModel(
            provider=args.provider, model=args.model, api_key=args.api_key, api_base=args.api_base
        )

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

    print(f"FusionPilot agent evaluation — {len(cases)} cases from {Path(args.cases).name}")
    if live is None:
        print("Mode: scripted. Each case answers its own provider calls, so this is deterministic")
        print("and offline. It measures the agent given a model decision, not the model.\n")
    else:
        print(f"Mode: live. Provider {live.provider}, model {live.model}.")
        print("The routing and prose in this run are the model's own. Only these checks are counted:")
        print(f"  {', '.join(sorted(LIVE_SIGNIFICANT))}")
        print("Everything else in the vocabulary quotes the script and is shown as [skip].\n")

    current_group = None
    for case in cases:
        group = case.get("group") or "ungrouped"
        if group != current_group:
            print(f"{group}")
            current_group = group

        started_case = time.time()
        try:
            outcome = run_case(case, live)
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

        counted = checks if live is None else [c for c in checks if c.name in LIVE_SIGNIFICANT]
        ok = all(check.passed for check in counted)
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
                    {
                        "name": check.name,
                        "passed": check.passed,
                        "detail": check.detail,
                        "counted": live is None or check.name in LIVE_SIGNIFICANT,
                    }
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

        if live is not None and (args.verbose or not ok):
            skipped = [c for c in checks if c.name not in LIVE_SIGNIFICANT]
            if skipped:
                print(f"       [skip] not counted in live mode: {', '.join(c.name for c in skipped)}")

    total_time = time.time() - started
    print()
    print(
        f"SUMMARY: {passed}/{len(cases)} passed, {failed} failed, {errored} errored "
        f"in {total_time:.1f}s"
    )
    if live is None:
        print(
            "Note: a green run means the agent behaved as specified given a scripted model. "
            "It does not measure model judgement. Add --api-key to measure that."
        )
    else:
        print(
            f"Note: counts cover the {len(LIVE_SIGNIFICANT)} model-independent checks only. A case "
            "fails here when the model routed elsewhere, broke a tool contract, or wrote a number "
            "the run never returned - not when its wording differed from the script."
        )

    if args.json_path:
        payload = {
            "cases_file": str(Path(args.cases).resolve()),
            "mode": "live" if live is not None else "scripted",
            "live_significant": sorted(LIVE_SIGNIFICANT),
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

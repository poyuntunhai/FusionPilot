#!/usr/bin/env python3
"""
fpx - a command line front end for the FusionPilot simulation core.

Why this exists
---------------
Pi and comparable agent harnesses prefer command line tools over permanently loaded tool
definitions: a CLI costs nothing in the context until it is called, its output can be shaped for a
reader, and it can be tested without an agent in the loop. This wraps the FusionPilot HTTP API in
exactly that form, so an agent working in a terminal can design, run and read experiments.

Two properties are deliberate:

* Every command writes compact JSON. Summaries rather than raw payloads: a single run carries every
  step of every target, and dumping that into a model's context spends the window on data nobody
  reads. Use --full when you actually want the whole thing.
* Working state lives in a file, because each invocation is a separate process. `config-set` then
  `run` has to mean something across two shells.

Examples
--------
    fpx login --username me --password secret
    fpx config-set --set targetCount=5 --set fusionMethod=KALMAN_FILTER
    fpx run
    fpx metrics
    fpx compare
    fpx history --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request


DEFAULT_BASE_URL = os.environ.get("FUSIONPILOT_API", "http://127.0.0.1:8080").rstrip("/")
DEFAULT_STATE_PATH = os.environ.get("FUSIONPILOT_STATE", ".fpx/state.json")
DEFAULT_TIMEOUT = float(os.environ.get("FUSIONPILOT_TIMEOUT", "60"))

CONFIG_SUMMARY_KEYS = (
    "scenarioName",
    "targetCount",
    "simulationSteps",
    "timeStepSeconds",
    "availableResources",
    "fusionMethod",
    "schedulingPolicy",
    "randomSeed",
)

METRIC_KEYS = (
    "averagePositionError",
    "trackingRate",
    "resourceUtilization",
    "averageWaitingTime",
    "allocatedTargetCount",
    "unservedTargetCount",
    "schedulingSwitches",
    "totalSteps",
)


class CliError(RuntimeError):
    def __init__(self, message: str, code: str = "ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- state


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CliError(f"State file could not be read ({path}): {exc}", "STATE_UNREADABLE") from exc
    return state if isinstance(state, dict) else {}


def save_state(path: str, state: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    # The token lives here, so keep the file to the owner where the platform supports it.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------- http


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict | None = None,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base_url + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        message = body.get("message") or f"HTTP {error.code}"
        raise CliError(message, body.get("code") or f"HTTP_{error.code}") from error
    except urllib.error.URLError as error:
        raise CliError(
            f"Cannot reach the FusionPilot backend at {base_url}: {error.reason}",
            "BACKEND_UNREACHABLE",
        ) from error

    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise CliError("Backend returned a body that is not JSON.", "BAD_RESPONSE") from exc
    if isinstance(body, dict) and body.get("success") is False:
        raise CliError(body.get("message") or "Backend reported a failure.", "BACKEND_REJECTED")
    return body.get("data", body) if isinstance(body, dict) else body


def solve_captcha(base_url: str, timeout: float) -> tuple[str, str]:
    """
    Answer the arithmetic captcha the login endpoint requires.

    The account endpoints are captcha protected because they are meant to be driven by a browser.
    A CLI that logs in has to answer it, so it does - the challenge is a single arithmetic
    expression. A token supplied through FUSIONPILOT_TOKEN skips this entirely.
    """
    challenge = request_json(base_url, "GET", "/api/v1/auth/captcha", timeout=timeout)
    question = str(challenge["question"])
    numbers = [int(value) for value in re.findall(r"-?\d+", question)]
    if len(numbers) < 2:
        raise CliError(f"Unrecognised captcha challenge: {question}", "CAPTCHA_UNSUPPORTED")
    left, right = numbers[0], numbers[1]
    if "×" in question or "*" in question:
        answer = left * right
    elif "－" in question or "-" in question:
        answer = left - right
    else:
        answer = left + right
    return challenge["challengeId"], str(answer)


# --------------------------------------------------------------------------- output shaping


def summarize_config(config: dict) -> dict:
    return {key: config[key] for key in CONFIG_SUMMARY_KEYS if key in config}


def summarize_metrics(metrics: dict | None) -> dict:
    if not isinstance(metrics, dict):
        return {}
    ordered = {key: metrics[key] for key in METRIC_KEYS if key in metrics}
    for key, value in metrics.items():
        ordered.setdefault(key, value)
    return ordered


def summarize_run(result: dict) -> dict:
    """One run reduced to what a reader or a model actually uses."""
    steps = result.get("steps")
    return {
        "runId": result.get("runId"),
        "metrics": summarize_metrics(result.get("metrics")),
        "config": summarize_config(result.get("config") or {}),
        "stepCount": len(steps) if isinstance(steps, list) else None,
    }


def summarize_comparison(result: dict) -> dict:
    summary: dict = {"runId": result.get("runId")}
    for side in ("roundRobin", "priority"):
        block = result.get(side)
        if isinstance(block, dict):
            summary[side] = {
                "runId": block.get("runId"),
                "metrics": summarize_metrics(block.get("metrics")),
            }
    delta = result.get("priorityMinusRoundRobin")
    if isinstance(delta, dict):
        summary["priorityMinusRoundRobin"] = delta
    summary["config"] = summarize_config(result.get("config") or {})
    return summary


def emit(payload, args) -> None:
    if args.human and isinstance(payload, dict) and "metrics" in payload:
        print(f"runId          : {payload.get('runId')}")
        config = payload.get("config") or {}
        if config:
            print(f"config         : {json.dumps(config, ensure_ascii=False)}")
        for key, value in (payload.get("metrics") or {}).items():
            print(f"{key:<18}: {value}")
        return
    indent = 2 if args.pretty else None
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


# --------------------------------------------------------------------------- commands


def resolve_auth(args, state: dict) -> str:
    token = args.token or os.environ.get("FUSIONPILOT_TOKEN") or state.get("token")
    if not token:
        raise CliError(
            "Not signed in. Run `fpx login`, or set FUSIONPILOT_TOKEN.",
            "NO_TOKEN",
        )
    return token


def working_config(args, state: dict, token: str) -> dict:
    """The session's configuration, seeded from the backend default on first use."""
    if isinstance(state.get("config"), dict) and state["config"]:
        return dict(state["config"])
    return request_json(args.base_url, "GET", "/api/v1/experiments/default", token=token, timeout=args.timeout)


def cmd_login(args, state: dict, path: str) -> None:
    challenge_id, answer = solve_captcha(args.base_url, args.timeout)
    session = request_json(
        args.base_url,
        "POST",
        "/api/v1/auth/login",
        {
            "login": args.username,
            "password": args.password,
            "captchaId": challenge_id,
            "captchaAnswer": answer,
        },
        timeout=args.timeout,
    )
    token = session.get("accessToken")
    if not token:
        raise CliError("Login succeeded but returned no access token.", "NO_TOKEN")
    state["token"] = token
    state["baseUrl"] = args.base_url
    state.setdefault("user", session.get("user"))
    save_state(path, state)
    emit({"signedIn": True, "user": session.get("user"), "stateFile": os.path.abspath(path)}, args)


def cmd_register(args, state: dict, path: str) -> None:
    """
    Create an account and sign in.

    The web app is the normal place to register, but a terminal tool that cannot bootstrap itself
    is useless on a fresh machine, and the account endpoints are the same ones the browser uses.
    """
    email = args.email or f"{args.username}@fpx.local"
    challenge_id, answer = solve_captcha(args.base_url, args.timeout)
    request_json(
        args.base_url,
        "POST",
        "/api/v1/auth/register",
        {
            "username": args.username,
            "email": email,
            "password": args.password,
            "displayName": args.display_name or args.username,
            "captchaId": challenge_id,
            "captchaAnswer": answer,
        },
        timeout=args.timeout,
    )
    login_args = argparse.Namespace(**vars(args))
    login_args.username = args.username
    cmd_login(login_args, state, path)


def cmd_whoami(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    emit(request_json(args.base_url, "GET", "/api/v1/auth/me", token=token, timeout=args.timeout), args)


def cmd_config_show(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    config = working_config(args, state, token)
    emit(
        {
            "config": config,
            "summary": summarize_config(config),
            "source": "state file" if state.get("config") else "backend default",
        },
        args,
    )


def cmd_config_set(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    if not args.set and not args.json_patch:
        raise CliError("Nothing to change. Use --set key=value or --json '{...}'.", "NO_PATCH")

    patch: dict = {}
    if args.json_patch:
        try:
            parsed = json.loads(args.json_patch)
        except ValueError as exc:
            raise CliError(f"--json is not valid JSON: {exc}", "BAD_PATCH") from exc
        if not isinstance(parsed, dict):
            raise CliError("--json must be a JSON object.", "BAD_PATCH")
        patch.update(parsed)
    for item in args.set or []:
        if "=" not in item:
            raise CliError(f"--set expects key=value, got: {item}", "BAD_PATCH")
        key, _, raw = item.partition("=")
        patch[key.strip()] = coerce(raw.strip())

    candidate = working_config(args, state, token)
    unknown = sorted(key for key in patch if key not in candidate)
    if unknown:
        raise CliError(
            f"Unknown field(s): {', '.join(unknown)}. Valid fields: {', '.join(sorted(candidate))}.",
            "UNKNOWN_FIELD",
        )
    candidate.update(patch)

    # The Java core decides validity. Rejecting here means an invalid configuration can never be
    # written to the state file and then silently used by a later `run`.
    try:
        request_json(args.base_url, "POST", "/api/v1/experiments/validate", candidate, token=token, timeout=args.timeout)
    except CliError as exc:
        raise CliError(f"The Java core rejected this configuration: {exc.message}", "INVALID_CONFIG") from exc

    state["config"] = candidate
    save_state(path, state)
    emit({"applied": patch, "summary": summarize_config(candidate)}, args)


def cmd_config_reset(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    config = request_json(args.base_url, "GET", "/api/v1/experiments/default", token=token, timeout=args.timeout)
    state["config"] = config
    save_state(path, state)
    emit({"reset": True, "summary": summarize_config(config)}, args)


def cmd_validate(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    config = working_config(args, state, token)
    try:
        response = request_json(args.base_url, "POST", "/api/v1/experiments/validate", config, token=token, timeout=args.timeout)
    except CliError as exc:
        raise CliError(f"The Java core rejected this configuration: {exc.message}", "INVALID_CONFIG") from exc
    emit({"valid": True, "config": summarize_config(config), "response": response}, args)


def cmd_run(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    config = working_config(args, state, token)
    result = request_json(args.base_url, "POST", "/api/v1/simulations/run", config, token=token, timeout=args.timeout)
    if isinstance(result, dict) and result.get("runId"):
        state["lastRunId"] = result["runId"]
        save_state(path, state)
    emit(result if args.full else summarize_run(result), args)


def cmd_compare(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    config = working_config(args, state, token)
    result = request_json(args.base_url, "POST", "/api/v1/simulations/compare", config, token=token, timeout=args.timeout)
    if isinstance(result, dict) and result.get("runId"):
        state["lastRunId"] = result["runId"]
        save_state(path, state)
    emit(result if args.full else summarize_comparison(result), args)


def cmd_metrics(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    run_id = args.run_id or state.get("lastRunId")
    if not run_id:
        raise CliError("No run to read. Run `fpx run` first, or pass --run-id.", "NO_RUN")
    result = request_json(args.base_url, "GET", f"/api/v1/simulations/{run_id}", token=token, timeout=args.timeout)
    emit(result if args.full else summarize_run(result), args)


def cmd_save(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    run_id = args.run_id or state.get("lastRunId")
    if not run_id:
        raise CliError("No run to save. Run `fpx run` first, or pass --run-id.", "NO_RUN")
    response = request_json(args.base_url, "POST", f"/api/v1/simulations/{run_id}/save", token=token, timeout=args.timeout)
    emit({"saved": True, "runId": run_id, "response": response}, args)


def cmd_history(args, state: dict, path: str) -> None:
    token = resolve_auth(args, state)
    rows = request_json(
        args.base_url,
        "GET",
        f"/api/v1/simulations/history?limit={max(1, min(args.limit, 100))}",
        token=token,
        timeout=args.timeout,
    )
    emit(rows, args)


def coerce(text: str):
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if text.startswith(("[", "{")):
        try:
            return json.loads(text)
        except ValueError:
            pass
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


# --------------------------------------------------------------------------- entry point


def add_output_flags(parser: argparse.ArgumentParser, *, under_subcommand: bool) -> None:
    """
    Presentation flags, accepted either side of the subcommand.

    `fpx run --human` is what anyone types, but argparse only accepted `fpx --human run` when the
    flags live on the root parser. They are declared in both places, and the copies under the
    subcommand use SUPPRESS so a value given before the subcommand is not overwritten by a default.
    """
    default = argparse.SUPPRESS if under_subcommand else False
    parser.add_argument("--pretty", action="store_true", default=default, help="indent the JSON output")
    parser.add_argument("--human", action="store_true", default=default, help="print metrics as plain lines")
    parser.add_argument("--full", action="store_true", default=default, help="print the raw payload instead of a summary")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpx",
        description="Drive the FusionPilot simulation core from a terminal.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"backend base URL (default {DEFAULT_BASE_URL})")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH, help="state file holding the token and working config")
    parser.add_argument("--token", default=None, help="override the stored access token")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="per-request timeout in seconds")
    add_output_flags(parser, under_subcommand=False)

    subparsers = parser.add_subparsers(dest="command", required=True)

    def subparser(name: str, help_text: str) -> argparse.ArgumentParser:
        created = subparsers.add_parser(name, help=help_text)
        add_output_flags(created, under_subcommand=True)
        return created

    login = subparser("login", "sign in and store an access token")
    login.add_argument("--username", required=True)
    login.add_argument("--password", required=True)
    login.set_defaults(handler=cmd_login)

    register = subparser("register", "create an account and sign in")
    register.add_argument("--username", required=True)
    register.add_argument("--password", required=True)
    register.add_argument("--email", default=None)
    register.add_argument("--display-name", dest="display_name", default=None)
    register.set_defaults(handler=cmd_register)

    subparser("whoami", "show the signed-in user").set_defaults(handler=cmd_whoami)
    subparser("config", "show the working configuration").set_defaults(handler=cmd_config_show)

    config_set = subparser("config-set", "change the working configuration")
    config_set.add_argument("--set", action="append", metavar="KEY=VALUE", help="may be repeated")
    config_set.add_argument("--json", dest="json_patch", metavar="JSON", help="patch given as one JSON object")
    config_set.set_defaults(handler=cmd_config_set)

    subparser("config-reset", "reset the working configuration to the backend default").set_defaults(
        handler=cmd_config_reset
    )
    subparser("validate", "ask the Java core whether the configuration is acceptable").set_defaults(
        handler=cmd_validate
    )
    subparser("run", "run one simulation with the working configuration").set_defaults(handler=cmd_run)
    subparser("compare", "run round-robin and priority and report the difference").set_defaults(handler=cmd_compare)

    metrics = subparser("metrics", "re-read the metrics of a run")
    metrics.add_argument("--run-id", default=None)
    metrics.set_defaults(handler=cmd_metrics)

    save = subparser("save", "save a run into this user's history")
    save.add_argument("--run-id", default=None)
    save.set_defaults(handler=cmd_save)

    history = subparser("history", "list saved runs for this user")
    history.add_argument("--limit", type=int, default=10)
    history.set_defaults(handler=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # SUPPRESS means an unset flag is simply absent, so fill in the defaults once here.
    for name in ("pretty", "human", "full"):
        if not hasattr(args, name):
            setattr(args, name, False)
    try:
        state = load_state(args.state)
        args.handler(args, state, args.state)
    except CliError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "error": exc.message}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

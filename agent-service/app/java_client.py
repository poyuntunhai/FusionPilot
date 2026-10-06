import httpx

from .config import JAVA_BASE_URL


class JavaBackendError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def _request(
    method: str,
    path: str,
    payload: dict | None = None,
    timeout: float = 10.0,
    authorization: str | None = None,
) -> dict:
    try:
        async with httpx.AsyncClient(base_url=JAVA_BASE_URL, timeout=timeout) as client:
            headers = {"Authorization": authorization} if authorization else None
            response = await client.request(method, path, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise JavaBackendError(
            "JAVA_UNAVAILABLE",
            f"Java backend is unavailable: {exc}",
        ) from exc

    if response.status_code >= 400:
        try:
            error_payload = response.json()
            message = error_payload.get("message", f"Java backend returned HTTP {response.status_code}")
        except ValueError:
            message = f"Java backend returned HTTP {response.status_code}"
        raise JavaBackendError(
            "JAVA_UNAUTHORIZED" if response.status_code == 401 else "JAVA_REQUEST_FAILED",
            message,
            response.status_code,
        )
    payload_data = response.json()
    if payload_data.get("success") is False:
        raise JavaBackendError(
            "JAVA_RESPONSE_ERROR",
            payload_data.get("message", "Java backend returned an error"),
        )
    return payload_data["data"]


async def get_default_config() -> dict:
    return await _request("GET", "/api/v1/experiments/default")


async def get_current_user(authorization: str) -> dict:
    return await _request("GET", "/api/v1/auth/me", authorization=authorization)


async def save_agent_trace(trace: dict, authorization: str) -> None:
    await _request(
        "POST",
        "/api/v1/agent/sessions",
        trace,
        authorization=authorization,
    )


async def update_agent_trace(trace: dict, authorization: str) -> None:
    await _request(
        "PUT",
        f"/api/v1/agent/sessions/{trace['trace_id']}",
        trace,
        authorization=authorization,
    )


async def get_agent_trace(trace_id: str, authorization: str) -> dict | None:
    try:
        return await _request(
            "GET",
            f"/api/v1/agent/sessions/{trace_id}",
            authorization=authorization,
        )
    except JavaBackendError as exc:
        if exc.status_code == 404:
            return None
        raise


async def validate_experiment(config: dict) -> dict:
    return await _request("POST", "/api/v1/experiments/validate", config)


async def run_simulation(config: dict, authorization: str | None = None) -> dict:
    return await _request(
        "POST",
        "/api/v1/simulations/run",
        config,
        timeout=30.0,
        authorization=authorization,
    )


async def compare_scheduling_policies(config: dict, authorization: str | None = None) -> dict:
    return await _request(
        "POST",
        "/api/v1/simulations/compare",
        config,
        timeout=30.0,
        authorization=authorization,
    )

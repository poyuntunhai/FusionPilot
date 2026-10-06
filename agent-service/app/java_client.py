import httpx

from .config import JAVA_BASE_URL


class JavaBackendError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def _request(method: str, path: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
    try:
        async with httpx.AsyncClient(base_url=JAVA_BASE_URL, timeout=timeout) as client:
            response = await client.request(method, path, json=payload)
    except httpx.HTTPError as exc:
        raise JavaBackendError(
            "JAVA_UNAVAILABLE",
            f"Java backend is unavailable: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise JavaBackendError(
            "JAVA_REQUEST_FAILED",
            f"Java backend returned HTTP {response.status_code}",
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


async def validate_experiment(config: dict) -> dict:
    return await _request("POST", "/api/v1/experiments/validate", config)


async def run_simulation(config: dict) -> dict:
    return await _request(
        "POST",
        "/api/v1/simulations/run",
        config,
        timeout=30.0,
    )


async def compare_scheduling_policies(config: dict) -> dict:
    return await _request(
        "POST",
        "/api/v1/simulations/compare",
        config,
        timeout=30.0,
    )
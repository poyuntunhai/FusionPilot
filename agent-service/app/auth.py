from fastapi import Header, HTTPException

from .java_client import JavaBackendError, get_current_user


async def require_agent_user(
    authorization: str | None = Header(default=None),
) -> dict:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Authentication is required."},
        )
    try:
        user = await get_current_user(authorization)
    except JavaBackendError as exc:
        if exc.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "Authentication is required."},
            ) from exc
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": exc.message,
                "dependency": "java-backend",
            },
        ) from exc
    return {
        "authorization": authorization,
        "user": user,
        "user_id": user["userId"],
    }

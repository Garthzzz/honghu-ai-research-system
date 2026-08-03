from __future__ import annotations

from datetime import datetime, timezone

from .constants import API_CONTRACT_VERSION, MODULE_NAME


def envelope(data=None, ok: bool = True, error: dict | None = None, status: int = 200):
    body = {
        "ok": ok,
        "contract_version": API_CONTRACT_VERSION,
        "module": MODULE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if ok:
        body["data"] = data
    else:
        body["error"] = error or {"code": "OPP_UNKNOWN", "message": "未知机会透镜错误"}
    return body, status


def error(code: str, message: str, status: int = 400, detail=None):
    err = {"code": code, "message": message}
    if detail is not None:
        err["detail"] = detail
    return envelope(ok=False, error=err, status=status)

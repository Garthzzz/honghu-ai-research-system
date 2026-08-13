from __future__ import annotations

"""Narrow stdin/stdout bridge to the configured Windows keyring backend.

The deployment bootstrap invokes this file from an exact Git checkout.  It
accepts a JSON request on stdin and never writes a secret to stdout or disk.
"""

import json
import sys


def _failure_label(exc: BaseException) -> str:
    code = getattr(exc, "winerror", None)
    if code is None and getattr(exc, "args", None):
        candidate = exc.args[0]
        if isinstance(candidate, int):
            code = candidate
    if code == 1312:
        return "winvault_logon_session_unavailable"
    return f"{type(exc).__module__}.{type(exc).__name__}"


def main() -> int:
    payload = json.load(sys.stdin)
    action = str(payload.get("action") or "")
    service = str(payload.get("service") or "")
    account = str(payload.get("account") or "")
    if not service or not account:
        raise SystemExit("keyring service and account are required")

    import keyring
    from keyring.backends.Windows import WinVaultKeyring

    # Do not let a machine-specific backend selector silently redirect a
    # production password to a file, plaintext, or null backend.
    keyring.set_keyring(WinVaultKeyring())
    try:
        if action == "set":
            password = str(payload.get("password") or "")
            if len(password) < 32:
                raise SystemExit("keyring secret is below the minimum length")
            keyring.set_password(service, account, password)
            if keyring.get_password(service, account) != password:
                raise SystemExit("keyring round-trip verification failed")
        elif action == "verify":
            if not keyring.get_password(service, account):
                raise SystemExit("keyring entry is unavailable")
        elif action == "delete":
            try:
                keyring.delete_password(service, account)
            except keyring.errors.PasswordDeleteError:
                pass
        else:
            raise SystemExit("unsupported keyring action")
    except SystemExit:
        raise
    except BaseException as exc:
        raise SystemExit(f"keyring operation failed: {_failure_label(exc)}") from None

    print(json.dumps({"ok": True, "action": action, "service": service, "account": account}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

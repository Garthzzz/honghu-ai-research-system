from __future__ import annotations

"""Real browser acceptance for the production PostgreSQL analyst-note UI.

The password is loaded from Windows Credential Manager.  A CA-verified HTTP
probe establishes the TLS/release identity before Chromium is allowed to use
the self-managed certificate for UI automation.  The test note is soft-deleted
through the same authenticated browser session; revision/audit remain durable.
"""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BrowserAcceptanceError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _password(service: str, account: str) -> str:
    import keyring

    value = keyring.get_password(service, account)
    if not value:
        raise BrowserAcceptanceError("browser acceptance credential is unavailable")
    return value


def verify_tls_health(
    *, base_url: str, ca_certificate: Path, expected_commit: str
) -> dict[str, Any]:
    import httpx

    with httpx.Client(verify=str(ca_certificate), timeout=15) as client:
        response = client.get(f"{base_url}/api/health")
        response.raise_for_status()
        health = response.json()
    if (
        not health.get("ok")
        or health.get("viewer_mode") != "production_postgresql"
        or (health.get("release") or {}).get("commit_sha") != expected_commit
        or (health.get("user_content") or {}).get("authority_state") != "S3"
        or (health.get("user_content") or {}).get("security_ready") is not True
    ):
        raise BrowserAcceptanceError("browser target is not the exact S3 production Viewer")
    return health


def run_browser_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    password = _password(args.credential_service, args.credential_account)
    health = verify_tls_health(
        base_url=args.base_url,
        ca_certificate=args.ca_certificate,
        expected_commit=args.expected_commit,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    screenshot = args.output_dir / "analyst_note_browser_acceptance.png"
    content = f"browser acceptance {int(time.time())}"
    note_key: str | None = None
    revision: int | None = None
    started = time.monotonic()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.browser_channel, headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        response = page.goto(
            f"{args.base_url}{args.page_path}", wait_until="networkidle", timeout=45_000
        )
        if response is None or response.status != 200:
            raise BrowserAcceptanceError("company page did not render in the browser")
        page.locator("#analystNoteAuth .an-auth-subject").fill(args.principal)
        page.locator("#analystNoteAuth .an-auth-password").fill(password)
        page.locator("#analystNoteAuth .an-auth-login").click()
        page.locator("#analystNoteAuth .an-auth-status").filter(
            has_text=f"已登录：{args.principal}"
        ).wait_for(timeout=20_000)
        editor = page.locator("details.an-editor").first
        editor.locator("summary").click()
        editor.locator(".an-new-note").fill(content)
        editor.locator(".an-add-note").click()
        editor.locator(".an-note-status").filter(has_text="已添加").wait_for(timeout=20_000)
        editor.locator(".an-note-body").filter(has_text=content).wait_for(timeout=20_000)
        page.screenshot(path=str(screenshot), full_page=True)
        entity_id = editor.get_attribute("data-company-id")
        if not entity_id:
            raise BrowserAcceptanceError("company editor has no stable entity identity")
        listed = page.evaluate(
            """async (entityId) => {
              const response=await fetch('/api/analyst_note/company/'+entityId,{credentials:'same-origin'});
              return {status:response.status,body:await response.json()};
            }""",
            entity_id,
        )
        matches = [
            item
            for item in listed.get("body", {}).get("notes", [])
            if item.get("content") == content
        ]
        if listed.get("status") != 200 or len(matches) != 1:
            raise BrowserAcceptanceError("browser-created note was not uniquely readable")
        note_key = str(matches[0]["note_key"])
        revision = int(matches[0]["revision"])
        deleted = page.evaluate(
            """async ({noteKey,revision}) => {
              const session=await (await fetch('/api/user-content/session',{credentials:'same-origin'})).json();
              const operation='browser-cleanup:'+crypto.randomUUID();
              const response=await fetch('/api/analyst_note/key/'+encodeURIComponent(noteKey),{
                method:'DELETE',credentials:'same-origin',
                headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf_token,'X-Idempotency-Key':operation},
                body:JSON.stringify({expected_revision:revision})
              });
              return {status:response.status,body:await response.json()};
            }""",
            {"noteKey": note_key, "revision": revision},
        )
        if (
            deleted.get("status") != 200
            or not deleted.get("body", {}).get("ok")
            or deleted.get("body", {}).get("note", {}).get("deleted") is not True
        ):
            raise BrowserAcceptanceError("browser acceptance cleanup did not soft-delete")
        browser.close()
    core = {
        "schema_version": "honghu.user_content_browser_acceptance.v1",
        "status": "pass",
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_identity": args.client_identity,
        "expected_commit": args.expected_commit,
        "health_process_pid": (health.get("production_process") or {}).get("pid"),
        "page_path": args.page_path,
        "principal": args.principal,
        "browser_channel": args.browser_channel,
        "login_verified": True,
        "create_and_list_verified": True,
        "soft_delete_verified": True,
        "note_key_sha256": hashlib.sha256(str(note_key).encode("utf-8")).hexdigest(),
        "created_revision": revision,
        "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "tls_verified_before_browser": True,
        "browser_ignored_private_ca_only_after_verified_probe": True,
        "credential_recorded": False,
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca-certificate", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--page-path", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--credential-service", required=True)
    parser.add_argument("--credential-account", required=True)
    parser.add_argument("--client-identity", required=True)
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.ca_certificate.is_file():
        raise BrowserAcceptanceError("Viewer CA certificate is missing")
    result = run_browser_acceptance(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

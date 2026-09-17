from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8080").rstrip("/")
MOCK_BANKING_URL = os.getenv("MOCK_BANKING_URL", "http://mock-banking:8081").rstrip("/")
FIXTURE_ADMIN_TOKEN = os.environ["FIXTURE_ADMIN_TOKEN"]
PORT = int(os.getenv("PORT", "8090"))
INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_bytes()


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {error.code} {detail}") from error


def create_persona(persona: str, months: int) -> dict[str, Any]:
    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    email = f"fixture-{suffix}@moaje.test"
    pin = "123456"
    owner_ci = f"TEST-CI-FIXTURE-{suffix}"
    product_name = f"Fixture Account {suffix}"
    fixture_run_id = f"fixture-{suffix}"

    register = request_json(
        "POST",
        f"{GATEWAY_URL}/api/v1/auth/register",
        {"email": email, "pin": pin},
    )
    login = request_json(
        "POST",
        f"{GATEWAY_URL}/api/v1/auth/login",
        {"email": email, "pin": pin, "device_info": "test-fixture-console"},
    )
    jwt = login["data"]["access_token"]
    authorization = {"Authorization": f"Bearer {jwt}"}

    account = request_json(
        "POST",
        f"{GATEWAY_URL}/api/v1/banking/accounts",
        {
            "ci": owner_ci,
            "userName": "Fixture Persona",
            "phoneNumber": "01000000004",
            "bankCode": "001",
            "productName": product_name,
            "initialBalance": 5_000_000,
        },
        authorization,
    )
    account_id = str(account["accountId"])

    fixture = request_json(
        "POST",
        f"{MOCK_BANKING_URL}/internal/test-fixtures/personas",
        {
            "fixtureRunId": fixture_run_id,
            "ownerCi": owner_ci,
            "bankCode": "001",
            "productName": product_name,
            "persona": persona,
            "months": months,
        },
        {"X-Fixture-Token": FIXTURE_ADMIN_TOKEN},
    )

    detail_url = f"{GATEWAY_URL}/api/v1/assets/accounts/{account_id}/detail"
    for _ in range(20):
        try:
            request_json("GET", detail_url, headers=authorization)
            break
        except RuntimeError:
            time.sleep(1)
    else:
        raise RuntimeError("Asset account projection was not created within 20 seconds")

    request_json(
        "POST",
        f"{GATEWAY_URL}/api/v1/assets/accounts/{account_id}/refresh",
        headers=authorization,
    )

    aggregates = []
    for year_month in fixture["months"]:
        monthly = request_json(
            "GET",
            f"{GATEWAY_URL}/api/v1/assets/cashflow/monthly?yearMonth={year_month}",
            headers=authorization,
        )
        categories = request_json(
            "GET",
            f"{GATEWAY_URL}/api/v1/assets/cashflow/category?yearMonth={year_month}",
            headers=authorization,
        )
        aggregates.append({"yearMonth": year_month, "monthly": monthly, "categories": categories["categories"]})

    return {
        "fixtureRunId": fixture_run_id,
        "persona": persona,
        "months": fixture["months"],
        "createdTransactionCount": fixture["createdTransactionCount"],
        "userId": str(register["data"]["user_id"]),
        "email": email,
        "pin": pin,
        "accountId": account_id,
        "aggregates": aggregates,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(INDEX_HTML)))
            self.end_headers()
            self.wfile.write(INDEX_HTML)
            return
        if self.path == "/health":
            self.write_json(200, {"status": "UP"})
            return
        self.write_json(404, {"message": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/api/personas":
            self.write_json(404, {"message": "Not found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            persona = str(body.get("persona", "BALANCED_STUDENT"))
            months = int(body.get("months", 3))
            if persona not in {"BALANCED_STUDENT", "CAFE_AND_DINING", "COMMUTER", "STUDY_FOCUSED"}:
                raise ValueError("Unknown persona")
            if months < 1 or months > 6:
                raise ValueError("months must be between 1 and 6")
            self.write_json(201, create_persona(persona, months))
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.write_json(400, {"message": str(error)})
        except Exception as error:
            self.write_json(502, {"message": str(error)})

    def write_json(self, status: int, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"fixture-console: {format % args}")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

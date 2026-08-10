from __future__ import annotations

from typing import Any

import httpx


class MolizhishuError(Exception):
    def __init__(
        self,
        code: int | None,
        message: str,
        http_status: int | None = None,
        body: Any = None,
    ):
        super().__init__(f"molizhishu error code={code} message={message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.body = body


class MolizhishuClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def submit_task(self, payload: dict) -> dict:
        url = f"{self.base_url}/task/batch/shared"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code // 100 != 2:
            raise MolizhishuError(
                body.get("code"),
                body.get("message", "http error"),
                response.status_code,
                body,
            )
        if body.get("success") is not True or body.get("code") != 200:
            raise MolizhishuError(
                body.get("code"),
                body.get("message", "business error"),
                response.status_code,
                body,
            )
        return body["data"]

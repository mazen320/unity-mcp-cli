from __future__ import annotations

import json
import socket
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class UnityMCPClientError(RuntimeError):
    """Base client error."""


class UnityMCPConnectionError(UnityMCPClientError):
    """Raised when the Unity bridge cannot be reached."""


class UnityMCPHTTPError(UnityMCPClientError):
    """Raised for HTTP errors returned by the Unity bridge."""

    def __init__(self, status_code: int, message: str, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class UnityMCPClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        request_timeout: float = 60.0,
        queue_poll_interval: float = 0.15,
        queue_poll_max: float = 1.5,
        queue_poll_timeout: float = 120.0,
        agent_id: str = "cli-anything-unity-mcp",
        use_queue: bool = True,
    ) -> None:
        self.host = host
        self.request_timeout = request_timeout
        self.queue_poll_interval = queue_poll_interval
        self.queue_poll_max = queue_poll_max
        self.queue_poll_timeout = queue_poll_timeout
        self.agent_id = agent_id
        self.use_queue = use_queue

    def ping(self, port: int, timeout: float = 3.0) -> Dict[str, Any]:
        return self.get_api(port, "ping", timeout=timeout)

    def get_api(
        self,
        port: int,
        api_path: str,
        query: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        return self._request_json(
            "GET",
            port,
            api_path,
            query=query,
            timeout=timeout,
        )

    def post_api(
        self,
        port: int,
        api_path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        return self._request_json(
            "POST",
            port,
            api_path,
            payload=payload or {},
            timeout=timeout,
        )

    def call_route(
        self,
        port: int,
        route: str,
        params: Optional[Dict[str, Any]] = None,
        use_queue: Optional[bool] = None,
    ) -> Any:
        payload = params or {}
        queue_enabled = self.use_queue if use_queue is None else use_queue
        if queue_enabled:
            try:
                return self._call_route_via_queue(port, route, payload)
            except UnityMCPHTTPError as exc:
                if exc.status_code != 404:
                    raise
        return self.post_api(port, route, payload)

    def get_queue_info(self, port: int) -> Dict[str, Any]:
        return self.get_api(port, "queue/info")

    def _call_route_via_queue(
        self,
        port: int,
        route: str,
        params: Dict[str, Any],
    ) -> Any:
        submission = self.post_api(
            port,
            "queue/submit",
            {
                "apiPath": route,
                "method": "POST",
                "body": json.dumps(params),
                "agentId": self.agent_id,
            },
        )
        ticket_id = submission.get("ticketId")
        if ticket_id is None:
            raise UnityMCPClientError(
                f"Unity queue submission for {route} did not return a ticket id."
            )

        deadline = time.monotonic() + self.queue_poll_timeout
        interval = self.queue_poll_interval
        while time.monotonic() < deadline:
            status = self.get_api(
                port,
                "queue/status",
                query={"ticketId": ticket_id},
                timeout=10.0,
            )
            state = str(status.get("status", "")).lower()
            if state == "completed":
                return status.get("result", status)
            if state in {"failed", "timedout"}:
                raise UnityMCPClientError(
                    status.get("error")
                    or f"Unity queue request for {route} failed with status {status.get('status')}."
                )
            time.sleep(interval)
            interval = min(interval * 1.5, self.queue_poll_max)

        raise UnityMCPClientError(
            f"Timed out waiting for Unity queue request {ticket_id} ({route})."
        )

    def _request_json(
        self,
        method: str,
        port: int,
        api_path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        url = self._build_url(port, api_path, query=query)
        headers = {
            "Accept": "application/json",
            "X-Agent-Id": self.agent_id,
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")

        request = Request(url=url, data=body, headers=headers, method=method.upper())

        try:
            with urlopen(request, timeout=timeout or self.request_timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            parsed = None
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            message = raw or getattr(exc, "reason", "HTTP error")
            if isinstance(parsed, dict) and parsed.get("error"):
                message = str(parsed["error"])
            raise UnityMCPHTTPError(exc.code, message, parsed) from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise UnityMCPConnectionError(
                f"Could not reach Unity bridge at {self.host}:{port}: {reason}"
            ) from exc
        except socket.timeout as exc:
            raise UnityMCPConnectionError(
                f"Timed out talking to Unity bridge at {self.host}:{port}."
            ) from exc

    def _build_url(
        self,
        port: int,
        api_path: str,
        query: Optional[Dict[str, Any]] = None,
    ) -> str:
        base = f"http://{self.host}:{port}/api/{api_path}"
        if not query:
            return base
        clean_query = {key: value for key, value in query.items() if value is not None}
        return base + "?" + urlencode(clean_query)

"""Minimal Apify REST client.

Deliberately not the official SDK: this needs to run in locked-down
environments, surface egress policy denials clearly rather than burying them
in retries, and keep the dependency surface to `requests`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)

API_BASE = "https://api.apify.com/v2"

TERMINAL_OK = {"SUCCEEDED"}
TERMINAL_BAD = {"FAILED", "ABORTED", "TIMED-OUT"}


class ApifyError(RuntimeError):
    """Any Apify call that cannot be completed."""


class ApifyAccessDenied(ApifyError):
    """403/407 — credentials rejected, or network policy blocked the host.

    Kept distinct because the correct response is to stop and report, never to
    retry. In a proxied environment a 403 on CONNECT is an org egress denial
    and no amount of backoff will clear it.
    """


class ApifyRunFailed(ApifyError):
    def __init__(self, run_id: str, status: str, actor_id: str):
        super().__init__(
            f"Apify run {run_id} for actor {actor_id!r} ended with status {status}. "
            f"Inspect the log at https://console.apify.com/actors/runs/{run_id}"
        )
        self.run_id = run_id
        self.status = status


@dataclass
class RunResult:
    run_id: str
    status: str
    dataset_id: str | None
    actor_id: str


class ApifyClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: int = 60,
        max_retries: int = 4,
        session: requests.Session | None = None,
    ):
        if not token:
            raise ApifyError("empty Apify token")
        self._token = token
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    # ---------------- transport ----------------

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        delay = 2.0
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._session.request(method, url, timeout=self._timeout, **kwargs)
            except requests.exceptions.SSLError as exc:
                # Almost always a proxy CA that the client is not reading.
                raise ApifyError(
                    f"TLS verification failed for {url}. If this session routes through "
                    "an inspecting proxy, point requests at its CA bundle via "
                    "REQUESTS_CA_BUNDLE. Never disable verification."
                ) from exc
            except requests.exceptions.ProxyError as exc:
                raise ApifyAccessDenied(
                    f"The proxy refused a tunnel to {url}. This is an egress policy "
                    "denial, not a transient error: api.apify.com must be allowlisted "
                    "for this environment. Reported rather than retried."
                ) from exc
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt == self._max_retries:
                    break
                log.warning("network error on %s %s (attempt %d): %s", method, url, attempt, exc)
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code in (401, 403, 407):
                raise ApifyAccessDenied(
                    f"{resp.status_code} from {url}. Either the APIFY_TOKEN is invalid or "
                    f"lacks access to this actor, or network policy blocked the host. "
                    f"Body: {resp.text[:400]}"
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self._max_retries:
                    raise ApifyError(
                        f"{resp.status_code} from {url} after {attempt} attempts: {resp.text[:400]}"
                    )
                retry_after = resp.headers.get("Retry-After")
                sleep_for = float(retry_after) if retry_after and retry_after.isdigit() else delay
                log.warning("%s from %s, retrying in %.1fs", resp.status_code, url, sleep_for)
                time.sleep(sleep_for)
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise ApifyError(f"{resp.status_code} from {url}: {resp.text[:400]}")
            return resp

        raise ApifyError(f"network failure on {method} {url}: {last_exc}")

    # ---------------- api surface ----------------

    def whoami(self) -> dict[str, Any]:
        """Verify the token works. Cheapest possible reachability probe."""
        return self._request("GET", "/users/me").json().get("data", {})

    def get_actor(self, actor_id: str) -> dict[str, Any]:
        """Fetch actor metadata; used by `doctor` to confirm an actor exists."""
        return self._request("GET", f"/acts/{actor_id}").json().get("data", {})

    def start_run(self, actor_id: str, run_input: dict[str, Any]) -> RunResult:
        resp = self._request(
            "POST",
            f"/acts/{actor_id}/runs",
            json=run_input,
            headers={"Content-Type": "application/json"},
        )
        data = resp.json().get("data", {})
        run_id = data.get("id")
        if not run_id:
            raise ApifyError(f"actor {actor_id!r} start returned no run id: {resp.text[:300]}")
        return RunResult(
            run_id=run_id,
            status=data.get("status", "READY"),
            dataset_id=data.get("defaultDatasetId"),
            actor_id=actor_id,
        )

    def wait_for_run(
        self, run: RunResult, *, poll_seconds: int = 10, max_wait_seconds: int = 3600
    ) -> RunResult:
        waited = 0
        while True:
            data = self._request("GET", f"/actor-runs/{run.run_id}").json().get("data", {})
            status = data.get("status", "UNKNOWN")
            run = RunResult(
                run_id=run.run_id,
                status=status,
                dataset_id=data.get("defaultDatasetId") or run.dataset_id,
                actor_id=run.actor_id,
            )
            if status in TERMINAL_OK:
                return run
            if status in TERMINAL_BAD:
                raise ApifyRunFailed(run.run_id, status, run.actor_id)
            if waited >= max_wait_seconds:
                raise ApifyError(
                    f"run {run.run_id} still {status} after {max_wait_seconds}s; "
                    "abort or raise max_wait_seconds"
                )
            time.sleep(poll_seconds)
            waited += poll_seconds
            log.info("run %s status=%s waited=%ds", run.run_id, status, waited)

    def iter_dataset_items(
        self, dataset_id: str, *, page_size: int = 500
    ) -> Iterator[dict[str, Any]]:
        """Stream dataset items, paginating so large channel scrapes stay bounded in memory."""
        offset = 0
        while True:
            resp = self._request(
                "GET",
                f"/datasets/{dataset_id}/items",
                params={"offset": offset, "limit": page_size, "clean": "true", "format": "json"},
            )
            items = resp.json()
            if not isinstance(items, list):
                raise ApifyError(f"unexpected dataset payload for {dataset_id}: {str(items)[:300]}")
            if not items:
                return
            yield from items
            if len(items) < page_size:
                return
            offset += len(items)

    def run_and_collect(
        self,
        actor_id: str,
        run_input: dict[str, Any],
        *,
        poll_seconds: int = 10,
        max_wait_seconds: int = 3600,
    ) -> list[dict[str, Any]]:
        run = self.start_run(actor_id, run_input)
        log.info("started actor %s run %s", actor_id, run.run_id)
        run = self.wait_for_run(run, poll_seconds=poll_seconds, max_wait_seconds=max_wait_seconds)
        if not run.dataset_id:
            raise ApifyError(f"run {run.run_id} succeeded but exposed no dataset")
        return list(self.iter_dataset_items(run.dataset_id))

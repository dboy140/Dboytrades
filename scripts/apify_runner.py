"""Apify execution layer: connectivity diagnosis, retries, spend guard.

Two failure classes are treated very differently. A transient fault (timeout,
5xx, rate limit) is retried with backoff. A policy denial (403/407, or a proxy
refusing the tunnel) is raised immediately and reported, because retrying an
egress policy decision just burns time and hides the real problem.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import config as cfg
from .util import record_cost

log = logging.getLogger(__name__)


class ApifyBlocked(RuntimeError):
    """Credentials rejected or the host is blocked by network policy.

    Never retried. The fix is administrative, not temporal.
    """


class ApifyTransient(RuntimeError):
    """Retryable fault."""


class SpendGuard(RuntimeError):
    """A run would cost more than the configured threshold."""


@dataclass
class RunOutcome:
    actor_id: str
    run_id: str
    status: str
    items: list[dict[str, Any]]
    cost_usd: float
    runtime_seconds: float


def _classify(exc: Exception) -> Exception:
    """Map a client exception onto our two failure classes."""
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()

    blocked_markers = (
        "403", "407", "401", "proxyerror", "connect tunnel failed",
        "forbidden", "unauthorized", "invalid token", "authentication",
    )
    if any(m in low for m in blocked_markers):
        return ApifyBlocked(
            f"{text}\n\n"
            "This is an access or egress-policy problem, not a transient one. "
            "Confirm APIFY_TOKEN is valid and that api.apify.com is allowlisted "
            "for this environment. Not retried by design."
        )
    return ApifyTransient(text)


class ApifyRunner:
    def __init__(self, token: str | None = None, *, dry_run: bool = False):
        self.dry_run = dry_run
        self._token = token
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from apify_client import ApifyClient

            self._client = ApifyClient(self._token or cfg.apify_token())
        return self._client

    # ------------------------------------------------------- diagnostics ----

    def probe(self) -> dict[str, Any]:
        """Cheapest possible reachability + auth check."""
        result: dict[str, Any] = {"token_present": False, "reachable": False, "user": None, "error": ""}
        try:
            cfg.apify_token()
            result["token_present"] = True
        except RuntimeError as exc:
            result["error"] = str(exc)
            return result

        try:
            me = self.client.user("me").get()
            result["reachable"] = True
            result["user"] = (me or {}).get("username") or (me or {}).get("id")
        except Exception as exc:
            result["error"] = str(_classify(exc))
        return result

    def actor_exists(self, actor_id: str) -> tuple[bool, str]:
        try:
            info = self.client.actor(actor_id).get()
            if info:
                return True, info.get("title", "")
            return False, "actor not found"
        except Exception as exc:
            classified = _classify(exc)
            if isinstance(classified, ApifyBlocked):
                raise classified
            return False, str(classified)[:200]

    # -------------------------------------------------------------- runs ----

    @retry(
        retry=retry_if_exception_type(ApifyTransient),
        stop=stop_after_attempt(cfg.RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=cfg.RETRY_BACKOFF_SECONDS, min=2, max=30),
        reraise=True,
    )
    def _call_run(self, actor_id: str, run_input: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.client.actor(actor_id).call(
                run_input=run_input,
                timeout_secs=cfg.RUN_MAX_WAIT_SECONDS,
            )
        except Exception as exc:
            raise _classify(exc) from exc

    @retry(
        retry=retry_if_exception_type(ApifyTransient),
        stop=stop_after_attempt(cfg.RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=cfg.RETRY_BACKOFF_SECONDS, min=2, max=30),
        reraise=True,
    )
    def _fetch_items(self, dataset_id: str) -> list[dict[str, Any]]:
        try:
            return list(self.client.dataset(dataset_id).iterate_items())
        except Exception as exc:
            raise _classify(exc) from exc

    def run(
        self,
        actor_id: str,
        run_input: dict[str, Any],
        *,
        operation: str = "run",
        estimated_cost_usd: float = 0.0,
        confirm_over_threshold: bool = True,
    ) -> RunOutcome:
        if confirm_over_threshold and estimated_cost_usd > cfg.COST_ALERT_THRESHOLD_USD:
            raise SpendGuard(
                f"{operation} on {actor_id} is estimated at ${estimated_cost_usd:.2f}, "
                f"above the ${cfg.COST_ALERT_THRESHOLD_USD:.2f} threshold. "
                "Confirm before running."
            )

        if self.dry_run:
            log.info("[dry-run] would run %s with %d input keys", actor_id, len(run_input))
            return RunOutcome(actor_id, "dry-run", "DRY_RUN", [], 0.0, 0.0)

        started = time.time()
        run = self._call_run(actor_id, run_input)
        if not run:
            raise ApifyTransient(f"actor {actor_id} returned no run object")

        status = run.get("status", "UNKNOWN")
        run_id = run.get("id", "")
        if status != "SUCCEEDED":
            raise ApifyTransient(
                f"run {run_id} for {actor_id} ended {status}; "
                f"see https://console.apify.com/actors/runs/{run_id}"
            )

        dataset_id = run.get("defaultDatasetId")
        items = self._fetch_items(dataset_id) if dataset_id else []
        cost = float(run.get("usageTotalUsd") or 0.0)
        runtime = time.time() - started

        total = record_cost(operation, actor_id, cost, units=len(items))
        log.info(
            "%s: %d items, $%.4f (running total $%.4f), %.1fs",
            operation, len(items), cost, total, runtime,
        )
        return RunOutcome(actor_id, run_id, status, items, cost, runtime)

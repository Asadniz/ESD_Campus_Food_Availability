"""Service-style caller for the Campus Food API: timeout, limited retry with backoff, circuit breaker."""
import argparse
import random
import time
import uuid

import requests

CONNECT_TIMEOUT = 1.0
READ_TIMEOUT = 2.0
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5            # delays: 0.5s, 1s (+ jitter)
FAILURE_THRESHOLD = 3         # consecutive failed attempts before the breaker opens
RECOVERY_SECONDS = 10.0
RETRY_STATUSES = {502, 503, 504}


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, threshold: int, recovery: float):
        self.threshold, self.recovery = threshold, recovery
        self.state, self.failures, self.opened_at = "closed", 0, 0.0

    def _to(self, state: str) -> None:
        if state != self.state:
            log(f"[breaker] {self.state} -> {state}")
            self.state = state

    def allow(self) -> bool:
        if self.state == "open":
            if time.monotonic() - self.opened_at < self.recovery:
                return False
            self._to("half_open")          # recovery period over: let one trial call through
        return True

    def success(self) -> None:
        self.failures = 0
        self._to("closed")

    def failure(self) -> None:
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.threshold:
            self.opened_at = time.monotonic()
            self._to("open")


class Client:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.http = requests.Session()
        self.breaker = CircuitBreaker(FAILURE_THRESHOLD, RECOVERY_SECONDS)

    def request(self, method: str, path: str, *, json=None, headers=None):
        headers = dict(headers or {})
        # Retry only when repeating is safe: reads, or writes protected by an Idempotency-Key.
        safe = method == "GET" or "Idempotency-Key" in headers
        attempts = MAX_ATTEMPTS if safe else 1
        for attempt in range(1, attempts + 1):
            if not self.breaker.allow():
                log(f"{method} {path} BLOCKED: breaker is open, no request sent")
                raise CircuitOpenError(path)
            try:
                resp = self.http.request(method, self.base + path, json=json, headers=headers,
                                         timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            except (requests.Timeout, requests.ConnectionError) as exc:
                reason, retryable = type(exc).__name__, True
            else:
                if resp.status_code < 500:   # 2xx/3xx/4xx: the server answered properly
                    self.breaker.success()
                    log(f"{method} {path} -> {resp.status_code} (attempt {attempt})")
                    return resp
                reason, retryable = f"HTTP {resp.status_code}", resp.status_code in RETRY_STATUSES
            self.breaker.failure()
            log(f"{method} {path} attempt {attempt}/{attempts} failed: {reason}")
            if not retryable:
                break
            if attempt < attempts and self.breaker.state != "open":
                delay = BACKOFF_BASE * 2 ** (attempt - 1) + random.uniform(0, 0.1)
                log(f"  retrying in {delay:.2f}s")
                time.sleep(delay)
        raise RuntimeError(f"{method} {path} failed")


def set_delay(base: str, staff_key: str, delay_ms: int) -> None:
    headers = {"X-Staff-Key": staff_key}
    if delay_ms:
        requests.post(f"{base}/admin/faults", json={"menu_delay_ms": delay_ms}, headers=headers, timeout=5)
    else:
        requests.delete(f"{base}/admin/faults", headers=headers, timeout=5)
    log(f"[demo] menu delay set to {delay_ms} ms")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--staff-key", default="staff-demo-key")
    p.add_argument("--delay-ms", type=int, default=3000, help="must exceed the 2 s read timeout")
    args = p.parse_args()
    client = Client(args.base_url)

    def read_menu(label: str) -> None:
        log(f"--- {label}")
        try:
            r = client.request("GET", "/eateries/1/menu")
            log(f"    result: {r.status_code}, {len(r.json()['items'])} items")
        except (CircuitOpenError, RuntimeError) as exc:
            log(f"    result: FAILED ({exc})")

    log("=== Phase 1: healthy server")
    for i in range(3):
        read_menu(f"menu read {i + 1}")
    key = str(uuid.uuid4())     # one key per logical operation, reused on every retry
    r = client.request("POST", "/holds", json={"item_id": 4, "pickup_in_minutes": 120},
                       headers={"Idempotency-Key": key})
    log(f"    hold created: id={r.json().get('id')} (Idempotency-Key {key[:8]}...)")

    log(f"=== Phase 2: inject {args.delay_ms} ms delay (read timeout is {READ_TIMEOUT}s)")
    set_delay(args.base_url, args.staff_key, args.delay_ms)
    read_menu("menu read (expect timeouts and retries)")
    read_menu("menu read (expect: blocked by open breaker)")
    read_menu("menu read (expect: still blocked)")

    log("=== Phase 3: remove fault, wait out the recovery period")
    set_delay(args.base_url, args.staff_key, 0)
    time.sleep(RECOVERY_SECONDS + 1)
    read_menu("trial call (half-open)")
    read_menu("menu read (breaker closed again)")


if __name__ == "__main__":
    main()
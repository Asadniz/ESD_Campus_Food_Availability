def test_error_envelope_shape(client):
    r = client.get("/holds/9999")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "HOLD_NOT_FOUND"
    assert err["request_id"]


def test_unknown_route_uses_same_envelope(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert "code" in r.json()["error"]


def test_rate_limit_returns_429_with_retry_after(client):
    from campus_api.ratelimit import hold_limiter
    hold_limiter.configure(max_calls=3, window_seconds=10)
    codes = [client.post("/holds", json={"item_id": 4}).status_code for _ in range(4)]
    assert 429 not in codes[:3]
    assert codes[3] == 429
    r = client.post("/holds", json={"item_id": 4})
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= 10
    assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_rate_limit_only_affects_hold_creation(client):
    from campus_api.ratelimit import hold_limiter
    hold_limiter.configure(max_calls=1, window_seconds=10)
    client.post("/holds", json={"item_id": 4})
    assert client.post("/holds", json={"item_id": 4}).status_code == 429
    assert client.get("/eateries").status_code == 200
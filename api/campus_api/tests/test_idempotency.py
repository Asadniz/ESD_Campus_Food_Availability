def _hold_count():
    from campus_api import db
    with db.session() as conn:
        return conn.execute("SELECT COUNT(*) FROM holds").fetchone()[0]


def test_create_hold_valid(client):
    r = client.post("/holds", json={"item_id": 1, "pickup_in_minutes": 120})
    assert r.status_code == 201
    body = r.json()
    assert body["item_id"] == 1
    assert body["status"] == "active"
    assert len(body["pickup_code"]) == 4


def test_create_hold_invalid_input(client):
    r = client.post("/holds", json={"item_id": 0})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"][0]["field"] == "item_id"


def test_repeated_request_same_key_creates_one_hold(client):
    headers = {"Idempotency-Key": "abc-123"}
    holds_before = _hold_count()
    portions_before = client.get("/items/1").json()["portions_left"]

    first = client.post("/holds", json={"item_id": 1}, headers=headers)
    second = client.post("/holds", json={"item_id": 1}, headers=headers)

    assert first.status_code == 201 and second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert _hold_count() == holds_before + 1
    assert client.get("/items/1").json()["portions_left"] == portions_before - 1


def test_same_key_different_body_is_rejected(client):
    headers = {"Idempotency-Key": "abc-123"}
    client.post("/holds", json={"item_id": 1}, headers=headers)
    r = client.post("/holds", json={"item_id": 2}, headers=headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_without_key_each_call_creates_a_hold(client):
    a = client.post("/holds", json={"item_id": 1}).json()["id"]
    b = client.post("/holds", json={"item_id": 1}).json()["id"]
    assert a != b  
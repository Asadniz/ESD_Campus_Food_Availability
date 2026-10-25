def test_hold_lifecycle(client):
    created = client.post("/holds", json={"item_id": 1, "pickup_in_minutes": 120})
    assert created.status_code == 201
    hold_id = created.json()["id"]
    assert created.json()["status"] == "active"

    picked = client.post(f"/holds/{hold_id}/pickup")
    assert picked.status_code == 200
    assert picked.json()["status"] == "picked_up"

    # Can't close it twice.
    assert client.post(f"/holds/{hold_id}/pickup").status_code == 409


def test_hold_sold_out(client):
    client.patch("/items/1/availability", headers={"X-Staff-Key": "test-key"},
                 json={"available": False})
    r = client.post("/holds", json={"item_id": 1})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ITEM_SOLD_OUT"


def test_hold_cancel_returns_portion(client):
    before = client.get("/items/4").json()["portions_left"]
    hold_id = client.post("/holds", json={"item_id": 4}).json()["id"]
    assert client.get("/items/4").json()["portions_left"] == before - 1
    client.post(f"/holds/{hold_id}/cancel")
    assert client.get("/items/4").json()["portions_left"] == before

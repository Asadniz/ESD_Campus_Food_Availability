def test_availability_requires_staff_key(client):
    r = client.patch("/items/1/availability", json={"available": False})
    assert r.status_code == 401


def test_availability_with_correct_key(client):
    r = client.patch("/items/1/availability", headers={"X-Staff-Key": "test-key"},
                      json={"available": False, "portions_left": 5})
    assert r.status_code == 200
    assert r.json()["available"] is False

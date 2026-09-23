def test_list_eateries(client):
    r = client.get("/eateries")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_menu_has_items(client):
    r = client.get("/eateries/1/menu")
    assert r.status_code == 200
    body = r.json()
    assert body["eatery"]["slug"] == "main-cafeteria"
    assert len(body["items"]) > 0
    assert all("available" in item for item in body["items"])


def test_menu_not_found(client):
    assert client.get("/eateries/999/menu").status_code == 404

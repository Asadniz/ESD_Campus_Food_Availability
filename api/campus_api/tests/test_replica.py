"""Assignment 3: replica identity, proxy-aware rate limiting."""
from campus_api.launcher import replica_by_forward_dns, replica_from_name


def test_replica_letter_from_compose_container_name():
    assert replica_from_name("campus-food-app-1.campus-food_default") == "A"
    assert replica_from_name("campus-food-app-3") == "C"
    assert replica_from_name("3f9a1c2b7d10") is None   # plain container id: no index


def test_replica_letter_from_forward_dns():
    table = {"campus-food-app-1": "172.18.0.2", "campus-food-app-2": "172.18.0.3", "campus-food-app-3": "172.18.0.4"}

    def resolve(name):
        if name not in table:
            raise OSError("no such name")
        return table[name]

    assert replica_by_forward_dns("172.18.0.2", "campus-food-app-", resolve) == "A"
    assert replica_by_forward_dns("172.18.0.4", "campus-food-app-", resolve) == "C"
    assert replica_by_forward_dns("10.9.9.9", "campus-food-app-", resolve) is None


def test_http_response_names_the_replica(client):
    r = client.get("/eateries")
    assert r.headers["X-Replica"]
    assert client.get("/health").headers["X-Replica"]


def test_rate_limit_keys_on_forwarded_client_not_on_the_proxy(client):
    from campus_api.ratelimit import hold_limiter
    hold_limiter.configure(max_calls=2, window_seconds=60)
    hold_limiter.reset()

    def post(ip):
        return client.post("/holds", json={"item_id": 1}, headers={"X-Forwarded-For": ip}).status_code

    assert [post("10.0.0.1"), post("10.0.0.1"), post("10.0.0.1")] == [201, 201, 429]
    assert post("10.0.0.2") == 201                       # a different client has its own budget
    # a spoofed leading entry does not help: only the last (Envoy-appended) entry counts
    assert post("1.2.3.4, 10.0.0.1") == 429

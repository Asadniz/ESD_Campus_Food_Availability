"""Tests for the gRPC CreateHold service. The server runs in-process on a free port and uses the
same temporary database as the HTTP test client, so each test can check both versions together."""
import logging

import grpc
import pytest

from campus_api.grpc_server import create_server
from campus_api.observability.logs import request_id_var
from campus_api.rpc import holds_pb2, holds_pb2_grpc


@pytest.fixture()
def stub(client):  # `client` first: it creates and seeds the temp database
    server, port = create_server("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    yield holds_pb2_grpc.HoldServiceStub(channel)
    channel.close()
    server.stop(grace=None)


def _call(stub, **fields):
    return stub.CreateHold(holds_pb2.CreateHoldRequest(**fields), timeout=5)


def _error(stub, **fields) -> grpc.RpcError:
    with pytest.raises(grpc.RpcError) as info:
        _call(stub, **fields)
    return info.value


def _meta(err) -> dict:
    return dict(err.trailing_metadata())


def test_grpc_create_hold_valid(stub):
    resp = _call(stub, item_id=1, pickup_in_minutes=120)
    assert resp.hold.item_id == 1
    assert resp.hold.status == "active"
    assert resp.hold.planned_pickup_minutes == 120
    assert len(resp.hold.pickup_code) == 4
    assert resp.replayed is False


def test_grpc_default_pickup_matches_http_default(stub):
    assert _call(stub, item_id=1).hold.planned_pickup_minutes == 180


def test_grpc_invalid_input(stub):
    err = _error(stub, item_id=0)
    assert err.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "item_id" in err.details()
    assert _meta(err)["x-error-code"] == "VALIDATION_ERROR"
    assert _error(stub, item_id=1, pickup_in_minutes=5).code() == grpc.StatusCode.INVALID_ARGUMENT


def test_grpc_item_not_found(stub):
    err = _error(stub, item_id=9999)
    assert err.code() == grpc.StatusCode.NOT_FOUND
    assert _meta(err)["x-error-code"] == "ITEM_NOT_FOUND"


def test_grpc_sold_out(stub, client):
    r = client.patch("/items/1/availability", json={"available": True, "portions_left": 0},
                     headers={"X-Staff-Key": "test-key"})
    assert r.status_code == 200
    err = _error(stub, item_id=1)
    assert err.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert _meta(err)["x-error-code"] == "ITEM_SOLD_OUT"
    # the HTTP version gives the matching answer for the same state
    http = client.post("/holds", json={"item_id": 1})
    assert http.status_code == 409 and http.json()["error"]["code"] == "ITEM_SOLD_OUT"


def test_grpc_repeated_key_creates_one_hold(stub, client):
    before = client.get("/items/1").json()["portions_left"]
    first = _call(stub, item_id=1, idempotency_key="grpc-key-1")
    second = _call(stub, item_id=1, idempotency_key="grpc-key-1")
    assert first.replayed is False and second.replayed is True
    assert second.hold == first.hold
    assert client.get("/items/1").json()["portions_left"] == before - 1


def test_grpc_same_key_different_body_is_rejected(stub):
    _call(stub, item_id=1, idempotency_key="grpc-key-2")
    err = _error(stub, item_id=2, idempotency_key="grpc-key-2")
    assert err.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert _meta(err)["x-error-code"] == "IDEMPOTENCY_KEY_REUSED"


def test_http_and_grpc_share_one_source_of_truth(stub, client):
    # A hold created through gRPC is readable through HTTP.
    created = _call(stub, item_id=3).hold
    read = client.get(f"/holds/{created.id}")
    assert read.status_code == 200
    assert read.json()["pickup_code"] == created.pickup_code

    # An idempotency key stored by HTTP is honoured by gRPC (and the other way round).
    http = client.post("/holds", json={"item_id": 4}, headers={"Idempotency-Key": "shared-key"})
    via_grpc = _call(stub, item_id=4, idempotency_key="shared-key")
    assert via_grpc.replayed is True
    assert via_grpc.hold.id == http.json()["id"]

    # Stock is one pool: portions taken by either transport count against the same item.
    before = client.get("/items/5").json()["portions_left"]
    _call(stub, item_id=5)
    client.post("/holds", json={"item_id": 5})
    assert client.get("/items/5").json()["portions_left"] == before - 2


def test_request_id_crosses_the_grpc_boundary(stub):
    seen = []

    class Capture(logging.Handler):
        def emit(self, record):
            seen.append((request_id_var.get(), getattr(record, "fields", {}).get("event")))

    handler = Capture()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    try:
        resp, call = stub.CreateHold.with_call(
            holds_pb2.CreateHoldRequest(item_id=1), timeout=5, metadata=(("x-request-id", "trace-abc-123"),))
    finally:
        logging.getLogger().removeHandler(handler)

    assert dict(call.initial_metadata())["x-request-id"] == "trace-abc-123"
    events = {event for rid, event in seen if rid == "trace-abc-123"}
    assert {"hold_created", "grpc_call_completed"} <= events


def test_grpc_generates_request_id_when_client_sends_none(stub):
    _, call = stub.CreateHold.with_call(holds_pb2.CreateHoldRequest(item_id=1), timeout=5)
    assert len(dict(call.initial_metadata())["x-request-id"]) == 16


# ---------------------------------------------------------------- metrics (Assignment 2, Part C)
import time

from prometheus_client import REGISTRY


def _sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _calls(status: str) -> float:
    return _sample("campus_grpc_requests_total", method="CreateHold", status=status)


def test_grpc_calls_are_counted_by_method_and_status(stub):
    before = {s: _calls(s) for s in ("OK", "NOT_FOUND", "INVALID_ARGUMENT")}
    count_before = _sample("campus_grpc_request_duration_seconds_count", method="CreateHold")

    _call(stub, item_id=1)
    _error(stub, item_id=9999)
    _error(stub, item_id=0)

    assert _calls("OK") == before["OK"] + 1
    assert _calls("NOT_FOUND") == before["NOT_FOUND"] + 1
    assert _calls("INVALID_ARGUMENT") == before["INVALID_ARGUMENT"] + 1
    # every call, success or failure, is also in the duration histogram
    assert _sample("campus_grpc_request_duration_seconds_count", method="CreateHold") == count_before + 3


def test_grpc_metric_labels_stay_bounded(stub):
    _call(stub, item_id=1, idempotency_key="label-check")
    methods, statuses = set(), set()
    for family in REGISTRY.collect():
        if family.name.startswith("campus_grpc_"):
            for sample in family.samples:
                methods.add(sample.labels.get("method"))
                statuses.add(sample.labels.get("status"))
    assert methods - {None} == {"CreateHold"}       # no request, user or trace IDs as labels
    assert statuses - {None} <= {c.name for c in grpc.StatusCode}


def test_grpc_in_flight_gauge_rises_during_a_call_and_returns_to_zero(stub):
    key = ("x-staff-key", "test-key")
    future = stub.CreateHold.future(
        holds_pb2.CreateHoldRequest(item_id=1), timeout=5,
        metadata=(key, ("x-fault-delay-ms", "600")),
    )
    deadline = time.time() + 3
    while _sample("campus_grpc_requests_in_progress", method="CreateHold") < 1 and time.time() < deadline:
        time.sleep(0.02)
    assert _sample("campus_grpc_requests_in_progress", method="CreateHold") == 1
    future.result()
    assert _sample("campus_grpc_requests_in_progress", method="CreateHold") == 0


def test_grpc_delay_switch_needs_the_staff_key(stub):
    started = time.perf_counter()
    stub.CreateHold(holds_pb2.CreateHoldRequest(item_id=1), timeout=5,
                    metadata=(("x-staff-key", "wrong"), ("x-fault-delay-ms", "800")))
    assert time.perf_counter() - started < 0.5      # ignored: wrong key


def test_idempotent_replays_are_counted(stub, client):
    before = _sample("campus_hold_replays_total")
    _call(stub, item_id=1, idempotency_key="replay-metric")
    _call(stub, item_id=1, idempotency_key="replay-metric")          # replay over gRPC
    client.post("/holds", json={"item_id": 1}, headers={"Idempotency-Key": "replay-metric-http"})
    client.post("/holds", json={"item_id": 1}, headers={"Idempotency-Key": "replay-metric-http"})  # over HTTP
    assert _sample("campus_hold_replays_total") == before + 2


def test_http_gauges_follow_holds_created_over_grpc(stub, client):
    def active() -> float:
        client.get("/metrics")                       # each scrape recomputes the gauges from the database
        return _sample("campus_active_holds", eatery="main-cafeteria")

    before = active()
    _call(stub, item_id=1)                           # created by the gRPC process, not the HTTP one
    assert active() == before + 1

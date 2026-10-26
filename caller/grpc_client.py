"""Command-line client for creating a hold, over gRPC (default) or over HTTP for comparison.

    python caller/grpc_client.py --item-id 1
    python caller/grpc_client.py --item-id 1 --pickup-in-minutes 120 --idempotency-key demo-1
    python caller/grpc_client.py --item-id 9999 --via http        # same operation, HTTP version

It sets a deadline, sends a request ID (so the call can be found in the logs) and prints either
the result or the error, with the status and the app's error code. Exit code is 0 on success, 1 on
an error response, 2 when the server could not be reached or the deadline passed.

Needs: pip install grpcio protobuf requests   (requests only for --via http)
"""
import argparse
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))

import grpc  # noqa: E402

from campus_api.rpc import holds_pb2, holds_pb2_grpc  # noqa: E402


def via_grpc(args, request_id: str) -> int:
    request = holds_pb2.CreateHoldRequest(item_id=args.item_id, idempotency_key=args.idempotency_key or "")
    if args.pickup_in_minutes is not None:
        request.pickup_in_minutes = args.pickup_in_minutes
    metadata = (("x-request-id", request_id),)

    started = time.perf_counter()
    with grpc.insecure_channel(args.target) as channel:
        stub = holds_pb2_grpc.HoldServiceStub(channel)
        try:
            response = stub.CreateHold(request, timeout=args.deadline, metadata=metadata)
        except grpc.RpcError as err:
            ms = (time.perf_counter() - started) * 1000
            trailing = dict(err.trailing_metadata() or ())
            code = err.code()
            print(f"status:   {code.name}" + (f" (error code {trailing['x-error-code']})" if "x-error-code" in trailing else ""))
            print(f"message:  {err.details()}")
            print(f"duration: {ms:.1f} ms")
            return 2 if code in (grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE) else 1
    ms = (time.perf_counter() - started) * 1000
    h = response.hold
    print("status:   OK")
    print(f"hold:     id={h.id} item_id={h.item_id} eatery={h.eatery} pickup_code={h.pickup_code} "
          f"status={h.status} planned_pickup_minutes={h.planned_pickup_minutes}")
    print(f"replayed: {response.replayed}")
    print(f"duration: {ms:.1f} ms")
    return 0


def via_http(args, request_id: str) -> int:
    import requests

    body = {"item_id": args.item_id}
    if args.pickup_in_minutes is not None:
        body["pickup_in_minutes"] = args.pickup_in_minutes
    headers = {"X-Request-ID": request_id}
    if args.idempotency_key:
        headers["Idempotency-Key"] = args.idempotency_key

    started = time.perf_counter()
    try:
        resp = requests.post(args.base_url + "/holds", json=body, headers=headers, timeout=args.deadline)
    except requests.RequestException as exc:
        print(f"status:   {type(exc).__name__}")
        print(f"message:  {exc}")
        return 2
    ms = (time.perf_counter() - started) * 1000
    data = resp.json()
    if resp.status_code >= 400:
        err = data.get("error", {})
        details = err.get("details")
        message = err.get("message", "") + (f" {details}" if details else "")
        print(f"status:   {resp.status_code} {resp.reason} (error code {err.get('code')})")
        print(f"message:  {message}")
        print(f"duration: {ms:.1f} ms")
        return 1
    print(f"status:   {resp.status_code} {resp.reason}")
    print(f"hold:     id={data['id']} item_id={data['item_id']} eatery={data['eatery']} "
          f"pickup_code={data['pickup_code']} status={data['status']} "
          f"planned_pickup_minutes={data['planned_pickup_minutes']}")
    print(f"replayed: {resp.headers.get('Idempotent-Replayed') == 'true'}")
    print(f"duration: {ms:.1f} ms")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--item-id", type=int, required=True)
    p.add_argument("--pickup-in-minutes", type=int, default=None, help="15-480; omit for the default (180)")
    p.add_argument("--idempotency-key", default=None)
    p.add_argument("--deadline", type=float, default=2.0, help="seconds before the call is abandoned")
    p.add_argument("--request-id", default=None, help="sent as x-request-id; generated if omitted")
    p.add_argument("--via", choices=["grpc", "http"], default="grpc")
    p.add_argument("--target", default="localhost:50051", help="gRPC address")
    p.add_argument("--base-url", default="http://localhost:8000", help="HTTP base URL (for --via http)")
    args = p.parse_args()

    request_id = args.request_id or uuid.uuid4().hex[:16]
    print(f"via:      {args.via}   request_id: {request_id}")
    sys.exit(via_grpc(args, request_id) if args.via == "grpc" else via_http(args, request_id))


if __name__ == "__main__":
    main()

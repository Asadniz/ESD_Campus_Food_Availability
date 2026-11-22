#!/usr/bin/env python3
"""Render envoy/envoy.yaml for one stage of Assignment 3 (stdlib only).

    python envoy/render.py a-only                      # Part A/B: HTTP and gRPC go to replica A only
    python envoy/render.py rr                          # Part C : equal-weight round robin over A, B, C
    python envoy/render.py weighted                    # Part D : weights A:B:C = 2:1:1 (round robin)
    python envoy/render.py least-request               # Part D : least request, equal weights
    python envoy/render.py rr --health-checks          # Part D : failure and recovery (active health checks)
    python envoy/render.py weighted --weights 3,1,1    # any weights
    python envoy/render.py rr --replicas 4             # optional: a fourth replica (D)

Then apply it:  docker compose up -d --no-deps --force-recreate envoy

Fixed on purpose for every stage (so runs are comparable): no retries (a route without retry_policy never
retries), huge circuit-breaker limits (Envoy's defaults of 1024 would act as a breaker), no outlier
detection, no timeouts shorter than the experiments need.
"""
import argparse
import pathlib

LETTERS = "ABCDEFGH"

# ---- active health check settings (reported in docs/A3_REPORT.md) -------------------------------------
HC_INTERVAL = "2s"
HC_TIMEOUT = "1s"
HC_UNHEALTHY = 2     # consecutive failures before a replica is taken out
HC_HEALTHY = 2       # consecutive successes before a replica that was out comes back
HC_PATH = "/health"
# Envoy checks a cluster that has never had traffic only every no_traffic_interval (default 60 s!). Right after
# Envoy starts, that would make the first minute of checks 30x slower than "interval", so set it equal.
HC_NO_TRAFFIC = HC_INTERVAL
DNS_REFRESH = "5s"


def cluster(name, port, hc_port, policy, endpoints, health_checks, http2, choice_count):
    eps = []
    for letter, host, weight in endpoints:
        hc = f"\n                health_check_config: {{ port_value: {hc_port} }}" if health_checks else ""
        eps.append(f"""            - load_balancing_weight: {weight}      # replica {letter}
              endpoint:
                address: {{ socket_address: {{ address: {host}, port_value: {port} }} }}{hc}""")
    lb = ""
    if policy == "LEAST_REQUEST":
        lb = f"\n    least_request_lb_config: {{ choice_count: {choice_count} }}"
    health = ""
    if health_checks:
        health = f"""
    health_checks:
      - timeout: {HC_TIMEOUT}
        interval: {HC_INTERVAL}
        no_traffic_interval: {HC_NO_TRAFFIC}
        unhealthy_interval: {HC_INTERVAL}
        unhealthy_threshold: {HC_UNHEALTHY}
        healthy_threshold: {HC_HEALTHY}
        always_log_health_check_failures: true
        http_health_check: {{ path: {HC_PATH} }}"""
    proto = ""
    if http2:
        proto = """
    typed_extension_protocol_options:
      envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
        "@type": type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions
        explicit_http_config:
          http2_protocol_options: {}"""
    return f"""  - name: {name}
    type: STRICT_DNS
    dns_lookup_family: V4_ONLY
    dns_refresh_rate: {DNS_REFRESH}
    connect_timeout: 1s
    lb_policy: {policy}{lb}
    circuit_breakers:
      thresholds:
        - {{ max_connections: 100000, max_pending_requests: 100000, max_requests: 100000, max_retries: 0 }}{health}{proto}
    load_assignment:
      cluster_name: {name}
      endpoints:
        - lb_endpoints:
{chr(10).join(eps)}
"""


def listener(name, port, prefix, cluster_name, grpc):
    match = "{ prefix: \"/\", grpc: {} }" if grpc else "{ prefix: \"/\" }"
    return f"""  - name: {name}
    address: {{ socket_address: {{ address: 0.0.0.0, port_value: {port} }} }}
    filter_chains:
      - filters:
          - name: envoy.filters.network.http_connection_manager
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
              stat_prefix: {prefix}
              codec_type: AUTO                 # {'HTTP/2: every gRPC call is routed on its own (NOT tcp_proxy)' if grpc else 'HTTP/1.1 from curl and the test client'}
              use_remote_address: true         # Envoy appends the real client address to X-Forwarded-For
              preserve_external_request_id: true   # keep the client's X-Request-ID; Envoy makes one if missing
              access_log:
                - name: envoy.access_loggers.file
                  typed_config:
                    "@type": type.googleapis.com/envoy.extensions.access_loggers.file.v3.FileAccessLog
                    path: /dev/stdout
                    log_format:
                      json_format:
                        service: envoy
                        listener: {prefix}
                        time: "%START_TIME%"
                        request_id: "%REQ(X-REQUEST-ID)%"
                        method: "%REQ(:METHOD)%"
                        path: "%REQ(:PATH)%"
                        protocol: "%PROTOCOL%"
                        response_code: "%RESPONSE_CODE%"
                        grpc_status: "%GRPC_STATUS%"
                        response_flags: "%RESPONSE_FLAGS%"
                        duration_ms: "%DURATION%"
                        upstream_cluster: "%UPSTREAM_CLUSTER%"
                        upstream_host: "%UPSTREAM_HOST%"
                        replica: "%RESP(X-REPLICA)%"
                        client: "%DOWNSTREAM_REMOTE_ADDRESS_WITHOUT_PORT%"
              http_filters:
                - name: envoy.filters.http.router
                  typed_config:
                    "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
              route_config:
                name: {prefix}_routes
                virtual_hosts:
                  - name: all
                    domains: ["*"]
                    routes:
                      - match: {match}
                        route: {{ cluster: {cluster_name}, timeout: 10s }}
"""


def render(args):
    n = args.replicas
    weights = [int(w) for w in args.weights.split(",")] if args.weights else [1] * n
    if len(weights) != n:
        raise SystemExit(f"--weights needs {n} numbers")
    policy = "ROUND_ROBIN"
    if args.stage == "weighted" and not args.weights:
        weights = [2] + [1] * (n - 1)
    if args.stage == "least-request":
        policy = "LEAST_REQUEST"
    used = [0] if args.stage == "a-only" else list(range(n))     # a-only: B and C run but are not destinations

    def endpoints(port_unused):
        return [(LETTERS[i], f"campus-food-app-{i + 1}", weights[i]) for i in used]

    http_c = cluster("app_http", 8000, 8000, policy, endpoints(8000), args.health_checks, False, args.choice_count)
    grpc_c = cluster("app_grpc", 50051, 8000, policy, endpoints(50051), args.health_checks, True, args.choice_count)
    stage = f"{args.stage} policy={policy} weights={weights if args.stage != 'a-only' else '[A only]'} health_checks={args.health_checks}"
    return f"""# GENERATED by envoy/render.py: do not edit by hand.   stage: {stage}
admin:
  address: {{ socket_address: {{ address: 0.0.0.0, port_value: 9901 }} }}   # /stats/prometheus, /clusters

static_resources:
  listeners:
{listener("http_in", 8000, "http", "app_http", False)}{listener("grpc_in", 50051, "grpc", "app_grpc", True)}
  clusters:
{http_c}{grpc_c}"""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["a-only", "rr", "weighted", "least-request"])
    p.add_argument("--weights", help="comma separated, one per replica, e.g. 2,1,1")
    p.add_argument("--replicas", type=int, default=3)
    p.add_argument("--health-checks", action="store_true")
    p.add_argument("--choice-count", type=int, default=2, help="least request: random hosts compared per pick")
    p.add_argument("--out", default=str(pathlib.Path(__file__).with_name("envoy.yaml")))
    args = p.parse_args()
    pathlib.Path(args.out).write_text(render(args))
    print(f"wrote {args.out}  ({args.stage}{' + health checks' if args.health_checks else ''})")


if __name__ == "__main__":
    main()

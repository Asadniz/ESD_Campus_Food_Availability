#!/bin/sh
# One-shot job: creates the 7 day retention policy and the index template for the app logs.
set -e
ES=http://elasticsearch:9200
H='Content-Type: application/json'

echo "creating ILM policy (delete indices 7 days after creation)"
curl -sf -X PUT "$ES/_ilm/policy/campus-food-logs" -H "$H" --data-binary @- <<'JSON'
{ "policy": { "phases": {
    "hot":    { "actions": {} },
    "delete": { "min_age": "7d", "actions": { "delete": {} } }
} } }
JSON
echo

echo "creating index template"
curl -sf -X PUT "$ES/_index_template/campus-food-logs" -H "$H" --data-binary @- <<'JSON'
{
  "index_patterns": ["campus-food-logs-*"],
  "template": {
    "settings": { "number_of_shards": 1, "number_of_replicas": 0, "index.lifecycle.name": "campus-food-logs", "index.mapping.ignore_malformed": true },
    "mappings": { "properties": {
      "message": { "type": "text" },
      "trace_id": { "type": "keyword" },
      "replica":  { "type": "keyword" },
      "envoy": { "properties": {
        "service":          { "type": "keyword" },
        "listener":         { "type": "keyword" },
        "request_id":       { "type": "keyword" },
        "method":           { "type": "keyword" },
        "path":             { "type": "keyword" },
        "protocol":         { "type": "keyword" },
        "response_code":    { "type": "integer" },
        "grpc_status":      { "type": "keyword" },
        "response_flags":   { "type": "keyword" },
        "duration_ms":      { "type": "float" },
        "upstream_cluster": { "type": "keyword" },
        "upstream_host":    { "type": "keyword" },
        "replica":          { "type": "keyword" },
        "client":           { "type": "keyword" }
      } },
      "app": { "properties": {
        "replica":    { "type": "keyword" },
        "time":       { "type": "keyword" },
        "service":    { "type": "keyword" },
        "severity":   { "type": "keyword" },
        "message":    { "type": "text" },
        "request_id": { "type": "keyword" },
        "event":      { "type": "keyword" },
        "method":     { "type": "keyword" },
        "path":       { "type": "keyword" },
        "route":      { "type": "keyword" },
        "eatery":     { "type": "keyword" },
        "reason":     { "type": "keyword" },
        "status":     { "type": "integer" },
        "duration_ms":{ "type": "float" },
        "hold_id":    { "type": "long" },
        "item_id":    { "type": "long" }
      } }
    } }
  }
}
JSON
echo
echo "elasticsearch setup done"

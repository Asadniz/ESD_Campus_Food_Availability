#!/bin/sh
# One-shot job: creates the data view and the saved searches used in the report.
KB=http://kibana:5601
H='Content-Type: application/json'
K='kbn-xsrf: true'

echo "creating data view"
curl -s -X POST "$KB/api/data_views/data_view" -H "$H" -H "$K" --data-binary @- <<'JSON'
{ "override": true,
  "data_view": { "id": "campus-food-logs", "title": "campus-food-logs-*", "name": "Campus food logs", "timeFieldName": "@timestamp" } }
JSON
echo

# saved_search <id> <title> <kql query>
saved_search() {
  curl -s -X POST "$KB/api/saved_objects/search/$1?overwrite=true" -H "$H" -H "$K" --data-binary @- <<JSON
{ "attributes": {
    "title": "$2",
    "columns": ["app.severity", "app.event", "app.request_id", "message"],
    "sort": [["@timestamp", "desc"]],
    "kibanaSavedObjectMeta": { "searchSourceJSON": "{\"query\":{\"query\":\"$3\",\"language\":\"kuery\"},\"filter\":[],\"indexRefName\":\"kibanaSavedObjectMeta.searchSourceJSON.index\"}" } },
  "references": [ { "id": "campus-food-logs", "name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern" } ] }
JSON
  echo
}

saved_search errors-and-warnings "Errors and warnings"      'app.severity : (ERROR or WARNING)'
saved_search server-errors       "5xx responses"            'app.event : request_completed and app.status >= 500'
saved_search slow-requests       "Requests slower than 400 ms" 'app.event : request_completed and app.duration_ms >= 400'
saved_search injected-faults     "Injected fault events"    'app.event : fault_injected'
saved_search sold-out-holds      "Holds rejected as sold out" 'app.event : hold_rejected and app.reason : sold_out'
echo "kibana setup done"

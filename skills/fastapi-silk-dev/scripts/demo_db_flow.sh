#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

echo "Seeding sample data..."
curl -sS -X POST "$BASE_URL/seed" | tee /tmp/silk_seed.json

echo "Running workload to generate profiler entries..."
for _ in 1 2 3; do
  curl -sS "$BASE_URL/workload" > /dev/null
  sleep 0.2
done

echo "Creating an item..."
curl -sS -X POST "$BASE_URL/items" \
  -H "Content-Type: application/json" \
  -d '{"name":"Skill Item","description":"Created by demo script"}' > /dev/null

echo "Creating another item..."
curl -sS -X POST "$BASE_URL/items" \
  -H "Content-Type: application/json" \
  -d '{"name":"Skill Item 2","description":"Created by demo script"}' > /dev/null

echo "Listing items..."
curl -sS "$BASE_URL/items" > /dev/null

echo "Done. Open: $BASE_URL/_silk/reports"

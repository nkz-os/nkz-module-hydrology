#!/bin/bash
# CI guard: ensure gl.run_tool() is only called from geolibre_engine.py
set -euo pipefail

cd "$(dirname "$0")/.."

BAD=$(grep -rn "gl\.run_tool" backend/app/ --include="*.py" | grep -v "geolibre_engine.py" || true)
if [ -n "$BAD" ]; then
    echo "❌ geolibre calls outside geolibre_engine.py:"
    echo "$BAD"
    echo ""
    echo "All gl.run_tool() calls MUST go through GeoLibreEngine."
    echo "Move the call into geolibre_engine.py or refactor."
    exit 1
fi

echo "✅ All geolibre calls are inside geolibre_engine.py"

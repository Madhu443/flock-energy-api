import json
import sys
import os

# Add root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app

openapi_schema = app.openapi()
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(openapi_schema, f, indent=2)

print(f"Exported openapi.json successfully to {out_path} ({len(json.dumps(openapi_schema))} bytes)")

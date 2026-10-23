#!/usr/bin/env bash
set -e

echo "=== Rig Digital Twin Core Initializing ==="

# Wait for database if DATABASE_URL is configured with postgresql
if [[ "$DATABASE_URL" =~ ^postgresql:// ]]; then
  echo "Checking database connectivity..."
  # Simple python one-liner check with retry
  python - <<'EOF'
import os
import sys
import time
from sqlalchemy import create_engine, text

db_url = os.environ.get("DATABASE_URL")
if not db_url:
    sys.exit(0)

max_retries = 30
for i in range(max_retries):
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
            print("Database is ready and accepting connections!")
            sys.exit(0)
    except Exception as e:
        print(f"Waiting for database ({i+1}/{max_retries})...")
        time.sleep(1)

print("Warning: Database did not become ready within timeout, proceeding with startup...")
EOF
fi

echo "Starting Rig Digital Twin application: $@"
exec "$@"

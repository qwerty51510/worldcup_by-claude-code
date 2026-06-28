#!/bin/bash
set -e

# Load environment variables from .env
export $(grep -v '^#' .env | xargs)

echo "=== Polymarket Trading Bot ==="
echo "Wallet: ${WALLET_ADDRESS:0:6}...${WALLET_ADDRESS: -4}"
echo "Bankroll: $BANKROLL"
echo ""

# Start pm_predict in background
python3 -m src.pm_predict --daemon --interval 300 &
PID_PREDICT=$!
echo "pm_predict PID=$PID_PREDICT"

# Start pm_monitor in background
python3 -m src.pm_monitor --daemon --interval 60 &
PID_MONITOR=$!
echo "pm_monitor PID=$PID_MONITOR"

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $PID_PREDICT $PID_MONITOR 2>/dev/null || true
    exit 0
}

trap cleanup INT TERM

# Run pm_trader in foreground (main loop)
python3 -m src.pm_trader --daemon --interval 300

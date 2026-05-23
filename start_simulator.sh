#!/bin/bash
# Start the SmartHome simulator on port 8080

echo "Starting SmartHome Simulator..."
echo "Simulator will be available at http://localhost:8080"
echo "Press Ctrl+C to stop"
echo ""

python3 smart_home_simulator.py --home-config homes_config.json

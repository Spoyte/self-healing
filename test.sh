#!/bin/bash
# Test suite for self-healing infrastructure system

set -e

echo "=== Self-Healing Infrastructure Test Suite ==="
echo

cd "$(dirname "$0")"

# Test 1: Help command
echo "[TEST 1] Help command..."
python3 self_healing.py help > /dev/null 2>&1 && echo "  ✓ PASS" || echo "  ✗ FAIL"

# Test 2: Status command
echo "[TEST 2] Status command..."
python3 self_healing.py status > /dev/null 2>&1 && echo "  ✓ PASS" || echo "  ✗ FAIL"

# Test 3: List checks command
echo "[TEST 3] List checks command..."
python3 self_healing.py list-checks > /dev/null 2>&1 && echo "  ✓ PASS" || echo "  ✗ FAIL"

# Test 4: Import test
echo "[TEST 4] Module import..."
python3 -c "import self_healing; print('  ✓ PASS')" 2>&1 || echo "  ✗ FAIL"

# Test 5: Check output format
echo "[TEST 5] Status JSON format..."
python3 -c "
import json
import sys
sys.path.insert(0, '.')
from self_healing import SelfHealingEngine
engine = SelfHealingEngine()
status = engine.get_status()
assert 'stats' in status
assert 'health_checks' in status
print('  ✓ PASS')
" 2>&1 || echo "  ✗ FAIL"

echo
echo "=== Test Suite Complete ==="

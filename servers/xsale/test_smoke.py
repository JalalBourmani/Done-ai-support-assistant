"""Quick smoke test for XSALE MCP server authentication and basic API calls."""

import os
import sys
import json

# Load .env manually for testing
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

import mcp_server


def test_login():
    print("=" * 60)
    print("TEST 1: Login to XSALE")
    print("=" * 60)
    try:
        sess = mcp_server._get_session()
        uid = mcp_server._user_id
        print(f"  [OK] Login successful!")
        print(f"  [OK] User ID: {uid}")
        return True
    except Exception as e:
        print(f"  [FAIL] Login failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_user():
    print("\n" + "=" * 60)
    print("TEST 2: Get logged user info")
    print("=" * 60)
    try:
        result = mcp_server._api_get("/user/get_logged_user")
        data = result.get("user") or result.get("data") or {}
        if isinstance(data, dict) and data.get("id"):
            print(f"  [OK] Name: {data.get('fullName', data.get('name'))}")
            print(f"  [OK] Email: {data.get('email')}")
            print(f"  [OK] ID: {data.get('id')}")
            print(f"  [OK] Role: {data.get('role')}")
            return True
        else:
            print(f"  [FAIL] Unexpected response structure:")
            print(f"    Keys: {list(result.keys())}")
            return False
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        return False


def test_list_cases():
    print("\n" + "=" * 60)
    print("TEST 3: List active cases (first 5)")
    print("=" * 60)
    try:
        uid = mcp_server._user_id
        if not uid:
            print("  [WARN] No user ID, trying without userId filter...")
            filters = [{"property": "status", "value": "ACTIVE"}]
        else:
            filters = [
                {"property": "userId", "value": uid},
                {"property": "status", "value": "ACTIVE"},
            ]
        
        sorts = [{"property": "updated", "direction": "DESC"}]
        params = {
            "page": 1, "start": 0, "limit": 5,
            "filter": mcp_server._build_filter(filters),
            "sort": mcp_server._build_sort(sorts),
        }
        result = mcp_server._api_get("/customercase/", params=params)
        total = result.get("total", 0)
        cases = result.get("data", [])
        print(f"  [OK] Total cases: {total}")
        print(f"  [OK] Retrieved: {len(cases)}")
        
        if cases:
            # Print the keys of the first case to understand the structure
            print(f"  [INFO] First case keys: {sorted(cases[0].keys())[:15]}...")
            
            for i, case in enumerate(cases[:5]):
                title = case.get("title", "N/A")
                status = case.get("status", "N/A")
                customer = case.get("customerName", case.get("companyName", "N/A"))
                case_id = case.get("id", "?")
                print(f"  [{i+1}] #{case_id} | {status} | {customer} | {title[:60]}")
        else:
            print("  [WARN] No cases found. Trying without userId filter...")
            params2 = {
                "page": 1, "start": 0, "limit": 5,
                "filter": mcp_server._build_filter([{"property": "status", "value": "ACTIVE"}]),
                "sort": mcp_server._build_sort(sorts),
            }
            result2 = mcp_server._api_get("/customercase/", params=params2)
            total2 = result2.get("total", 0)
            cases2 = result2.get("data", [])
            print(f"  [INFO] Without userId filter - Total: {total2}, Retrieved: {len(cases2)}")
            if cases2:
                for i, case in enumerate(cases2[:3]):
                    print(f"  [{i+1}] #{case.get('id')} | {case.get('status')} | {case.get('title', '')[:50]}")
        
        return True
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_case_types():
    print("\n" + "=" * 60)
    print("TEST 4: List case types")
    print("=" * 60)
    try:
        result = mcp_server._api_get("/account/case_type/", params={
            "page": 1, "start": 0, "limit": 999999,
            "sort": mcp_server._build_sort([{"property": "sort", "direction": "ASC"}]),
        })
        
        # Debug: show raw response keys
        print(f"  [INFO] Response keys: {list(result.keys())}")
        
        types = result.get("data", [])
        if not types:
            # Try without params
            result2 = mcp_server._api_get("/account/case_type/")
            print(f"  [INFO] No-params response keys: {list(result2.keys())}")
            types = result2.get("data", [])
        
        print(f"  [OK] Found {len(types)} case types:")
        for t in types:
            name = t.get("name", t.get("title", t.get("label", "Unknown")))
            print(f"     - {name}")
        return True
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        return False


if __name__ == "__main__":
    results = []
    results.append(("Login", test_login()))
    if results[-1][1]:
        results.append(("Get User", test_get_user()))
        results.append(("List Cases", test_list_cases()))
        results.append(("Case Types", test_case_types()))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for name, ok in results:
        icon = "[OK]" if ok else "[FAIL]"
        print(f"  {icon} {name}")
    
    failed = sum(1 for _, ok in results if not ok)
    if failed:
        print(f"\n  {failed} test(s) failed!")
        sys.exit(1)
    else:
        print(f"\n  All {len(results)} tests passed!")

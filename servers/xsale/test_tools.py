"""Test the actual MCP tool functions end-to-end."""

import os, json, sys

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# Clear any cached bytecode
if '__pycache__' in os.listdir('.'):
    import shutil
    shutil.rmtree('__pycache__', ignore_errors=True)

import mcp_server

print("=" * 60)
print("TEST: get_logged_user()")
print("=" * 60)
result = mcp_server.get_logged_user()
print(result)

print("\n" + "=" * 60)
print("TEST: list_case_types()")
print("=" * 60)
result = mcp_server.list_case_types()
parsed = json.loads(result)
print(f"Found {len(parsed)} case types")
for t in parsed:
    print(f"  - {t}")

print("\n" + "=" * 60)
print("TEST: list_my_cases()")
print("=" * 60)
result = mcp_server.list_my_cases()
parsed = json.loads(result)
print(f"Total: {parsed.get('total')}, Showing: {parsed.get('showing')}")
if parsed.get("cases"):
    for c in parsed["cases"][:5]:
        print(f"  #{c['id']} | {c['status']} | {c['subject'][:60]}")
else:
    print("  No cases returned via tool. Testing raw API...")
    raw = mcp_server._api_get("/customercase/", params={
        "page": 1, "start": 0, "limit": 3,
        "filter": json.dumps([{"property":"userId","value": mcp_server._user_id},{"property":"status","value":"ACTIVE"}]),
        "sort": json.dumps([{"property":"updated","direction":"DESC"}]),
        "group": json.dumps([{"property":"groupingStatus","direction":"ASC"}]),
    })
    print(f"  Raw response keys: {list(raw.keys())}")
    cases = raw.get("customercase", [])
    print(f"  Raw cases count: {len(cases)}")
    if cases:
        print(f"  First case subject: {cases[0].get('subject', 'N/A')}")
        print(f"  First case status: {cases[0].get('status', 'N/A')}")

print("\n" + "=" * 60)
print("TEST: list_unassigned_cases()")
print("=" * 60)
result = mcp_server.list_unassigned_cases()
parsed = json.loads(result)
print(f"Total: {parsed.get('total')}, Showing: {parsed.get('showing')}")
if parsed.get("cases"):
    for c in parsed["cases"][:3]:
        print(f"  #{c['id']} | {c['subject'][:60]}")

print("\n" + "=" * 60)
print("TEST: get_case_by_serial(43255)")
print("=" * 60)
result = mcp_server.get_case_by_serial(43255)
parsed = json.loads(result)
if "error" in parsed:
    print(f"  FAILED: {parsed['error']}")
else:
    print(f"  SUCCESS: Found case #{parsed.get('id')} with serialNumber {parsed.get('serialNumber')}!")
    print(f"  Subject: {parsed.get('subject')}")

print("\n" + "=" * 60)
print("TEST: get_case_by_serial(44112)")
print("=" * 60)
result_44112 = mcp_server.get_case_by_serial(44112)
parsed_44112 = json.loads(result_44112)
if "error" in parsed_44112:
    print(f"  FAILED: {parsed_44112['error']}")
else:
    print(f"  SUCCESS: Found case #{parsed_44112.get('id')} with serialNumber {parsed_44112.get('serialNumber')}!")
    print(f"  Subject: {parsed_44112.get('subject')}")
    print("\n  Relations:")
    relations = parsed_44112.get("relation", [])
    print(f"  Found {len(relations)} relations.")
    for r in relations:
        print(f"    - [{r.get('type')}] by {r.get('author')} on {r.get('created')}:")
        print(f"      {repr(r.get('note'))}")
    
    print("\n  Timeline:")
    timeline = parsed_44112.get("timeline", [])
    print(f"  Found {len(timeline)} timeline events.")
    for t in timeline:
        print(f"    - [{t.get('type')}] by {t.get('author')} on {t.get('timestamp')}:")
        print(f"      {repr(t.get('content'))}")



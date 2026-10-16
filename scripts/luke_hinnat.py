import json, sys, urllib.request
URL = "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/met/metryv/0100_metryv.px"
q = {"query": [
    {"code": "W", "selection": {"filter": "all", "values": ["2024*", "2025*", "2026*"]}},
    {"code": "MPKH", "selection": {"filter": "item", "values": ["6", "71", "9"]}},
    {"code": "HAKT", "selection": {"filter": "item", "values": ["0", "8021", "8023", "8022"]}},
    {"code": "PTL", "selection": {"filter": "item", "values": ["N1", "N2", "N3", "N4", "N5", "N6"]}},
], "response": {"format": "csv"}}
req = urllib.request.Request(URL, data=json.dumps(q).encode(), headers={"Content-Type": "application/json"})
r = urllib.request.urlopen(req, timeout=120)
body = r.read()
open(sys.argv[1], "wb").write(body)
print(len(body), "tavua;", body.count(b"\n"), "riviä")
print(body[:600].decode("utf-8", "replace"))

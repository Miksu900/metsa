import json, re, sys, urllib.parse, urllib.request
BASE = "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE"
out = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)
def get(path):
    url = BASE + ("/" + "/".join(urllib.parse.quote(x) for x in path) if path else "")
    return json.load(urllib.request.urlopen(url, timeout=60))
def walk(path, depth):
    try:
        items = get(path)
    except Exception as e:
        p("VIRHE", "/".join(path), e); return []
    tables = []
    for it in items:
        if it["type"] == "l" and depth > 0:
            tables += walk(path + [it["id"]], depth - 1)
        elif it["type"] == "t":
            tables.append((path + [it["id"]], it["text"]))
    return tables
p("Juuritaso:", [(i["id"], i["text"]) for i in get([])])
tables = walk(["met"], 4)
p("\nMetsätaulukoita yhteensä:", len(tables))
hit = [(pp, t) for pp, t in tables if re.search(r"kantohin|puukauppa|hinn", t + " ".join(pp), re.I)]
p("\n== Hintoihin viittaavat taulukot ==")
for pp, t in hit:
    p("/".join(pp), "|", t)
p("\n== Metatiedot ==")
for pp, t in hit[:12]:
    try:
        meta = get(pp)
        p("\n###", "/".join(pp), "|", meta.get("title"))
        for v in meta["variables"]:
            vals = list(zip(v["values"], v["valueTexts"]))
            show = vals if len(vals) <= 25 else vals[:8] + [("...", "...")] + vals[-6:]
            p(" -", v["code"], f"({len(vals)} arvoa):", show)
    except Exception as e:
        p("meta-virhe", pp, e)
open(sys.argv[1], "w").write("\n".join(out))

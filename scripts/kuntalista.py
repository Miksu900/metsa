import json, sys, urllib.request, re
def get(u):
    req = urllib.request.Request(u, headers={"Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))
out = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)
B = "https://data.stat.fi/api/classifications/v2"
try:
    L = get(f"{B}/classifications?content=data&meta=min&lang=fi")
    names = [(c.get("localId") or c.get("id"), c.get("classificationName", [{}])[0].get("name") if isinstance(c.get("classificationName"), list) else "") for c in L]
    kun = [n for n in names if n[0] and re.match(r"kunta_1_20", n[0])]
    p("kunta-luokituksia:", kun[-6:])
    mk = [n for n in names if n[0] and re.match(r"maakunta_1_20", n[0])]
    p("maakunta-luokituksia:", mk[-4:])
except Exception as e:
    p("luokituslistaus epäonnistui:", repr(e)[:200])
    L = []
open(sys.argv[1], "w").write("\n".join(out))

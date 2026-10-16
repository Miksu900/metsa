import json, re, sys, urllib.parse, urllib.request
B = "https://data.stat.fi/api/classifications/v2"
def get(u):
    req = urllib.request.Request(u, headers={"Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=90))
def nm(x):
    v = x.get("classificationItemNames") or x.get("classificationName") or []
    return v[0].get("name") if v else None
out = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)

L = get(f"{B}/classifications?content=data&meta=min&lang=fi")
ids = sorted({(c.get("localId") or c.get("id")) for c in L if (c.get("localId") or c.get("id"))})
kids = [i for i in ids if re.fullmatch(r"kunta_1_\d{8}", i)]
p("kunta-luokitukset:", kids[:3], "...", kids[-3:], len(kids))
latest = kids[-1]
p("uusin:", latest)
items = get(f"{B}/classifications/{latest}/classificationItems?content=data&meta=min&lang=fi")
kunnat = {}
for it in items:
    code = it.get("code"); name = nm(it)
    if code and name: kunnat[code] = {"nimi": name}
p("kuntia:", len(kunnat), list(kunnat.items())[:3])

# kunta -> maakunta vastaavuus
mk = latest.replace("kunta", "maakunta")
mapped = 0
for tid in (f"{latest}%23{mk}", f"{latest}#{mk}"):
    try:
        m = get(f"{B}/correspondenceTables/{tid}/maps?content=data&meta=min&lang=fi")
        for r in m:
            s = r.get("sourceItem", {}); t = r.get("targetItem", {})
            sc = s.get("code"); tc = t.get("code"); tn = nm(t) if isinstance(t, dict) else None
            if sc in kunnat:
                kunnat[sc]["maakunta"] = tc
                if tn: kunnat[sc]["maakunta_nimi"] = tn
                mapped += 1
        p("vastaavuus ok", tid, mapped)
        break
    except Exception as e:
        p("vastaavuus epäonnistui", tid, repr(e)[:150])

# vanhat kuntanumerot (yhdistyneet kunnat): nimet vanhemmista luokituksista
vanhat = {}
for k in kids:
    try:
        its = get(f"{B}/classifications/{k}/classificationItems?content=data&meta=min&lang=fi")
    except Exception as e:
        continue
    for it in its:
        c = it.get("code"); n = nm(it)
        if c and n and c not in kunnat: vanhat.setdefault(c, n)
p("vanhoja kuntanumeroita:", len(vanhat))
json.dump({"kunnat": kunnat, "vanhat": vanhat}, open(sys.argv[1], "w"), ensure_ascii=False, indent=0)
sample = [(c, kunnat[c]) for c in ("977", "846", "564", "091", "853") if c in kunnat]
p("näytteet:", sample)
open(sys.argv[2], "w").write("\n".join(out))

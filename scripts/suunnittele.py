import json, re, sys
alku, loppu = int(sys.argv[1]), int(sys.argv[2])
nimet = []
for ln in open("data/kunta-linkit.txt", encoding="utf-8"):
    m = re.fullmatch(r"MV_(.+)\.zip", ln.strip())
    if m: nimet.append(m.group(1))
nimet = sorted(set(nimet))
print(len(nimet), "kuntatiedostoa", file=sys.stderr)
print(json.dumps(nimet[alku:loppu], ensure_ascii=False))

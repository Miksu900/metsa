"""Hakee Luken viikoittaiset pystykauppahinnat ja laskee viimeisen 5 viikon keskiarvon hinta-alueittain.
Käyttö: python paivita_hinnat.py ULOS.json            (hakee PxWeb-rajapinnasta)
        python paivita_hinnat.py ULOS.json --csv F    (testaus paikallisesta CSV:stä)"""
import csv, io, json, statistics, sys, datetime, urllib.request
URL = "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/met/metryv/0100_metryv.px"
ALUEET = ["1", "3", "4", "5", "6", "71", "72", "8", "9"]
PTL = ["N1", "N2", "N3", "N4", "N5", "N6"]
N = 5

def hae():
    q = {"query": [
        {"code": "W", "selection": {"filter": "top", "values": ["12"]}},
        {"code": "MPKH", "selection": {"filter": "item", "values": ALUEET}},
        {"code": "HAKT", "selection": {"filter": "item", "values": ["0"]}},
        {"code": "PTL", "selection": {"filter": "item", "values": PTL}}],
        "response": {"format": "csv"}}
    req = urllib.request.Request(URL, data=json.dumps(q).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=120).read().decode("utf-8-sig")

def laske(teksti):
    rows = list(csv.reader(io.StringIO(teksti)))
    hdr, data = rows[0], rows[1:]
    nimi2id = {"KOKO MAA": "9", "Etelä-Suomi": "1", "Keski-Suomi": "3", "Savo-Karjala": "4", "Kymi-Savo": "5",
               "Etelä-Pohjanmaa": "6", "Pohjois-Pohjanmaa": "71", "Kainuu-Koillismaa": "72", "Lappi": "8"}
    ptl_cols = {c: PTL[i] for i, c in enumerate(hdr[4:])}
    per = {}
    for r in data:
        if r[3].lstrip(".") != "Pystykauppa": continue
        a = nimi2id.get(r[2])
        if not a: continue
        vals = {}
        for c, v in zip(hdr[4:], r[4:]):
            try: vals[ptl_cols[c]] = float(v)
            except ValueError: pass
        if len(vals) == 6:
            per.setdefault(a, {})[r[1]] = vals
    # jokaiselle alueelle omat viimeiset N viikkoa, joilta kaikki puutavaralajit ovat saatavilla
    ulos = {}
    for a, d in per.items():
        vk = sorted(d)[-N:]
        ulos[a] = {"h": {p: round(statistics.mean(d[w][p] for w in vk), 2) for p in PTL}, "v": vk}
    return ulos

if __name__ == "__main__":
    teksti = open(sys.argv[3], encoding="utf-8-sig").read() if len(sys.argv) > 3 and sys.argv[2] == "--csv" else hae()
    alueet = laske(teksti)
    json.dump({
        "paivitetty": datetime.date.today().isoformat(),
        "lahde": "Luonnonvarakeskus, Kantohinnat viikoittain (pystykauppa), CC BY 4.0",
        "alueet": alueet,
        "energia": 9.26,
        "huom": "Hinnat €/m3: N1 mäntytukki, N2 kuusitukki, N3 koivutukki, N4 mäntykuitu, N5 kuusikuitu, N6 koivukuitu. Energia- ja muun puun hinta kiinteä arvio."
    }, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
    print({a: v["v"][0] + ".." + v["v"][-1] for a, v in alueet.items()})

"""Esilaskenta: yhden kunnan kiinteistökohtaiset puumäärät.
Käyttö: python esilaske.py GPKG ULOS.json.gz
Yhdistää Metsäkeskuksen metsävarakuviot (ajantasaistettu tila, treestandclass=2)
ja Maanmittauslaitoksen palstat (PalstanSijaintitiedot)."""
import base64, gzip, json, os, sys, time, urllib.parse, urllib.request
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import Transformer
from shapely import force_2d
from shapely.geometry import shape
from shapely.ops import transform

GPKG, OUT = sys.argv[1], sys.argv[2]
BASE = "https://avoin-paikkatieto.maanmittauslaitos.fi/kiinteisto-avoin/simple-features/v3"
AUTH = "Basic " + base64.b64encode((os.environ["MML_API_KEY"] + ":").encode()).decode()
T0 = time.time()
def log(*a):
    print(f"[{time.time()-T0:6.0f}s]", *a, flush=True)

def http_json(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Authorization": AUTH, "Accept": "application/geo+json"})
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:
            log("  virhe", type(e).__name__, str(e)[:80], "yritys", i + 1)
            time.sleep(3 * (i + 1))
    raise SystemExit("MML-haku epäonnistui")

# 1. Kuviot ja tilavuudet kuvioittain (m3/ha)
stands = gpd.read_file(GPKG, layer="stand")
stands["geometry"] = stands.geometry.apply(force_2d)
log("kuvioita", len(stands))
def tbl(n): return pyogrio.read_dataframe(GPKG, layer=n, read_geometry=False)
RYHMA = {"1": "ma", "2": "ku", "3": "ko", "4": "ko", "27": "ko",
         "8": "ku", "10": "ku", "11": "ku", "12": "ma", "14": "ku", "16": "ku", "19": "ku", "22": "ma", "23": "ku", "30": "ku"}
ts_all = tbl("treestand")
st_all = tbl("treestratum")[["treestandid", "treespecies", "volume", "sawlogvolume", "pulpwoodvolume"]]
def vol_frame(luokka, etuliite=""):
    ts = ts_all[ts_all.treestandclass == luokka][["treestandid", "standid"]]
    st = st_all.merge(ts, on="treestandid")
    st["r"] = st.treespecies.astype(str).map(lambda c: RYHMA.get(c, "le"))
    st["muu"] = (st.volume - st.sawlogvolume.fillna(0) - st.pulpwoodvolume.fillna(0)).clip(lower=0)
    cols = {}
    for r in ["ma", "ku", "ko", "le"]:
        s = st[st.r == r].groupby("standid")
        cols[etuliite + r + "_t"] = s.sawlogvolume.sum(); cols[etuliite + r + "_k"] = s.pulpwoodvolume.sum()
    cols[etuliite + "muu"] = st.groupby("standid").muu.sum()
    return pd.DataFrame(cols).fillna(0.0)
vol = vol_frame("2")            # ajantasaistettu tila
# Ennuste (~10 v): luokalla 3 ei ole latvuskerroksia, vain yhteenveto -> skaalataan nykyinen puulajijakauma
_sm = tbl("treestandsummary")[["treestandid", "volume", "sawlogvolume", "pulpwoodvolume", "maintreespecies"]] \
    if "maintreespecies" in tbl("treestandsummary").columns else None
_sm0 = tbl("treestandsummary")
def _sum(luokka):
    t = ts_all[ts_all.treestandclass == luokka][["treestandid", "standid"]]
    x = _sm0.merge(t, on="treestandid")
    return x.groupby("standid")[["volume", "sawlogvolume", "pulpwoodvolume"]].sum()
_s2, _s3 = _sum("2"), _sum("3")
_ms = ts_all[ts_all.treestandclass == "3"].dropna(subset=["maintreespecies"]).drop_duplicates("standid").set_index("standid")["maintreespecies"]
vol3 = pd.DataFrame(index=vol.index.union(_s3.index))
for r in ["ma", "ku", "ko", "le"]:
    vol3["f_" + r + "_t"] = 0.0; vol3["f_" + r + "_k"] = 0.0
vol3["f_muu"] = 0.0
for sid in vol3.index:
    f = _s3.loc[sid] if sid in _s3.index else None
    if f is None: continue
    c = vol.loc[sid] if sid in vol.index else None
    c2 = _s2.loc[sid] if sid in _s2.index else None
    ft, fk = float(f.sawlogvolume or 0), float(f.pulpwoodvolume or 0)
    fm = max(float(f.volume or 0) - ft - fk, 0.0)
    ct = sum(c[r + "_t"] for r in ["ma", "ku", "ko", "le"]) if c is not None else 0.0
    ck = sum(c[r + "_k"] for r in ["ma", "ku", "ko", "le"]) if c is not None else 0.0
    ryh = RYHMA.get(str(_ms.get(sid, "")), "le")
    for r in ["ma", "ku", "ko", "le"]:
        vol3.at[sid, "f_" + r + "_t"] = ft * c[r + "_t"] / ct if ct > 0 else (ft if r == ryh else 0.0)
        vol3.at[sid, "f_" + r + "_k"] = fk * c[r + "_k"] / ck if ck > 0 else (fk if r == ryh else 0.0)
    vol3.at[sid, "f_muu"] = fm
gp = tbl("growthplacedata")[["standid", "maingroup", "fertilityclass"]]
# ikä ja kehitysluokka (ajantasaistettu tila)
ts2 = ts_all[ts_all.treestandclass == "2"][["treestandid", "standid", "developmentclass"]]
tsum = tbl("treestandsummary")[["treestandid", "age", "storey", "volume"]]
tsum = tsum[tsum.storey.astype(str) == "1"].merge(ts2, on="treestandid")
tsum = tsum.sort_values("volume", ascending=False).drop_duplicates("standid")
ika = tsum.set_index("standid")["age"]
kehit = ts2.dropna(subset=["developmentclass"]).drop_duplicates("standid").set_index("standid")["developmentclass"]
rajoitettu = set(tbl("restriction").standid)
stands = stands[["standid", "geometry"]].merge(vol, left_on="standid", right_index=True, how="left") \
    .merge(vol3, left_on="standid", right_index=True, how="left").merge(gp, on="standid", how="left")
for c in list(vol.columns) + list(vol3.columns): stands[c] = stands[c].fillna(0.0)
stands["ika"] = stands.standid.map(ika)
stands["kehit"] = stands.standid.map(kehit).astype(object).fillna("?")
stands["rajoitus"] = stands.standid.isin(rajoitettu)
stands["kasvupaikka"] = stands.fertilityclass.astype(object).fillna("?")
IKA_RAJAT = [20, 40, 60, 80, 100]
def ikaluokka(a):
    if a is None or a != a or a <= 0: return 6
    for i, r in enumerate(IKA_RAJAT):
        if a <= r: return i
    return 5
stands["ikal"] = stands.ika.map(ikaluokka)
stands = gpd.GeoDataFrame(stands, geometry="geometry", crs=3067)

# 2. Palstat MML:stä: haetaan vain ruudut, joissa on kuvioita
to84 = Transformer.from_crs(3067, 4326, always_xy=True).transform
to67 = Transformer.from_crs(4326, 3067, always_xy=True).transform
STEP = 4000
b = stands.geometry.bounds.values
ruudut = set()
for x0, y0, x1, y1 in b:
    for i in range(int(x0 // STEP), int(x1 // STEP) + 1):
        for j in range(int(y0 // STEP), int(y1 // STEP) + 1):
            ruudut.add((i, j))
log("ruutuja haettavana:", len(ruudut))
recs = {}
nreq = 0
for n, (i, j) in enumerate(sorted(ruudut)):
    lo1, la1 = to84(i * STEP, j * STEP); lo2, la2 = to84((i + 1) * STEP, (j + 1) * STEP)
    url = f"{BASE}/collections/PalstanSijaintitiedot/items?bbox={min(lo1,lo2):.6f},{min(la1,la2):.6f},{max(lo1,lo2):.6f},{max(la1,la2):.6f}&limit=5000"
    while url:
        d = http_json(url); nreq += 1
        for f in d.get("features", []):
            t = f["properties"].get("kiinteistotunnus", "")
            if t: recs[f["id"]] = (t, f["geometry"])
        url = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
    if n % 50 == 0: log(f"ruutu {n}/{len(ruudut)}, palstoja {len(recs)}, pyyntöjä {nreq}")
par = gpd.GeoDataFrame({"tunnus": [v[0] for v in recs.values()],
                        "geometry": [transform(to67, shape(v[1])) for v in recs.values()]}, crs=3067)
par = par.dissolve(by="tunnus").reset_index()
log("kiinteistöjä", len(par))

# 3. Leikkaus
ov = gpd.overlay(stands, par, how="intersection", keep_geom_type=True)
ov["ha"] = ov.geometry.area / 10000
vcols = list(vol.columns); fcols = list(vol3.columns)
for c in vcols + fcols: ov[c] = ov[c] * ov.ha
ov["ha_m1"] = np.where(ov.maingroup.astype(str) == "1", ov.ha, 0.0)
g = ov.groupby("tunnus")[vcols + fcols + ["ha", "ha_m1"]].sum()
par["ha_tot"] = par.geometry.area / 10000
g = g.join(par.set_index("tunnus").ha_tot, how="right").fillna(0.0)
ika_ha = ov.pivot_table(index="tunnus", columns="ikal", values="ha", aggfunc="sum", fill_value=0.0)
kehit_ha = ov.groupby(["tunnus", "kehit"]).ha.sum()
kasv_ha = ov.groupby(["tunnus", "kasvupaikka"]).ha.sum()
rajoitus_ha = ov[ov.rajoitus].groupby("tunnus").ha.sum()
res = {}; laaja = {}
order = ["ma_t", "ma_k", "ku_t", "ku_k", "ko_t", "ko_k", "le_t", "le_k", "muu"]
kehit_d = {}; kasv_d = {}
for (t, k), v in kehit_ha.items():
    if v >= 0.01: kehit_d.setdefault(t, {})[k] = round(v, 2)
for (t, k), v in kasv_ha.items():
    if v >= 0.01: kasv_d.setdefault(t, {})[k] = round(v, 2)
for t, r in g.iterrows():
    if r.ha <= 0: continue
    res[t] = [round(r.ha_tot, 2), round(r.ha, 2), round(r.ha_m1, 2)] + [round(r[c], 1) for c in order]
    ik = [round(float(ika_ha.loc[t].get(i, 0.0)), 2) for i in range(1, 8)] if False else [round(float(ika_ha.loc[t].get(i, 0.0)), 2) for i in range(0, 7)]
    laaja[t] = {"e": [round(r["f_" + c], 1) for c in order], "i": ik, "k": kehit_d.get(t, {}),
                "s": kasv_d.get(t, {}), "r": round(float(rajoitus_ha.get(t, 0.0)), 2)}
meta = {"kentat": ["ha_yht", "ha_kuviot", "ha_metsamaa"] + order,
        "huom": "Tilavuudet m3. Lähde: Metsäkeskus metsävarakuviot (ajantasaistettu tila) ja Maanmittauslaitos."}
json.dump({"meta": meta, "tilat": res}, gzip.open(OUT, "wt", compresslevel=9), separators=(",", ":"))
json.dump({"meta": {"ika_rajat": IKA_RAJAT, "huom": "e=ennuste (noin 10 v), i=ha ikäluokittain (<=20,<=40,<=60,<=80,<=100,>100,tuntematon), k=ha kehitysluokittain, s=ha kasvupaikoittain, r=ha rajoitettua"},
           "tilat": laaja}, gzip.open(OUT.replace(".json.gz", ".laaja.json.gz"), "wt", compresslevel=9), separators=(",", ":"))
log("valmis:", len(res), "kiinteistöä,", os.path.getsize(OUT) // 1024, "kt")

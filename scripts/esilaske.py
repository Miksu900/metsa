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
ts = tbl("treestand"); ts = ts[ts.treestandclass == "2"][["treestandid", "standid"]]
st = tbl("treestratum")[["treestandid", "treespecies", "volume", "sawlogvolume", "pulpwoodvolume"]]
st = st.merge(ts, on="treestandid")
RYHMA = {"1": "ma", "2": "ku", "3": "ko", "4": "ko", "27": "ko",
         "8": "ku", "10": "ku", "11": "ku", "12": "ma", "14": "ku", "16": "ku", "19": "ku", "22": "ma", "23": "ku", "30": "ku"}
st["r"] = st.treespecies.astype(str).map(lambda c: RYHMA.get(c, "le"))
st["muu"] = (st.volume - st.sawlogvolume.fillna(0) - st.pulpwoodvolume.fillna(0)).clip(lower=0)
cols = {}
for r in ["ma", "ku", "ko", "le"]:
    s = st[st.r == r].groupby("standid")
    cols[r + "_t"] = s.sawlogvolume.sum(); cols[r + "_k"] = s.pulpwoodvolume.sum()
cols["muu"] = st.groupby("standid").muu.sum()
vol = pd.DataFrame(cols).fillna(0.0)
gp = tbl("growthplacedata")[["standid", "maingroup"]]
stands = stands[["standid", "geometry"]].merge(vol, left_on="standid", right_index=True, how="left").merge(gp, on="standid", how="left")
for c in vol.columns: stands[c] = stands[c].fillna(0.0)
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
for c in vol.columns: ov[c] = ov[c] * ov.ha
ov["ha_m1"] = np.where(ov.maingroup.astype(str) == "1", ov.ha, 0.0)
g = ov.groupby("tunnus")[list(vol.columns) + ["ha", "ha_m1"]].sum()
par["ha_tot"] = par.geometry.area / 10000
g = g.join(par.set_index("tunnus").ha_tot, how="right").fillna(0.0)
res = {}
order = ["ma_t", "ma_k", "ku_t", "ku_k", "ko_t", "ko_k", "le_t", "le_k", "muu"]
for t, r in g.iterrows():
    if r.ha <= 0: continue
    res[t] = [round(r.ha_tot, 2), round(r.ha, 2), round(r.ha_m1, 2)] + [round(r[c], 1) for c in order]
meta = {"kentat": ["ha_yht", "ha_kuviot", "ha_metsamaa"] + order,
        "huom": "Tilavuudet m3. Lähde: Metsäkeskus metsävarakuviot (ajantasaistettu tila) ja Maanmittauslaitos."}
json.dump({"meta": meta, "tilat": res}, gzip.open(OUT, "wt", compresslevel=9), separators=(",", ":"))
log("valmis:", len(res), "kiinteistöä,", os.path.getsize(OUT) // 1024, "kt")

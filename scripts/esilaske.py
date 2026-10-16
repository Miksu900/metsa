"""Esilaskenta: yhden kunnan kiinteistökohtaiset puumäärät.
Käyttö: python esilaske.py KUNTANRO GPKG ULOS.json
Yhdistää Metsäkeskuksen metsävarakuviot (ajantasaistettu tila, treestandclass=2)
ja Maanmittauslaitoksen palstat (PalstanSijaintitiedot)."""
import base64, json, os, sys, time, urllib.parse, urllib.request
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import Transformer
from shapely import force_2d
from shapely.geometry import shape
from shapely.ops import transform

KUNTA, GPKG, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
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

# 2. Palstat MML:stä ruututettuna
cen = stands.geometry.centroid
x0, x1 = np.percentile(cen.x, [0.5, 99.5]); y0, y1 = np.percentile(cen.y, [0.5, 99.5])
m = 2500
x0, y0, x1, y1 = x0 - m, y0 - m, x1 + m, y1 + m
log("alue (3067):", round(x0), round(y0), round(x1), round(y1))
to84 = Transformer.from_crs(3067, 4326, always_xy=True).transform
to67 = Transformer.from_crs(4326, 3067, always_xy=True).transform
STEP = 4000
recs = {}
nreq = 0
x = x0
while x < x1:
    y = y0
    while y < y1:
        lo1, la1 = to84(x, y); lo2, la2 = to84(x + STEP, y + STEP)
        url = f"{BASE}/collections/PalstanSijaintitiedot/items?bbox={lo1:.6f},{la1:.6f},{lo2:.6f},{la2:.6f}&limit=5000"
        while url:
            d = http_json(url); nreq += 1
            for f in d.get("features", []):
                t = f["properties"].get("kiinteistotunnus", "")
                if t.startswith(KUNTA):
                    recs[f["id"]] = (t, f["geometry"])
            url = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
        y += STEP
    x += STEP
    log(f"palstoja tähän mennessä {len(recs)}, pyyntöjä {nreq}")
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
meta = {"kunta": KUNTA, "kentat": ["ha_yht", "ha_kuviot", "ha_metsamaa"] + order,
        "huom": "Tilavuudet m3. Lähde: Metsäkeskus metsävarakuviot (ajantasaistettu tila) ja Maanmittauslaitos."}
json.dump({"meta": meta, "tilat": res}, open(OUT, "w"), separators=(",", ":"))
log("valmis:", len(res), "kiinteistöä,", os.path.getsize(OUT) // 1024, "kt")

"""Koe: lasketaan Teuvan kiinteistön 846-403-10-54 metsän tilavuus avoimesta datasta
ja verrataan Asiakastiedon raporttiin (kokonaistilavuus 1294 m3, tukki ~284, kuitu ~808, 16,5 ha, 3 palstaa)."""
import base64, json, os, sys, urllib.request
import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import Transformer
from shapely import force_2d
from shapely.geometry import shape
from shapely.ops import transform

GPKG = sys.argv[1]
TUNNUS = sys.argv[2]            # esim. 84640300100054
OUT = sys.argv[3]
BASE = "https://avoin-paikkatieto.maanmittauslaitos.fi/kiinteisto-avoin/simple-features/v3"
KEY = os.environ["MML_API_KEY"]

out = []
def p(*a):
    s = " ".join(str(x) for x in a)
    print(s); out.append(s)

# 1. palstat MML:ltä
req = urllib.request.Request(
    f"{BASE}/collections/PalstanSijaintitiedot/items?kiinteistotunnus={TUNNUS}&limit=100",
    headers={"Authorization": "Basic " + base64.b64encode((KEY + ":").encode()).decode(),
             "Accept": "application/geo+json"})
data = json.load(urllib.request.urlopen(req, timeout=60))
feats = data.get("features", [])
p("Palstoja MML:stä:", len(feats), "numberReturned:", data.get("numberReturned"))
tr = Transformer.from_crs(4326, 3067, always_xy=True).transform
parcels = [transform(tr, shape(f["geometry"])) for f in feats]
for i, g in enumerate(parcels):
    p(f"  palsta {i+1}: {g.area/10000:.2f} ha, tunnus={feats[i]['properties'].get('kiinteistotunnus')}")
p("Palstojen yhteispinta-ala ha:", round(sum(g.area for g in parcels)/10000, 2))
union = gpd.GeoSeries(parcels, crs=3067).union_all()
minx, miny, maxx, maxy = union.bounds

# 2. kuviot
stands = gpd.read_file(GPKG, layer="stand", bbox=(minx, miny, maxx, maxy))
stands["geometry"] = stands.geometry.apply(force_2d)
stands = stands[stands.intersects(union)].copy()
stands["inter_ha"] = stands.geometry.intersection(union).area / 10000
stands["geom_ha"] = stands.geometry.area / 10000
p("Kuvioita palstoilla:", len(stands), " leikkausala ha:", round(stands.inter_ha.sum(), 2))
p("Kentän 'area' vs geometria (ensimmäiset 5):")
p(stands[["standid", "area", "geom_ha", "inter_ha"]].head(5).to_string())

ids = set(stands.standid)
def tbl(name):
    return pyogrio.read_dataframe(GPKG, layer=name, read_geometry=False)
ts = tbl("treestand"); ts = ts[ts.standid.isin(ids)]
tsum = tbl("treestandsummary"); tsum = tsum[tsum.treestandid.isin(set(ts.treestandid))]
strat = tbl("treestratum"); strat = strat[strat.treestandid.isin(set(ts.treestandid))]
gp = tbl("growthplacedata"); gp = gp[gp.standid.isin(ids)]

p("\ntreestand-rivien luokat (treestandclass):", ts.treestandclass.value_counts().to_dict())
p("treestand-lähteet:", ts.treestanddatasource.value_counts().to_dict())
p("summary storey:", tsum.storey.value_counts(dropna=False).to_dict())
p("strata storey:", strat.storey.value_counts(dropna=False).to_dict())
p("strata treespecies:", strat.treespecies.value_counts().to_dict())
p("deadtreetype summary:", tsum.deadtreetype.value_counts(dropna=False).to_dict())

# 3. tulostetaan kuviokohtaiset rivit
sm = ts.merge(tsum, on="treestandid", how="left", suffixes=("", "_s"))
p("\n--- kuviot: treestand + summary (volume, sawlog, pulp) ---")
cols = ["standid", "treestandid", "treestandclass", "treestanddatasource", "treedatadate",
        "developmentclass", "maintreespecies", "storey", "age", "volume", "sawlogvolume", "pulpwoodvolume", "volumegrowth"]
sm = sm.merge(stands[["standid", "inter_ha"]], on="standid")
p(sm[cols + ["inter_ha"]].sort_values(["standid", "treestandclass"]).to_string())

p("\n--- strata ---")
st = strat.merge(ts[["treestandid", "standid", "treestandclass"]], on="treestandid").merge(stands[["standid", "inter_ha"]], on="standid")
p(st[["standid", "treestandid", "treestandclass", "stratumnumber", "storey", "treespecies", "age", "volume", "sawlogvolume", "pulpwoodvolume", "inter_ha"]].sort_values(["standid", "treestandid", "stratumnumber"]).to_string())

# 4. kokonaistilavuudet eri tulkinnoilla (oletus: kentät m3/ha)
def total(df, col, filt=None):
    d = df if filt is None else df[filt(df)]
    return round((d[col] * d.inter_ha).sum(), 1)
p("\n=== Kokonaistilavuudet (oletus: m3/ha * leikkausala) ===")
p("Raportti (Asiakastieto): kokonais 1294, tukki ~284, kuitu ~808, metsämaata 11,5 ha")
for cls in sorted(ts.treestandclass.dropna().unique()):
    f = lambda d, c=cls: d.treestandclass == c
    p(f"strata luokka {cls}: volume={total(st,'volume',f)} saw={total(st,'sawlogvolume',f)} pulp={total(st,'pulpwoodvolume',f)}")
    p(f"summary luokka {cls}: volume={total(sm,'volume',f)} saw={total(sm,'sawlogvolume',f)} pulp={total(sm,'pulpwoodvolume',f)}")
p(f"strata kaikki: volume={total(st,'volume')}")
p(f"summary kaikki: volume={total(sm,'volume')}")

# 5. kasvupaikka
g2 = gp.merge(stands[["standid", "inter_ha"]], on="standid")
p("\n--- kasvupaikka ---")
p(g2[["standid", "maingroup", "subgroup", "fertilityclass", "soiltype", "inter_ha"]].to_string())

# 6. koodiluettelo
try:
    cm = tbl("codeschema_mapping")
    p("\ncodeschema_mapping sarakkeet:", list(cm.columns), "rivejä:", len(cm))
    txt = cm.astype(str).apply(lambda r: " ".join(r), axis=1)
    sel = cm[txt.str.contains("treespecies|treestandclass|storey|TreeSpecies|TreeStandClass|Storey", case=False)]
    p(sel.head(60).to_string())
except Exception as e:
    p("codeschema_mapping ei luettavissa:", e)

open(OUT, "w").write("\n".join(out))

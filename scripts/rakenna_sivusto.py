#!/usr/bin/env python3
"""Rakentaa Metsänarvio-sivuston hakemistoon dist/.

Käyttö: python scripts/rakenna_sivusto.py [--hinnat-csv TIEDOSTO]
Ympäristömuuttujat: SITE_URL (esim. https://metsanarvio.fi), DOMAIN (luo CNAME-tiedoston).
"""
import datetime, gzip, html, json, os, shutil, statistics, subprocess, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SITE = ROOT / "site"
SITE_URL = os.environ.get("SITE_URL", "https://miksu900.github.io/metsa").rstrip("/")
NIMI = "Metsänarvio"
TANAAN = datetime.date.today().isoformat()

AREA_NIMET = {"1": "Etelä-Suomi", "3": "Keski-Suomi", "4": "Savo-Karjala", "5": "Kymi-Savo", "6": "Etelä-Pohjanmaa",
              "71": "Pohjois-Pohjanmaa", "72": "Kainuu-Koillismaa", "8": "Lappi", "9": "Koko maa"}
# Luken hinta-alueet maakunnittain (Luke, Puukaupan alueluokitukset 2023). Poikkeus: Kuusamo, Pudasjärvi, Taivalkoski -> Kainuu-Koillismaa.
MAAKUNTA_ALUE = {"01": "1", "02": "1", "04": "1", "05": "1", "06": "1", "07": "1", "13": "3", "11": "4", "12": "4",
                 "08": "5", "09": "5", "10": "5", "14": "6", "15": "6", "16": "6", "17": "71", "18": "72", "19": "8"}
KOILLISMAA = {"Kuusamo", "Pudasjärvi", "Taivalkoski"}
KENTAT = ["ha_yht", "ha_kuviot", "ha_metsamaa", "ma_t", "ma_k", "ku_t", "ku_k", "ko_t", "ko_k", "le_t", "le_k", "muu"]
HINTA_IDX = {"ma_t": "N1", "ma_k": "N4", "ku_t": "N2", "ku_k": "N5", "ko_t": "N3", "ko_k": "N6", "le_t": "N6", "le_k": "N6"}


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "-" for c in s).strip("-")


def e(s):
    return html.escape(str(s), quote=True)


def fi(n, d=0):
    s = f"{n:,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def eur(n):
    return fi(round(n)) + " €"


# ---------------------------------------------------------------- hinnat
def hae_hinnat():
    out = DIST / "hinnat.json"
    args = [sys.executable, str(ROOT / "scripts/paivita_hinnat.py"), str(out)]
    if "--hinnat-csv" in sys.argv:
        args += ["--csv", sys.argv[sys.argv.index("--hinnat-csv") + 1]]
    subprocess.run(args, check=True)
    d = json.load(open(out))
    if "--hinnat-csv" in sys.argv:  # vain testikäyttöön: puuttuvat alueet kopioidaan koko maan hinnoista
        for a in AREA_NIMET:
            d["alueet"].setdefault(a, d["alueet"]["9"])
    d["nimet"] = AREA_NIMET
    json.dump(d, open(out, "w"), ensure_ascii=False)
    return d


# ---------------------------------------------------------------- data
def lataa_data():
    kt = json.load(open(ROOT / "data/kuntatiedot.json"))
    kunnat, vanhat = kt["kunnat"], kt["vanhat"]
    nimi2koodi = {v["nimi"]: k for k, v in kunnat.items()}
    tiedostot = {}
    for f in sorted(p for p in (ROOT / "data/raw").glob("*.json.gz") if ".laaja." not in p.name):
        nimi = f.name[:-len(".json.gz")]
        tiedostot[nimi] = json.load(gzip.open(f, "rt"))["tilat"]
    puuttuvat = [n for n in tiedostot if n not in nimi2koodi]
    if puuttuvat:
        print("HUOM: nimeä ei löydy kuntaluettelosta:", puuttuvat)
    merged = defaultdict(dict)
    laskuri = defaultdict(Counter)
    for nimi, tilat in tiedostot.items():
        for t, v in tilat.items():
            pre = t[:3]
            laskuri[pre][nimi] += 1
            m = merged[pre].get(t)
            if m is None:
                merged[pre][t] = list(v)
            else:
                m[0] = max(m[0], v[0])
                for i in range(1, len(v)):
                    m[i] = round(m[i] + v[i], 2 if i < 3 else 1)
    return kunnat, vanhat, nimi2koodi, tiedostot, merged, laskuri


def alue_kunnalle(koodi, nimi, kunnat):
    k = kunnat.get(koodi)
    if not k or "maakunta" not in k:
        return None
    if nimi in KOILLISMAA:
        return "72"
    return MAAKUNTA_ALUE.get(k["maakunta"])


def rakenna_hakemisto(kunnat, vanhat, nimi2koodi, merged, laskuri):
    hak = {}
    for pre in merged:
        paatiedosto = laskuri[pre].most_common(1)[0][0]
        if pre in kunnat:
            nimi = kunnat[pre]["nimi"]
            alue = alue_kunnalle(pre, nimi, kunnat)
            maak = kunnat[pre].get("maakunta_nimi")
        else:
            koodi = nimi2koodi.get(paatiedosto)
            nimi = (vanhat.get(pre) + f" (nyk. {paatiedosto})") if pre in vanhat and vanhat.get(pre) != paatiedosto else paatiedosto
            alue = alue_kunnalle(koodi, paatiedosto, kunnat) if koodi else None
            maak = kunnat.get(koodi, {}).get("maakunta_nimi") if koodi else None
        if alue:
            hak[pre] = {"n": nimi, "a": alue, "t": paatiedosto, "m": maak}
    return hak


# ---------------------------------------------------------------- sivupohja
def sivu(polku, otsikko, kuvaus, runko, jsonld=None, laskuri=False, robots="index,follow"):
    """polku: esim. 'kunnat/oulu/' tai '' (juuri). Palauttaa HTML:n."""
    syvyys = len([p for p in polku.split("/") if p]) - (1 if polku.endswith(".html") else 0)
    pfx = "../" * syvyys
    canon = f"{SITE_URL}/{polku}"
    ld = ""
    for obj in (jsonld or []):
        ld += '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False) + "</script>\n"
    nav = [("", "Laskuri"), ("kunnat/", "Kunnat"), ("kantohinnat/", "Kantohinnat"), ("miten-metsan-arvo-lasketaan/", "Opas")]
    navhtml = "".join(f'<a href="{pfx}{p}"{" aria-current=page" if p == polku else ""}>{n}</a>' for p, n in nav)
    skripti = f'<script>const PFX="{pfx}";</script><script src="{pfx}laskuri.js" defer></script>' if laskuri else ""
    return f"""<!doctype html>
<html lang="fi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(otsikko)}</title>
<meta name="description" content="{e(kuvaus)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{e(canon)}">
<link rel="icon" href="data:,">
<meta property="og:type" content="website">
<meta property="og:locale" content="fi_FI">
<meta property="og:site_name" content="{NIMI}">
<meta property="og:title" content="{e(otsikko)}">
<meta property="og:description" content="{e(kuvaus)}">
<meta property="og:url" content="{e(canon)}">
<link rel="stylesheet" href="{pfx}tyyli.css">
{ld}</head>
<body>
<div class="wrap">
  <header>
    <div class="logo"><a href="{pfx}">{NIMI}</a></div>
    <nav class="nav" aria-label="Päävalikko">{navhtml}</nav>
  </header>
  <main>
{runko}
  </main>
  <footer>
    <p>Lähteet: Metsäkeskus, metsävarakuviot (CC BY 4.0); Maanmittauslaitos, kiinteistörekisterikartta (CC BY 4.0); Luonnonvarakeskus, kantohinnat viikoittain (CC BY 4.0). Palvelu ei näytä omistajatietoja.</p>
    <p>Arviot ovat suuntaa antavia. Ne eivät ole virallisia arvioita, kiinteistönvälittäjän arvioita eikä pankin vakuusarvoja.</p>
    <p><a href="{pfx}kunnat/">Kaikki kunnat</a> · <a href="{pfx}kantohinnat/">Kantohinnat</a> · <a href="{pfx}miten-metsan-arvo-lasketaan/">Miten metsän arvo lasketaan</a> · <a href="{pfx}mista-loydan-kiinteistotunnuksen/">Kiinteistötunnus</a></p>
  </footer>
</div>
{skripti}
</body>
</html>
"""


LASKURI_LOMAKE = """<form id="lomake" novalidate>
    <label for="tunnus">Kiinteistötunnus</label>
    <div class="row">
      <input id="tunnus" name="tunnus" type="text" inputmode="text" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="esim. 977-406-63-1" aria-describedby="vihje">
      <button class="go" type="submit">Laske arvo</button>
    </div>
    <div class="hint" id="vihje">Tunnuksen löydät kiinteistöveropäätöksestä tai lainhuutotodistuksesta. <a href="{pfx}mista-loydan-kiinteistotunnuksen/">Näin löydät tunnuksen</a>. Kokeile esimerkkiä: <button type="button" id="esim">977-406-63-1</button></div>
  </form>
  <div id="viesti" role="status" aria-live="polite"></div>
  <div id="tulos" aria-live="polite"></div>"""


def lomake(pfx):
    return LASKURI_LOMAKE.replace("{pfx}", pfx)


# ---------------------------------------------------------------- tilastot
def kunnan_tilastot(tilat, hinnat_alue):
    """tilat: {tunnus: rivi}. Palauttaa yhteenvedon tai None."""
    ha_tot = 0.0
    vol = defaultdict(float)
    arvo = 0.0
    koot = []
    n = 0
    for v in tilat.values():
        r = dict(zip(KENTAT, v))
        ha = r["ha_metsamaa"] if r["ha_metsamaa"] > 0.5 else r["ha_kuviot"]
        if ha <= 0:
            continue
        n += 1
        ha_tot += ha
        koot.append(ha)
        for k in KENTAT[3:]:
            vol[k] += r[k]
        for k, p in HINTA_IDX.items():
            arvo += r[k] * hinnat_alue["h"][p]
    if n == 0 or ha_tot <= 0:
        return None
    arvo += vol["muu"] * HINNAT["energia"]
    kokonais = sum(vol.values())
    laji = {"Mänty": vol["ma_t"] + vol["ma_k"], "Kuusi": vol["ku_t"] + vol["ku_k"],
            "Koivu": vol["ko_t"] + vol["ko_k"], "Muu lehtipuu": vol["le_t"] + vol["le_k"], "Energia- ja muu puu": vol["muu"]}
    koot.sort()
    return {"n": n, "ha": ha_tot, "vol_ha": kokonais / ha_tot, "arvo_ha": arvo / ha_tot,
            "mediaani_ha": statistics.median(koot), "laji": {k: v / kokonais for k, v in laji.items()},
            "tukki_osuus": (vol["ma_t"] + vol["ku_t"] + vol["ko_t"] + vol["le_t"]) / kokonais}


# ---------------------------------------------------------------- sivut
def etusivu(kunta_lkm):
    faq = [
        ("Paljonko metsäni puusto on arvoltaan?",
         "Syötä kiinteistötunnus laskuriin. Laskuri yhdistää kiinteistön rajat Metsäkeskuksen metsätietoon ja arvottaa puumäärät Luonnonvarakeskuksen tuoreilla kantohinnoilla. Tulos on arvio puuston arvosta pystykauppana."),
        ("Mitä kantohinta tarkoittaa?",
         "Kantohinta on hinta, jonka metsänomistaja saa myydessään puun pystyyn eli kaatamattomana. Se ilmoitetaan euroina kuutiometriltä, ja se on erilainen tukille ja kuitupuulle sekä eri puulajeille. Luonnonvarakeskus julkaisee kantohinnat viikoittain."),
        ("Mikä ero on tukkipuulla ja kuitupuulla?",
         "Tukkipuu on järeää runkopuuta, josta sahataan sahatavaraa. Kuitupuu on ohuempaa puuta, josta tehdään esimerkiksi sellua ja paperia. Tukkipuusta maksetaan yleensä enemmän kuin kuitupuusta."),
        ("Onko puuston arvo sama kuin metsätilan hinta?",
         "Ei ole. Puuston arvo kertoo vain puiden arvon pystykauppana. Metsätilan kauppahintaan vaikuttavat myös maapohja, sijainti, kulkuyhteydet ja markkinatilanne. Siksi tuloksia ei pidä käyttää kauppahintana."),
        ("Mistä löydän kiinteistötunnuksen?",
         "Kiinteistötunnus on esimerkiksi kiinteistöveropäätöksessä, lainhuutotodistuksessa ja kauppakirjassa. Se kirjoitetaan muodossa 977-406-63-1, eli kuntanumero, kylänumero, tilanumero ja rekisterinumero."),
        ("Kuinka tarkka arvio on?",
         "Puumäärät perustuvat Metsäkeskuksen kaukokartoitukseen, joten ne voivat poiketa todellisesta etenkin hakkuiden jälkeen. Vertailimme laskentaa kahteen julkiseen kaupalliseen metsäarvioon: puulajikohtaiset tukki- ja kuitumäärät osuivat lähelle, mutta kokonaistilavuudessa oli yhdellä kiinteistöllä noin 7 prosentin ero."),
        ("Mistä tiedot ovat?",
         "Metsätiedot ovat Metsäkeskuksen avointa metsävaratietoa, kiinteistörajat Maanmittauslaitoksen avointa kiinteistörekisterikartta-aineistoa ja kantohinnat Luonnonvarakeskuksen tilastoja. Kaikki ovat CC BY 4.0 -lisenssillä."),
    ]
    jsonld = [
        {"@context": "https://schema.org", "@type": "WebSite", "name": NIMI, "url": SITE_URL + "/", "inLanguage": "fi"},
        {"@context": "https://schema.org", "@type": "WebApplication", "name": NIMI, "url": SITE_URL + "/",
         "applicationCategory": "UtilitiesApplication", "operatingSystem": "Web", "inLanguage": "fi",
         "description": "Laskee metsän puuston arvon kiinteistötunnuksella avoimesta metsätiedosta ja tuoreista kantohinnoista.",
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"}},
        {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
    ]
    runko = f"""
  <h1>Paljonko metsäsi puusto on arvoltaan?</h1>
  <p class="lead">Syötä kiinteistötunnus. Lasken puuston arvon Metsäkeskuksen metsätiedosta ja Luonnonvarakeskuksen tuoreista kantohinnoista. Palvelu kattaa {kunta_lkm} kuntaa koko Manner-Suomessa.</p>
  {lomake("")}
  <section class="prose">
    <h2>Näin arvio lasketaan</h2>
    <p>Etsin kiinteistön rajat Maanmittauslaitoksen aineistosta ja katson, mitkä Metsäkeskuksen metsäkuviot osuvat sen alueelle. Kuvioilta saadaan puumäärä puulajeittain, jaettuna tukkiin ja kuituun. Kerron määrät Luonnonvarakeskuksen viiden viikon keskimääräisillä pystykauppahinnoilla kiinteistön hinta-alueelta. <a href="miten-metsan-arvo-lasketaan/">Lue tarkempi kuvaus laskennasta</a>.</p>
    <h2>Usein kysyttyä</h2>
    {"".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in faq)}
    <h2>Selaa kuntia ja kantohintoja</h2>
    <p><a href="kunnat/">Metsän keskimääräinen arvo kunnittain</a> ja <a href="kantohinnat/">tuoreet kantohinnat hinta-alueittain</a>.</p>
  </section>"""
    return sivu("", f"{NIMI} – metsän puuston arvo kiinteistötunnuksella",
                "Laske metsäsi puuston arvo kiinteistötunnuksella. Perustuu Metsäkeskuksen metsätietoon ja Luonnonvarakeskuksen tuoreisiin kantohintoihin.",
                runko, jsonld, laskuri=True)


def kuntasivu(pre, k, st, hak, samat):
    nimi = k["n"]
    a = HINNAT["alueet"][k["a"]]
    h = a["h"]
    vk = a["v"]
    viikot = f"{int(vk[0][-2:])}–{int(vk[-1][-2:])}/{vk[0][:4]}"
    laji_rivit = "".join(f"<tr><td>{e(l)}</td><td>{fi(o * 100, 0)} %</td></tr>" for l, o in st["laji"].items() if o >= 0.005)
    otsikko = f"Metsän arvo, {nimi}: puuston keskiarvo ja kantohinnat"
    kuvaus = (f"{nimi}: metsien puuston keskimääräinen arvo noin {fi(round(st['arvo_ha'], -1))} €/ha ja tilavuus noin {fi(st['vol_ha'])} m³/ha. "
              f"Laske oman kiinteistösi arvo kiinteistötunnuksella.")
    muut = "".join(f'<li><a href="../{slug(hak[p]["n"])}/">{e(hak[p]["n"])}</a></li>' for p in samat)
    runko = f"""
  <p class="crumbs"><a href="../../">Etusivu</a> › <a href="../">Kunnat</a> › {e(nimi)}</p>
  <h1>Metsän arvo, {e(nimi)}</h1>
  <p class="lead">Laske kiinteistön puuston arvo kiinteistötunnuksella. Alla on myös kunnan {e(nimi)} metsien keskimääräisiä lukuja ja kunnan hinta-alueen kantohinnat.</p>
  <div class="laskuri-laatikko">{lomake("../../")}</div>
  <section class="prose">
    <h2>Metsät lukuina: {e(nimi)}</h2>
    <dl class="stats">
      <div><dt>Metsää omistavia kiinteistöjä aineistossa</dt><dd>{fi(st['n'])}</dd></div>
      <div><dt>Puuston tilavuus keskimäärin</dt><dd>{fi(st['vol_ha'])} m³/ha</dd></div>
      <div><dt>Puuston arvo keskimäärin</dt><dd>noin {eur(round(st['arvo_ha'], -1))}/ha</dd></div>
      <div><dt>Kiinteistön metsäala, mediaani</dt><dd>{fi(st['mediaani_ha'], 1)} ha</dd></div>
    </dl>
    <p>Luvut on laskettu Metsäkeskuksen metsävarakuvioista kaikille kunnan kiinteistöille, joilla on metsätietoa. Arvo on puuston arvo pystykauppana nykyisillä kantohinnoilla, ei metsätilan kauppahinta. Tukkipuun osuus puuston tilavuudesta on noin {fi(st['tukki_osuus'] * 100)} %.</p>
    <h3>Puulajijakauma tilavuuden mukaan</h3>
    <div class="taulu"><table><thead><tr><th>Puulaji</th><th>Osuus</th></tr></thead><tbody>{laji_rivit}</tbody></table></div>
    <h2>Kantohinnat: hinta-alue {e(AREA_NIMET[k['a']])}</h2>
    <p>Kunta kuuluu Luonnonvarakeskuksen kantohintatilastossa hinta-alueeseen <strong>{e(AREA_NIMET[k['a']])}</strong>. Viiden viikon ({viikot}) keskimääräiset pystykauppahinnat ovat:</p>
    <div class="taulu"><table><thead><tr><th>Puutavaralaji</th><th>€/m³</th></tr></thead><tbody>
      <tr><td>Mäntytukki</td><td>{fi(h['N1'], 2)}</td></tr><tr><td>Kuusitukki</td><td>{fi(h['N2'], 2)}</td></tr><tr><td>Koivutukki</td><td>{fi(h['N3'], 2)}</td></tr>
      <tr><td>Mäntykuitupuu</td><td>{fi(h['N4'], 2)}</td></tr><tr><td>Kuusikuitupuu</td><td>{fi(h['N5'], 2)}</td></tr><tr><td>Koivukuitupuu</td><td>{fi(h['N6'], 2)}</td></tr>
    </tbody></table></div>
    <p><a href="../../kantohinnat/">Kaikki hinta-alueet ja hintojen selitys</a> · <a href="../../miten-metsan-arvo-lasketaan/">Miten metsän arvo lasketaan</a></p>
    <h2>Muita kuntia, maakunta: {e(k.get('m') or '')}</h2>
    <ul class="lista">{muut}</ul>
  </section>"""
    jsonld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": NIMI, "item": SITE_URL + "/"},
        {"@type": "ListItem", "position": 2, "name": "Kunnat", "item": SITE_URL + "/kunnat/"},
        {"@type": "ListItem", "position": 3, "name": nimi, "item": f"{SITE_URL}/kunnat/{slug(nimi)}/"}]}]
    return sivu(f"kunnat/{slug(nimi)}/", otsikko, kuvaus, runko, jsonld, laskuri=True)


def kuntaluettelo(sivulista):
    ryhmat = defaultdict(list)
    for nimi, maak in sivulista:
        ryhmat[maak or "Muut"].append(nimi)
    osat = ""
    for maak in sorted(ryhmat):
        li = "".join(f'<li><a href="{slug(n)}/">{e(n)}</a></li>' for n in sorted(ryhmat[maak]))
        osat += f"<h2>{e(maak)}</h2><ul class=\"lista\">{li}</ul>"
    runko = f"""
  <p class="crumbs"><a href="../">Etusivu</a> › Kunnat</p>
  <h1>Metsän arvo kunnittain</h1>
  <p class="lead">Valitse kunta nähdäksesi metsien keskimääräisen puuston arvon, tilavuuden ja kunnan hinta-alueen kantohinnat.</p>
  <section class="prose">{osat}</section>"""
    return sivu("kunnat/", "Metsän arvo kunnittain – puuston keskiarvo ja kantohinnat",
                "Metsän puuston keskimääräinen arvo ja tilavuus kunnittain koko Manner-Suomessa sekä kunnan hinta-alueen kantohinnat.", runko)


def kantohintasivu():
    rivit = ""
    for a in ["1", "3", "4", "5", "6", "71", "72", "8", "9"]:
        if a not in HINNAT["alueet"]:
            continue
        h = HINNAT["alueet"][a]["h"]
        rivit += f"<tr><td>{e(AREA_NIMET[a])}</td>" + "".join(f"<td>{fi(h[p], 2)}</td>" for p in ["N1", "N2", "N3", "N4", "N5", "N6"]) + "</tr>"
    vk = HINNAT["alueet"]["9"]["v"]
    viikot = f"{int(vk[0][-2:])}–{int(vk[-1][-2:])}/{vk[0][:4]}"
    runko = f"""
  <p class="crumbs"><a href="../">Etusivu</a> › Kantohinnat</p>
  <h1>Kantohinnat nyt: mäntytukki, kuusitukki ja kuitupuu hinta-alueittain</h1>
  <p class="lead">Tuoreet pystykaupan keskihinnat euroina kuutiometriltä. Hinnat ovat Luonnonvarakeskuksen viikkotilastosta, ja ne on laskettu viimeisen viiden viikon ({viikot}) keskiarvona. Sivu päivittyy päivittäin.</p>
  <section class="prose">
    <div class="taulu"><table><thead><tr><th>Hinta-alue</th><th>Mäntytukki</th><th>Kuusitukki</th><th>Koivutukki</th><th>Mäntykuitu</th><th>Kuusikuitu</th><th>Koivukuitu</th></tr></thead><tbody>{rivit}</tbody></table></div>
    <p class="pieni">Hinnat €/m³, pystykauppa yhteensä (kaikki hakkuutavat). Lähde: Luonnonvarakeskus, Kantohinnat viikoittain, CC BY 4.0. Hinnat päivitetty {HINNAT['paivitetty']}.</p>
    <h2>Mikä on kantohinta?</h2>
    <p>Kantohinta on hinta, jonka metsänomistaja saa puusta, kun puu myydään pystyyn eli kaatamattomana. Ostaja hoitaa hakkuun ja kuljetuksen, ja niiden kustannukset on jo vähennetty hinnasta. Hankintakaupassa, jossa myyjä toimittaa puut tienvarteen, hinta on korkeampi, mutta se ei ole sama asia kuin kantohinta.</p>
    <h2>Tukki ja kuitu</h2>
    <p>Tukki on järeää runkopuuta, josta sahataan sahatavaraa. Kuitupuu on ohuempaa runkopuuta, josta tehdään esimerkiksi sellua ja paperia. Taulukon tukkihinnat ovat selvästi kuitupuun hintoja korkeammat. Sen vuoksi puuston arvoon vaikuttaa paljon se, kuinka suuri osa puustosta on tukkikokoista.</p>
    <h2>Mitkä maakunnat kuuluvat mihinkin hinta-alueeseen?</h2>
    <ul>
      <li><strong>Etelä-Suomi:</strong> Uusimaa, Varsinais-Suomi, Satakunta, Kanta-Häme, Pirkanmaa, Päijät-Häme</li>
      <li><strong>Keski-Suomi:</strong> Keski-Suomi</li>
      <li><strong>Savo-Karjala:</strong> Pohjois-Savo, Pohjois-Karjala</li>
      <li><strong>Kymi-Savo:</strong> Kymenlaakso, Etelä-Karjala, Etelä-Savo</li>
      <li><strong>Etelä-Pohjanmaa:</strong> Etelä-Pohjanmaa, Pohjanmaa, Keski-Pohjanmaa</li>
      <li><strong>Pohjois-Pohjanmaa:</strong> Pohjois-Pohjanmaa, paitsi Kuusamo, Pudasjärvi ja Taivalkoski</li>
      <li><strong>Kainuu-Koillismaa:</strong> Kainuu sekä Kuusamo, Pudasjärvi ja Taivalkoski</li>
      <li><strong>Lappi:</strong> Lappi</li>
    </ul>
    <p>Aluejako on Luonnonvarakeskuksen vuoden 2023 puukaupan alueluokituksesta.</p>
    <p><a href="../">Laske oman metsäsi puuston arvo kiinteistötunnuksella</a>.</p>
  </section>"""
    return sivu("kantohinnat/", "Kantohinnat nyt: mäntytukki, kuusitukki ja kuitupuu hinta-alueittain",
                "Tuoreet pystykaupan kantohinnat hinta-alueittain: mäntytukki, kuusitukki, koivutukki ja kuitupuu. Luonnonvarakeskuksen viikkotilasto.", runko)


def opassivu():
    h = HINNAT["alueet"]["9"]["h"]
    esim_m3 = 200
    esim = esim_m3 * h["N1"]
    faq = [("Miten metsän puuston arvo lasketaan?",
            "Puuston arvo saadaan kertomalla kunkin puulajin ja puutavaralajin (tukki, kuitu) kuutiometrimäärä kyseisen puutavaralajin kantohinnalla ja laskemalla tulokset yhteen."),
           ("Kuuluuko maapohja puuston arvoon?", "Ei kuulu. Maapohjan arvo on erillinen osa metsän kokonaisarvoa.")]
    jsonld = [{"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}]
    runko = f"""
  <p class="crumbs"><a href="../">Etusivu</a> › Miten metsän arvo lasketaan</p>
  <h1>Miten metsän arvo lasketaan?</h1>
  <p class="lead">Metsän arvossa on kolme osaa: puusto, maapohja ja taimikot. Tämä palvelu laskee niistä puuston arvon, joka on yleensä suurin yksittäinen osa.</p>
  <section class="prose">
    <h2>1. Puumäärä puulajeittain</h2>
    <p>Metsäkeskus arvioi metsän puuston lentolaserkeilauksen ja ilmakuvien avulla. Metsä on jaettu keskimäärin noin 1,4 hehtaarin kuvioihin, joille on arvioitu muun muassa puuston kokonaistilavuus sekä tukki- ja kuitupuun määrä puulajeittain. Kiinteistön puumäärä saadaan laskemalla yhteen ne kuviot, jotka osuvat kiinteistön rajojen sisälle. Kuvion pinta-alasta otetaan mukaan vain kiinteistöön kuuluva osa.</p>
    <h2>2. Kantohinnat</h2>
    <p>Puun arvo riippuu siitä, onko se tukkia vai kuitua, ja mitä puulajia se on. Luonnonvarakeskus julkaisee <a href="../kantohinnat/">pystykauppahinnat</a> viikoittain hinta-alueittain. Palvelu käyttää kiinteistön hinta-alueen viiden viikon keskiarvoa.</p>
    <h2>3. Kerro ja laske yhteen</h2>
    <p>Jokainen määrä kerrotaan sitä vastaavalla hinnalla. Esimerkiksi jos kiinteistöllä on {esim_m3} m³ mäntytukkia ja mäntytukin koko maan keskimääräinen kantohinta on {fi(h['N1'], 2)} €/m³, mäntytukin arvo on noin {eur(esim)}. Samalla tavalla lasketaan muut puulajit ja kuitupuu, ja summa on puuston arvo.</p>
    <h2>Mitä arvossa ei ole mukana</h2>
    <ul>
      <li><strong>Maapohja.</strong> Metsämaan arvo on erillinen osa. Se riippuu kasvupaikasta ja sijainnista.</li>
      <li><strong>Taimikot ja nuoret metsät.</strong> Niiden arvoa ei voi laskea tukki- ja kuitumääristä samalla tavalla.</li>
      <li><strong>Hakkuurajoitukset.</strong> Esimerkiksi suojelualueet voivat rajoittaa puun myyntiä.</li>
      <li><strong>Kauppahinta.</strong> Metsätilan hinta voi poiketa puuston arvosta paljon, koska siihen vaikuttavat sijainti, markkinatilanne ja muut tekijät.</li>
    </ul>
    <h2>Kuinka luotettava arvio on?</h2>
    <p>Puumäärät perustuvat kaukokartoitukseen eikä kiinteistöllä mitattuun puustoon, joten tarkkuus vaihtelee. Kun vertasimme laskentaamme kahteen julkiseen kaupalliseen metsäarvioon, puulajikohtaiset tukki- ja kuitumäärät osuivat lähelle, ja puuston arvo osui ensimmäisellä kiinteistöllä alle prosentin päähän. Toisella kiinteistöllä kokonaistilavuus oli noin 7 prosenttia suurempi kuin vertailuarvion luku. Kahden kiinteistön otos on pieni, joten tulosta ei pidä pitää tilastollisena takuuna.</p>
    <p>Jos teet kauppaa, perintö- tai lahjaveroasioita tai pankkilainaa, tarvitset asiantuntijan tekemän arvion.</p>
    <p><a href="../">Laske oman kiinteistösi puuston arvo</a>.</p>
  </section>"""
    return sivu("miten-metsan-arvo-lasketaan/", "Miten metsän arvo lasketaan? Puuston arvo, kantohinnat ja tukki ja kuitu",
                "Selkeä opas metsän puuston arvon laskemiseen: puumäärät, tukki ja kuitu, kantohinnat ja mitä arvoon ei kuulu.", runko, jsonld)


def tunnussivu():
    faq = [("Mistä löydän kiinteistötunnuksen?",
            "Kiinteistötunnus on esimerkiksi kiinteistöveropäätöksessä, lainhuutotodistuksessa ja kauppakirjassa."),
           ("Missä muodossa kiinteistötunnus kirjoitetaan?",
            "Tunnus kirjoitetaan neljänä numerona väliviivoilla: kuntanumero, kylänumero, tilanumero ja rekisterinumero, esimerkiksi 977-406-63-1.")]
    jsonld = [{"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}]
    runko = f"""
  <p class="crumbs"><a href="../">Etusivu</a> › Kiinteistötunnus</p>
  <h1>Mistä löydän kiinteistötunnuksen?</h1>
  <p class="lead">Kiinteistötunnus tunnistaa kiinteistön yksiselitteisesti. Tarvitset sen, kun haet metsän arvoa palvelusta.</p>
  <section class="prose">
    <h2>Tunnuksen muoto</h2>
    <p>Tunnus koostuu neljästä osasta, jotka erotetaan väliviivoilla: kuntanumero, kylänumero, tilanumero ja rekisterinumero. Esimerkiksi <strong>977-406-63-1</strong>. Tunnus voidaan kirjoittaa myös 14 numeron mittaisena ilman väliviivoja (97740600630001). Palvelu hyväksyy molemmat.</p>
    <h2>Mistä tunnuksen löytää</h2>
    <ul>
      <li>kiinteistöveropäätöksestä</li>
      <li>lainhuutotodistuksesta</li>
      <li>kauppakirjasta tai perukirjasta</li>
      <li>kiinteistörekisteriotteesta</li>
    </ul>
    <p>Jos asiakirjoja ei ole käsillä, kiinteistön voi etsiä myös Maanmittauslaitoksen karttapalvelusta osoitteen tai sijainnin perusteella. Tunnus näkyy siellä kiinteistön tiedoissa.</p>
    <h2>Mitä tehdä, jos tunnuksella ei löydy tietoa?</h2>
    <ul>
      <li>Tarkista, että tunnuksessa ei ole kirjoitusvirhettä.</li>
      <li>Palvelu löytää vain kiinteistöt, joilla on Metsäkeskuksen metsätietoa. Rakennetulla tontilla tai pellolla ei välttämättä ole.</li>
      <li>Ahvenanmaan kiinteistöt eivät ole mukana.</li>
    </ul>
    <p><a href="../">Siirry laskuriin</a>.</p>
  </section>"""
    return sivu("mista-loydan-kiinteistotunnuksen/", "Mistä löydän kiinteistötunnuksen? Muoto ja löytymispaikat",
                "Kiinteistötunnuksen muoto ja mistä asiakirjoista sen löytää. Tarvitset tunnuksen metsän arvon laskemiseen.", runko, jsonld)


# ---------------------------------------------------------------- pääohjelma
def kirjoita(polku, sisalto):
    p = DIST / polku
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(sisalto, encoding="utf-8")


def main():
    global HINNAT
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    HINNAT = hae_hinnat()
    kunnat, vanhat, nimi2koodi, tiedostot, merged, laskuri = lataa_data()
    hak = rakenna_hakemisto(kunnat, vanhat, nimi2koodi, merged, laskuri)
    print("tunnusetuliitteitä:", len(hak), "kiinteistöjä:", sum(len(v) for v in merged.values()))
    # data
    (DIST / "kunnat").mkdir()
    for pre, tilat in merged.items():
        if pre in hak:
            json.dump({"tilat": tilat}, open(DIST / "kunnat" / f"{pre}.json", "w"), separators=(",", ":"))
    json.dump(hak, open(DIST / "hakemisto.json", "w"), ensure_ascii=False, separators=(",", ":"))
    # staattiset
    for f in ("tyyli.css", "laskuri.js"):
        shutil.copy(SITE / f, DIST / f)
    # kuntasivut: vain nykyiset kunnat (koodi löytyy kuntaluettelosta ja on dataa)
    sivut = []
    ryhmat = defaultdict(list)
    for pre, k in hak.items():
        if pre in kunnat:
            ryhmat[k["m"]].append(pre)
    kuntasivut = []
    for pre in sorted(hak):
        k = hak[pre]
        if pre not in kunnat:
            continue
        st = kunnan_tilastot(merged[pre], HINNAT["alueet"][k["a"]])
        if not st or st["n"] < 20:
            continue
        samat = [p for p in sorted(ryhmat[k["m"]], key=lambda x: hak[x]["n"]) if p != pre][:14]
        kirjoita(f"kunnat/{slug(k['n'])}/index.html", kuntasivu(pre, k, st, hak, samat))
        kuntasivut.append((k["n"], k["m"]))
        sivut.append(f"kunnat/{slug(k['n'])}/")
    kirjoita("index.html", etusivu(len(kuntasivut)))
    kirjoita("kunnat/index.html", kuntaluettelo(kuntasivut))
    kirjoita("kantohinnat/index.html", kantohintasivu())
    kirjoita("miten-metsan-arvo-lasketaan/index.html", opassivu())
    kirjoita("mista-loydan-kiinteistotunnuksen/index.html", tunnussivu())
    kirjoita("404.html", sivu("404.html", "Sivua ei löytynyt", "Sivua ei löytynyt.", '<h1>Sivua ei löytynyt</h1><p><a href="/">Siirry etusivulle</a></p>', robots="noindex"))
    sivut = ["", "kunnat/", "kantohinnat/", "miten-metsan-arvo-lasketaan/", "mista-loydan-kiinteistotunnuksen/"] + sivut
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for s in sivut:
        sm += f"<url><loc>{SITE_URL}/{s}</loc><lastmod>{TANAAN}</lastmod></url>\n"
    sm += "</urlset>\n"
    kirjoita("sitemap.xml", sm)
    kirjoita("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")
    kirjoita("llms.txt", f"# {NIMI}\n\n> Suomalainen palvelu, joka laskee metsän puuston arvon kiinteistötunnuksella Metsäkeskuksen avoimesta metsätiedosta ja Luonnonvarakeskuksen kantohinnoista.\n\n- [Laskuri]({SITE_URL}/)\n- [Kantohinnat]({SITE_URL}/kantohinnat/)\n- [Miten metsän arvo lasketaan]({SITE_URL}/miten-metsan-arvo-lasketaan/)\n- [Metsän arvo kunnittain]({SITE_URL}/kunnat/)\n")
    if os.environ.get("DOMAIN"):
        kirjoita("CNAME", os.environ["DOMAIN"] + "\n")
    kirjoita(".nojekyll", "")
    print("sivuja:", len(sivut), "kuntasivuja:", len(kuntasivut))


if __name__ == "__main__":
    main()

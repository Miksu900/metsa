// Metsänarvio: kiinteistötunnus -> puuston arvo. Kaikki laskenta tapahtuu selaimessa.
// PFX asetetaan sivukohtaisesti (suhteellinen polku juureen).
const LAJIT = [
  {id: "ma", nimi: "Mänty",        vari: "var(--ma)", t: "N1", k: "N4"},
  {id: "ku", nimi: "Kuusi",        vari: "var(--ku)", t: "N2", k: "N5"},
  {id: "ko", nimi: "Koivu",        vari: "var(--ko)", t: "N3", k: "N6"},
  {id: "le", nimi: "Muu lehtipuu", vari: "var(--le)", t: "N6", k: "N6"}
];
const KENTAT = ["ha_yht","ha_kuviot","ha_metsamaa","ma_t","ma_k","ku_t","ku_k","ko_t","ko_k","le_t","le_k","muu"];
const $ = s => document.querySelector(s);
const fi = (n, d = 0) => n.toLocaleString("fi-FI", {minimumFractionDigits: d, maximumFractionDigits: d});
const eur = n => fi(Math.round(n)) + " €";
const cache = {};
let hinnat = null, hakemisto = null;

function normalisoi(s) {
  s = s.trim().replace(/\s+/g, "");
  if (/^\d{14}$/.test(s)) return s;
  const m = s.match(/^(\d{1,3})-(\d{1,3})-(\d{1,4})-(\d{1,4})$/);
  if (!m) return null;
  return m[1].padStart(3, "0") + m[2].padStart(3, "0") + m[3].padStart(4, "0") + m[4].padStart(4, "0");
}
const muotoile = t => `${+t.slice(0,3)}-${+t.slice(3,6)}-${+t.slice(6,10)}-${+t.slice(10,14)}`;
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function viesti(teksti, virhe) {
  $("#viesti").innerHTML = teksti ? `<div class="msg${virhe ? " err" : ""}">${teksti}</div>` : "";
}
async function lataaJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}

function laske(rivi, alue) {
  const v = Object.fromEntries(KENTAT.map((k, i) => [k, rivi[i]]));
  const h = hinnat.alueet[alue].h;
  const lajit = LAJIT.map(l => {
    const t = v[l.id + "_t"], k = v[l.id + "_k"];
    return {...l, tuk: t, kui: k, arvo: t * h[l.t] + k * h[l.k]};
  });
  const muuArvo = v.muu * hinnat.energia;
  const arvo = lajit.reduce((a, l) => a + l.arvo, 0) + muuArvo;
  const tukki = lajit.reduce((a, l) => a + l.tuk, 0);
  const kuitu = lajit.reduce((a, l) => a + l.kui, 0);
  return {v, lajit, muuArvo, arvo, tukki, kuitu, tilavuus: tukki + kuitu + v.muu};
}

function nayta(tunnus, k, rivi) {
  const a = hinnat.alueet[k.a];
  const r = laske(rivi, k.a);
  const ala = r.v.ha_metsamaa > 0.5 ? r.v.ha_metsamaa : r.v.ha_kuviot;
  const wk = s => +s.slice(-2);
  const jakso = `viikot ${wk(a.v[0])}–${wk(a.v[a.v.length-1])}/${a.v[0].slice(0,4)}`;
  const osat = [...r.lajit.map(l => ({nimi: l.nimi, vari: l.vari, arvo: l.arvo})), {nimi: "Energia- ja muu puu", vari: "var(--muu)", arvo: r.muuArvo}];
  const palkki = osat.filter(o => o.arvo > 0).map(o => `<span style="width:${(100 * o.arvo / r.arvo).toFixed(2)}%;background:${o.vari}" title="${o.nimi} ${eur(o.arvo)}"></span>`).join("");
  const rivit = osat.map((o, i) => {
    const l = r.lajit[i];
    const nimi = l ? o.nimi : `${o.nimi} (${fi(r.v.muu)} m³)`;
    return `<tr><td><i class="dot" style="background:${o.vari}"></i>${nimi}</td>
      <td>${l ? fi(l.tuk) : "–"}</td><td>${l ? fi(l.kui) : "–"}</td><td>${eur(o.arvo)}</td></tr>`;
  }).join("");
  $("#tulos").innerHTML = `
  <div class="card">
    <p class="kicker">Kiinteistö ${muotoile(tunnus)}, ${esc(k.n)}</p>
    <div class="big">noin ${eur(Math.round(r.arvo / 100) * 100)}</div>
    <p class="sub">Puuston arvo kantohinnoilla, hinta-alue ${esc(hinnat.nimet[k.a])}, ${jakso}</p>
    <dl class="facts">
      <div><dt>Kiinteistön ala</dt><dd>${fi(r.v.ha_yht, 1)} ha</dd></div>
      <div><dt>Metsämaata</dt><dd>${fi(ala, 1)} ha</dd></div>
      <div><dt>Puuston tilavuus</dt><dd>${fi(r.tilavuus)} m³</dd></div>
      <div><dt>Tilavuus hehtaarilla</dt><dd>${ala > 0 ? fi(r.tilavuus / ala) : "–"} m³</dd></div>
    </dl>
    <h2>Mistä arvo muodostuu</h2>
    <div class="bar" role="img" aria-label="Arvon jakautuminen puulajeittain">${palkki}</div>
    <table>
      <thead><tr><th>Puulaji</th><th>Tukki m³</th><th>Kuitu m³</th><th>Arvo</th></tr></thead>
      <tbody>${rivit}</tbody>
      <tfoot><tr><td>Yhteensä</td><td>${fi(r.tukki)}</td><td>${fi(r.kuitu)}</td><td>${eur(r.arvo)}</td></tr></tfoot>
    </table>
    <h2>Mitä luku tarkoittaa</h2>
    <ul class="notes">
      <li>Luku on puuston arvo, jos puut myytäisiin pystykauppana nyt. Se ei ole kiinteistön myyntihinta.</li>
      <li>Maapohjan arvoa ei ole mukana. Metsätilan kauppahinta on yleensä eri luku.</li>
      <li>Puumäärät perustuvat kaukokartoitukseen, ja ne voivat poiketa todellisesta. Hakkuut ja kuviorajat päivittyvät viiveellä.</li>
      <li>Hintoina on Luonnonvarakeskuksen pystykauppahintojen viiden viikon keskiarvo. Energiapuun hinta on kiinteä arvio (${fi(hinnat.energia, 2)} €/m³).</li>
    </ul>
  </div>`;
}

async function hae(syote) {
  viesti(""); $("#tulos").innerHTML = "";
  const tunnus = normalisoi(syote);
  if (!tunnus) { viesti("Kiinteistötunnus ei näytä oikealta. Kirjoita se muodossa 977-406-63-1.", true); return; }
  viesti("Haetaan…");
  try {
    hinnat = hinnat || await lataaJson(PFX + "hinnat.json");
    hakemisto = hakemisto || await lataaJson(PFX + "hakemisto.json");
  } catch (e) { viesti("Tietojen lataus epäonnistui. Yritä hetken päästä uudelleen.", true); return; }
  const pre = tunnus.slice(0, 3);
  const k = hakemisto[pre];
  if (!k) { viesti("Tämän kuntanumeron (" + pre + ") kiinteistöille ei ole metsätietoa. Ahvenanmaa ei ole mukana.", true); return; }
  try { cache[pre] = cache[pre] || await lataaJson(`${PFX}kunnat/${pre}.json`); }
  catch (e) { viesti("Tietojen lataus epäonnistui. Yritä hetken päästä uudelleen.", true); return; }
  const rivi = cache[pre].tilat[tunnus];
  if (!rivi) { viesti("Tälle tunnukselle ei löytynyt metsätietoa. Tunnus voi olla väärin, tai kiinteistössä ei ole metsää.", true); return; }
  viesti("");
  nayta(tunnus, k, rivi);
  try { history.replaceState(null, "", "#" + muotoile(tunnus)); } catch (e) {}
}

if ($("#lomake")) {
  $("#lomake").addEventListener("submit", e => { e.preventDefault(); hae($("#tunnus").value); });
  const es = $("#esim");
  if (es) es.addEventListener("click", () => { $("#tunnus").value = es.textContent; hae($("#tunnus").value); });
  if (location.hash.length > 3) { $("#tunnus").value = decodeURIComponent(location.hash.slice(1)); hae($("#tunnus").value); }
}

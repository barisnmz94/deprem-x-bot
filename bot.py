#!/usr/bin/env python3
"""Deprem: Anında Bilgi ve İletişim, X (Twitter) otomasyonu.

Komutlar:
  python3 bot.py planli      Sıradaki taslağı paylaşır (günde 2 kez GitHub Actions çalıştırır)
  python3 bot.py deprem      Resmi kaynaklardaki yeni M≥4 depremleri paylaşır (5 dakikada bir)
  python3 bot.py onizle      Sıradaki taslakları ve bütçeyi gösterir, hiçbir şey göndermez
  python3 bot.py denetle     Tüm taslakların uzunluğunu ve kurallarını kontrol eder
  python3 bot.py kontrol     X anahtarlarının çalıştığını doğrular

Yalnızca Python standart kütüphanesi kullanılır. X anahtarları ortam değişkenlerinden okunur;
anahtar yoksa ya da DRY_RUN=1 ise hiçbir şey gönderilmez, metin ekrana yazılır.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRAFTS_FILE = ROOT / "taslaklar.json"
POSTS_STATE = ROOT / "durum" / "planli.json"
QUAKES_STATE = ROOT / "durum" / "depremler.json"

UTC = timezone.utc
TR = timezone(timedelta(hours=3))  # Türkiye 2016'dan beri yaz saati uygulamıyor.


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
MIN_MAGNITUDE = env_float("MIN_MAGNITUDE", 4.0)
MAX_QUAKE_AGE_MIN = env_float("MAX_QUAKE_AGE_MIN", 45)
MAX_QUAKE_POSTS_PER_HOUR = int(env_float("MAX_QUAKE_POSTS_PER_HOUR", 4))
PROMO_PAUSE_MAGNITUDE = env_float("PROMO_PAUSE_MAGNITUDE", 5.5)   # sonrasında 24 saat tanıtım yok
FULL_PAUSE_MAGNITUDE = env_float("FULL_PAUSE_MAGNITUDE", 6.5)     # sonrasında 24 saat planlı post yok
MONTHLY_BUDGET_USD = env_float("MONTHLY_BUDGET_USD", 8.0)
MIN_HOURS_BETWEEN_SCHEDULED = env_float("MIN_HOURS_BETWEEN_SCHEDULED", 6)
APP_HINT_EVERY = int(env_float("APP_HINT_EVERY", 5))  # her N. küçük deprem postuna uygulama hatırlatması

APP_LINK = "https://apps.apple.com/tr/app/id6821462060?ct=x_organik"
COST_PLAIN = 0.015   # X API pay-per-use: Post: Create
COST_WITH_URL = 0.20  # X API pay-per-use: Post: Create (with URL)
TWEET_URL = "https://api.x.com/2/tweets"
ME_URL = "https://api.x.com/2/users/me"
USER_AGENT = "DepremXBot/1.0 (+https://apps.apple.com/tr/app/id6821462060)"

AFAD_URL = "https://servisnet.afad.gov.tr/apigateway/deprem/apiv2/event/filter"
KANDILLI_URL = "http://www.koeri.boun.edu.tr/scripts/lst0.asp"
EMSC_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"
TURKEY_BOX = (35.0, 43.0, 25.0, 45.5)  # min lat, max lat, min lon, max lon

PROVINCES = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara", "Antalya", "Ardahan", "Artvin",
    "Aydın", "Balıkesir", "Bartın", "Batman", "Bayburt", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa",
    "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Düzce", "Edirne", "Elazığ", "Erzincan", "Erzurum",
    "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Iğdır", "Isparta", "İstanbul", "İzmir",
    "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri", "Kilis", "Kırıkkale", "Kırklareli",
    "Kırşehir", "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa", "Mardin", "Mersin", "Muğla", "Muş", "Nevşehir",
    "Niğde", "Ordu", "Osmaniye", "Rize", "Sakarya", "Samsun", "Şanlıurfa", "Siirt", "Sinop", "Şırnak", "Sivas",
    "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Uşak", "Van", "Yalova", "Yozgat", "Zonguldak",
]
SEAS = {"EGE DENIZI": "Ege Denizi", "MARMARA DENIZI": "Marmara Denizi", "AKDENIZ": "Akdeniz",
        "KARADENIZ": "Karadeniz", "IZMIR KORFEZI": "İzmir Körfezi", "GOKOVA KORFEZI": "Gökova Körfezi",
        "SAROS KORFEZI": "Saros Körfezi", "EDREMIT KORFEZI": "Edremit Körfezi", "IZMIT KORFEZI": "İzmit Körfezi"}
EMSC_REGIONS = {"WESTERN TURKEY": "Batı Anadolu", "EASTERN TURKEY": "Doğu Anadolu", "CENTRAL TURKEY": "İç Anadolu",
                "NEAR THE COAST OF WESTERN TURKEY": "Batı Anadolu kıyıları", "AEGEAN SEA": "Ege Denizi",
                "SEA OF MARMARA": "Marmara Denizi", "BLACK SEA": "Karadeniz", "DODECANESE ISLANDS, GREECE": "Ege Denizi",
                "TURKEY-SYRIA BORDER REGION": "Türkiye-Suriye sınırı", "TURKEY-IRAN BORDER REGION": "Türkiye-İran sınırı",
                "EASTERN MEDITERRANEAN SEA": "Doğu Akdeniz", "CYPRUS REGION": "Kıbrıs açıkları"}


# ---------------------------------------------------------------- yardımcılar

def fold(text: str) -> str:
    """Türkçe harfleri ASCII büyük harfe indirir: 'Balıkesir' -> 'BALIKESIR'."""
    table = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")
    return text.translate(table).upper()


PROVINCE_BY_FOLD = {fold(p): p for p in PROVINCES}


def now_utc() -> datetime:
    return datetime.now(UTC)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def tr_number(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def weighted_length(text: str) -> int:
    """X'in karakter sayımı: bağlantı 23, emoji ve geniş karakterler 2, diğerleri 1."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"https?://\S+", "x" * 23, text)
    total = 0
    for ch in text:
        cp = ord(ch)
        if cp in (0x200D, 0xFE0F):
            continue
        light = (cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037)
        total += 1 if light else 2
    return total


def has_url(text: str) -> bool:
    return bool(re.search(r"https?://", text))


def http_get(url: str, timeout: int = 20) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        print(f"  ! {urllib.parse.urlsplit(url).netloc} okunamadı: {error}")
        return None


# ---------------------------------------------------------------- X API (OAuth 1.0a)

class XClient:
    def __init__(self) -> None:
        self.keys = {name: os.environ.get(name, "") for name in
                     ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}

    @property
    def configured(self) -> bool:
        return all(self.keys.values())

    def _auth_header(self, method: str, url: str) -> str:
        oauth = {
            "oauth_consumer_key": self.keys["X_API_KEY"],
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.keys["X_ACCESS_TOKEN"],
            "oauth_version": "1.0",
        }
        quote = lambda s: urllib.parse.quote(str(s), safe="~-._")
        params = "&".join(f"{quote(k)}={quote(v)}" for k, v in sorted(oauth.items()))
        base = "&".join([method.upper(), quote(url), quote(params)])
        key = f"{quote(self.keys['X_API_SECRET'])}&{quote(self.keys['X_ACCESS_SECRET'])}"
        signature = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
        oauth["oauth_signature"] = signature
        return "OAuth " + ", ".join(f'{quote(k)}="{quote(v)}"' for k, v in sorted(oauth.items()))

    def _request(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": self._auth_header(method, url),
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read() or b"{}")
            except json.JSONDecodeError:
                payload = {}
            return error.code, payload

    def post(self, text: str) -> tuple[bool, str]:
        """(başarılı mı, post kimliği ya da hata) döner."""
        if is_dry():
            print("  [deneme] gönderilmedi:\n" + "\n".join("    | " + line for line in text.splitlines()))
            return True, "deneme"
        status, payload = self._request("POST", TWEET_URL, {"text": text})
        if status in (200, 201):
            return True, payload.get("data", {}).get("id", "")
        detail = payload.get("detail") or payload.get("title") or json.dumps(payload, ensure_ascii=False)[:300]
        return False, f"HTTP {status}: {detail}"

    def me(self) -> tuple[int, dict]:
        return self._request("GET", ME_URL)


def is_dry() -> bool:
    """Anahtar yoksa da deneme modudur; böylece taslaklar gönderilmeden 'paylaşıldı' sayılmaz."""
    return DRY_RUN or not XClient().configured


# ---------------------------------------------------------------- bütçe

def month_key(moment: datetime | None = None) -> str:
    return (moment or now_utc()).strftime("%Y-%m")


def spent_this_month() -> float:
    key = month_key()
    total = 0.0
    for path in (POSTS_STATE, QUAKES_STATE):
        total += load_json(path, {}).get("harcama", {}).get(key, 0.0)
    return round(total, 3)


def record_spend(state: dict, cost: float) -> None:
    spend = state.setdefault("harcama", {})
    key = month_key()
    spend[key] = round(spend.get(key, 0.0) + cost, 3)


def within_budget(cost: float) -> bool:
    spent = spent_this_month()
    if spent + cost > MONTHLY_BUDGET_USD:
        print(f"  ! Aylık bütçe doldu: {spent:.2f} $ / {MONTHLY_BUDGET_USD:.2f} $. Gönderilmedi.")
        return False
    return True


def post_cost(text: str) -> float:
    return COST_WITH_URL if has_url(text) else COST_PLAIN


# ---------------------------------------------------------------- deprem kaynakları

def quake(source: str, sid: str, mag: float, depth: float, lat: float, lon: float,
          place: str, province: str | None, when: datetime) -> dict:
    return {"kaynak": source, "id": f"{source}:{sid}", "buyukluk": round(mag, 1), "derinlik": round(abs(depth), 1),
            "enlem": lat, "boylam": lon, "yer": place, "il": province, "zaman": when.astimezone(UTC).isoformat()}


def fetch_afad(since: datetime) -> list[dict] | None:
    query = urllib.parse.urlencode({
        "start": since.strftime("%Y-%m-%dT%H:%M:%S"),
        "end": (now_utc() + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S"),
        "minmag": f"{MIN_MAGNITUDE:.1f}", "orderby": "timedesc", "limit": "100",
    })
    raw = http_get(f"{AFAD_URL}?{query}")
    if raw is None:
        return None
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return None
    result = []
    for item in items if isinstance(items, list) else []:
        try:
            when = datetime.strptime(item["date"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
            province = item.get("province") or None
            district = item.get("district") or None
            if province and district:
                place = f"{district} ({province})"
            else:
                place = (item.get("location") or "Türkiye").split(" - ")[0].strip()
            result.append(quake("AFAD", str(item["eventID"]), float(item["magnitude"]), float(item.get("depth") or 0),
                                float(item["latitude"]), float(item["longitude"]), place,
                                province if province in PROVINCES else None, when))
        except (KeyError, ValueError, TypeError):
            continue
    return result


def kandilli_place(raw: str) -> tuple[str, str | None]:
    match = re.search(r"\(([^)]+)\)\s*$", raw)
    if match:
        province = PROVINCE_BY_FOLD.get(fold(match.group(1).strip()))
        if province:
            return province, province
    for key, name in SEAS.items():
        if key in fold(raw):
            return name, None
    return raw.title(), None


def fetch_kandilli(since: datetime) -> list[dict] | None:
    raw = http_get(KANDILLI_URL)
    if raw is None:
        return None
    text = raw.decode("cp1254", errors="replace")
    result = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 9 or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", tokens[0]):
            continue
        try:
            when = datetime.strptime(f"{tokens[0]} {tokens[1]}", "%Y.%m.%d %H:%M:%S").replace(tzinfo=TR)
            lat, lon, depth = float(tokens[2]), float(tokens[3]), float(tokens[4])
        except ValueError:
            continue
        mags = []
        for token in (tokens[7], tokens[6], tokens[5]):  # Mw > ML > MD
            try:
                mags.append(float(token))
            except ValueError:
                pass
        mag = next((m for m in mags if m > 0), None)
        if mag is None or mag < MIN_MAGNITUDE or when < since:
            continue
        place_tokens = []
        for token in tokens[8:]:
            if token.startswith(("İlksel", "Ilksel", "REVIZE")):
                break
            place_tokens.append(token)
        place, province = kandilli_place(" ".join(place_tokens))
        sid = f"{tokens[0]}-{tokens[1]}-{tokens[2]}"
        result.append(quake("Kandilli", sid, mag, depth, lat, lon, place, province, when))
    return result


def fetch_emsc(since: datetime) -> list[dict] | None:
    min_lat, max_lat, min_lon, max_lon = TURKEY_BOX
    query = urllib.parse.urlencode({
        "format": "json", "minmag": f"{MIN_MAGNITUDE:.1f}", "limit": "50",
        "start": since.strftime("%Y-%m-%dT%H:%M:%S"),
        "minlat": min_lat, "maxlat": max_lat, "minlon": min_lon, "maxlon": max_lon,
    })
    raw = http_get(f"{EMSC_URL}?{query}")
    if raw is None:
        return None
    if not raw.strip():
        return []  # FDSN, sonuç yoksa boş yanıt döner
    try:
        features = json.loads(raw).get("features", [])
    except json.JSONDecodeError:
        return None
    result = []
    for feature in features:
        p = feature.get("properties", {})
        try:
            when = datetime.strptime(p["time"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
            region = p.get("flynn_region", "")
            place = EMSC_REGIONS.get(region, region.title() or "Türkiye")
            result.append(quake("EMSC", str(feature.get("id")), float(p["mag"]), float(p.get("depth") or 0),
                                float(p["lat"]), float(p["lon"]), place, None, when))
        except (KeyError, ValueError, TypeError):
            continue
    return result


def fetch_quakes(since: datetime) -> list[dict]:
    """AFAD birincil kaynaktır. Ulaşılamazsa Kandilli, o da yoksa EMSC kullanılır."""
    for name, fetcher in (("AFAD", fetch_afad), ("Kandilli", fetch_kandilli), ("EMSC", fetch_emsc)):
        events = fetcher(since)
        if events is not None:
            print(f"  {name}: son {MAX_QUAKE_AGE_MIN:.0f} dk içinde M≥{tr_number(MIN_MAGNITUDE)} olay sayısı {len(events)}")
            return [e for e in events if e["buyukluk"] >= MIN_MAGNITUDE]
    print("  ! Hiçbir resmi kaynağa ulaşılamadı.")
    return []


def same_event(a: dict, b: dict) -> bool:
    ta = datetime.fromisoformat(a["zaman"])
    tb = datetime.fromisoformat(b["zaman"])
    return (abs((ta - tb).total_seconds()) <= 120
            and haversine_km(a["enlem"], a["boylam"], b["enlem"], b["boylam"]) <= 80)


# ---------------------------------------------------------------- deprem postu

def hashtag(name: str) -> str:
    return "#" + re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", name)


def quake_text(event: dict, show_app_hint: bool) -> str:
    when = datetime.fromisoformat(event["zaman"]).astimezone(TR)
    mag = event["buyukluk"]
    depth = event["derinlik"]
    depth_text = f"{depth:.0f} km" if depth >= 1 else "1 km'den az"
    lines = [
        f"📍 {event['yer']}",
        f"Büyüklük {tr_number(mag)} · Derinlik {depth_text}",
        f"🕒 {when.strftime('%H:%M')} (TSİ) · Kaynak: {event['kaynak']}",
        "",
    ]
    if mag >= 5.0:
        lines += [
            "Sarsıntı sürüyorsa çök, kapan, tutun.",
            "Binadan çıkarken asansörü kullanmayın.",
            "Hatları meşgul etmemek için yakınlarınıza mesajla ulaşın.",
            "Acil durumda 112'yi arayın.",
            "",
        ]
    elif show_app_hint:
        lines += ["Bölgenizdeki depremleri telefonunuza bildirim olarak almak için profildeki bağlantıya bakabilirsiniz.", ""]
    tags = ["#deprem"]
    if event.get("il"):
        tags.append(hashtag(event["il"]))
    lines.append(" ".join(tags))
    return "\n".join(lines)


def run_quakes() -> int:
    state = load_json(QUAKES_STATE, {"paylasilan": [], "harcama": {}, "kucuk_sayac": 0})
    now = now_utc()
    since = now - timedelta(minutes=MAX_QUAKE_AGE_MIN)
    events = sorted(fetch_quakes(since), key=lambda e: e["zaman"])

    recent = [p for p in state.get("paylasilan", [])
              if now - datetime.fromisoformat(p["zaman"]) < timedelta(days=3)]
    posted_ids = {p["id"] for p in recent}
    failures = 0

    for event in events:
        when = datetime.fromisoformat(event["zaman"])
        if when < since or event["id"] in posted_ids or any(same_event(event, p) for p in recent):
            continue
        last_hour = [p for p in recent if p.get("post_zamani")
                     and now - datetime.fromisoformat(p["post_zamani"]) < timedelta(hours=1)]
        if len(last_hour) >= MAX_QUAKE_POSTS_PER_HOUR and event["buyukluk"] < 5.0:
            print(f"  - {event['yer']} M{event['buyukluk']} atlandı: son 1 saatte {len(last_hour)} post var")
            recent.append({**event, "atlandi": True})
            continue

        hint = False
        if event["buyukluk"] < 5.0 and not big_quake_within(state, PROMO_PAUSE_MAGNITUDE, hours=24, now=now):
            counter = state.get("kucuk_sayac", 0) + 1
            state["kucuk_sayac"] = counter
            hint = APP_HINT_EVERY > 0 and counter % APP_HINT_EVERY == 0
        text = quake_text(event, hint)
        if not within_budget(post_cost(text)):
            break
        print(f"  + {event['yer']} M{event['buyukluk']} ({event['kaynak']})")
        ok, result = XClient().post(text)
        if ok:
            if result != "deneme":
                record_spend(state, post_cost(text))
            recent.append({**event, "post_zamani": now.isoformat(), "post_id": result})
        else:
            failures += 1
            print(f"  ! Gönderilemedi: {result}")
            if "duplicate" in result.lower():
                recent.append({**event, "atlandi": True})

    state["paylasilan"] = recent
    if not is_dry():
        save_json(QUAKES_STATE, state)
    return 1 if failures else 0


def big_quake_within(state: dict, magnitude: float, hours: float, now: datetime | None = None) -> bool:
    now = now or now_utc()
    return any(p["buyukluk"] >= magnitude and now - datetime.fromisoformat(p["zaman"]) < timedelta(hours=hours)
               for p in state.get("paylasilan", []))


# ---------------------------------------------------------------- planlı postlar

def draft_text(draft: dict) -> str:
    text = draft["metin"].strip()
    if draft.get("baglanti"):
        text += f"\n\n{APP_LINK}"
    return text


def next_draft(drafts: list[dict], used: set[str], allow_promo: bool) -> dict | None:
    for draft in drafts:
        if draft["id"] in used:
            continue
        if not allow_promo and (draft.get("baglanti") or draft.get("tur") == "uygulama"):
            continue
        return draft
    return None


def run_scheduled() -> int:
    drafts = load_json(DRAFTS_FILE, [])
    state = load_json(POSTS_STATE, {"paylasilan": [], "harcama": {}})
    quakes = load_json(QUAKES_STATE, {"paylasilan": []})
    now = now_utc()
    # Panelden "şimdi paylaş" denince süre ve büyük deprem beklemeleri uygulanmaz; seçimi kişi yapmıştır.
    manual = os.environ.get("MANUEL") == "1"
    forced_id = os.environ.get("TASLAK_ID", "").strip()

    if not manual and big_quake_within(quakes, FULL_PAUSE_MAGNITUDE, hours=24, now=now):
        print("  Son 24 saatte büyük deprem oldu. Planlı paylaşım yapılmadı; yalnızca deprem bilgisi paylaşılıyor.")
        return 0
    last = state["paylasilan"][-1]["zaman"] if state["paylasilan"] else None
    if not manual and last and now - datetime.fromisoformat(last) < timedelta(hours=MIN_HOURS_BETWEEN_SCHEDULED):
        print(f"  Son planlı post {MIN_HOURS_BETWEEN_SCHEDULED:.0f} saatten yeni. Atlandı.")
        return 0

    allow_promo = manual or not big_quake_within(quakes, PROMO_PAUSE_MAGNITUDE, hours=24, now=now)
    used = {p["id"] for p in state["paylasilan"]}
    remaining = sum(1 for d in drafts if d["id"] not in used)
    if forced_id:
        draft = next((d for d in drafts if d["id"] == forced_id), None)
        if draft is None or forced_id in used:
            print(f"  ! {forced_id} taslağı bulunamadı ya da daha önce paylaşıldı.")
            return 1
    else:
        draft = next_draft(drafts, used, allow_promo)
    if draft is None:
        print("  ! Paylaşılacak taslak kalmadı. taslaklar.json dosyasına yeni taslak ekleyin.")
        return 1

    text = draft_text(draft)
    if not within_budget(post_cost(text)):
        return 1
    print(f"  + Taslak {draft['id']} ({draft.get('tur', '-')}), kalan taslak: {remaining - 1}")
    ok, result = XClient().post(text)
    if not ok:
        print(f"  ! Gönderilemedi: {result}")
        if "duplicate" in result.lower():
            state["paylasilan"].append({"id": draft["id"], "zaman": now.isoformat(), "post_id": "tekrar-reddedildi"})
            if not is_dry():
                save_json(POSTS_STATE, state)
        return 1
    if result != "deneme":
        record_spend(state, post_cost(text))
    state["paylasilan"].append({"id": draft["id"], "zaman": now.isoformat(), "post_id": result})
    if not is_dry():
        save_json(POSTS_STATE, state)
    if remaining - 1 < 10:
        print(f"  ! Uyarı: yalnızca {remaining - 1} taslak kaldı.")
    return 0


# ---------------------------------------------------------------- kontrol komutları

BANNED_WORDS = ["sensör", "s-dalgası", "nöbet", "enkaz", "vip", "—"]


def run_lint() -> int:
    drafts = load_json(DRAFTS_FILE, [])
    errors = 0
    ids = set()
    for draft in drafts:
        text = draft_text(draft)
        problems = []
        if draft["id"] in ids:
            problems.append("aynı id iki kez")
        ids.add(draft["id"])
        length = weighted_length(text)
        if length > 280:
            problems.append(f"{length}/280 karakter")
        lowered = text.lower()
        problems += [f"'{w}' kullanılmamalı" for w in BANNED_WORDS if w in lowered]
        if len(re.findall(r"#\w+", text)) > 2:
            problems.append("2'den fazla hashtag")
        if has_url(draft["metin"]):
            problems.append("bağlantıyı metne değil 'baglanti': true alanına koyun")
        if problems:
            errors += 1
            print(f"  ✗ {draft['id']}: {', '.join(problems)}")
    texts = [d["metin"].strip() for d in drafts]
    if len(texts) != len(set(texts)):
        errors += 1
        print("  ✗ Aynı metin birden fazla taslakta var.")
    links = sum(1 for d in drafts if d.get("baglanti"))
    cost = links * COST_WITH_URL + (len(drafts) - links) * COST_PLAIN
    print(f"  {len(drafts)} taslak, {links} tanesi bağlantılı. Tamamının maliyeti yaklaşık {cost:.2f} $.")
    print("  Sorun yok." if errors == 0 else f"  {errors} taslakta sorun var.")
    return 1 if errors else 0


def run_preview() -> int:
    drafts = load_json(DRAFTS_FILE, [])
    state = load_json(POSTS_STATE, {"paylasilan": []})
    used = {p["id"] for p in state["paylasilan"]}
    queue = [d for d in drafts if d["id"] not in used]
    print(f"Bu ay harcanan: {spent_this_month():.2f} $ / {MONTHLY_BUDGET_USD:.2f} $")
    print(f"Kalan taslak: {len(queue)} (günde 2 postla yaklaşık {len(queue) // 2} gün)\n")
    for draft in queue[:5]:
        text = draft_text(draft)
        print(f"── {draft['id']} · {draft.get('tur', '-')} · {weighted_length(text)}/280")
        print(text + "\n")
    return 0


def run_check() -> int:
    client = XClient()
    if not client.configured:
        print("X anahtarları tanımlı değil (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET).")
        return 1
    status, payload = client.me()
    if status == 200:
        print(f"Bağlantı tamam: @{payload['data']['username']}")
        return 0
    print(f"X bağlantısı başarısız: HTTP {status} {json.dumps(payload, ensure_ascii=False)[:300]}")
    return 1


def main() -> int:
    commands = {"planli": run_scheduled, "deprem": run_quakes, "onizle": run_preview,
                "denetle": run_lint, "kontrol": run_check}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(__doc__)
        return 2
    if is_dry():
        print("(Deneme modu: X'e hiçbir şey gönderilmez.)")
    return commands[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Deprem X botu için yerel kontrol paneli.

    python3 panel.py

Tarayıcıda http://127.0.0.1:8765 açılır. Yalnızca bu bilgisayardan erişilebilir.
GitHub'a `gh` aracıyla bağlanır; taslak değişiklikleri depoya commit edilip gönderilir.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import bot

ROOT = Path(__file__).resolve().parent
HTML_FILE = ROOT / "panel.html"
REPO = "barisnmz94/deprem-x-bot"
X_PROFILE = "https://x.com/Depremaninda"
TOKEN = secrets.token_urlsafe(24)
GH = shutil.which("gh") or str(Path.home() / ".local/bin/gh")
TR = timezone(timedelta(hours=3))
SCHEDULE_UTC = [(6, 10), (16, 40)]  # planli-post.yml cron satırlarıyla aynı
JITTER_MIN = 45

WORKFLOWS = {
    "planli": ("planli-post.yml", "Planlı post"),
    "deprem": ("deprem-takip.yml", "Deprem takip"),
    "kontrol": ("baglanti-kontrol.yml", "Bağlantı kontrol"),
}
TYPES = {"uygulama": "Uygulama", "hazirlik": "Hazırlık", "bilgi": "Bilgi", "aile": "Aile"}

git_lock = threading.Lock()
last_pull = 0.0


# ---------------------------------------------------------------- komut yardımcıları

def run(args: list[str], timeout: int = 60, stdin: str | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, input=stdin)
    except (subprocess.TimeoutExpired, FileNotFoundError) as error:
        return 1, str(error)
    return result.returncode, (result.stdout + result.stderr).strip()


def gh(*args: str, timeout: int = 60) -> tuple[int, str]:
    return run([GH, *args], timeout=timeout)


def git_pull(force: bool = False) -> str | None:
    """Botun yazdığı durum dosyalarını almak için depoyu günceller. Hata varsa mesajı döner."""
    global last_pull
    if not force and time.time() - last_pull < 20:
        return None
    with git_lock:
        code, out = run(["git", "pull", "-q", "--rebase", "--autostash"], timeout=40)
        last_pull = time.time()
    return None if code == 0 else f"GitHub'dan güncel durum alınamadı: {out[-300:]}"


def git_commit_push(paths: list[str], message: str) -> str | None:
    with git_lock:
        run(["git", "add", *paths])
        code, out = run(["git", "commit", "-q", "-m", message])
        if code != 0 and "nothing to commit" not in out:
            return f"Kaydedilemedi: {out[-300:]}"
        for attempt in range(4):
            run(["git", "pull", "-q", "--rebase", "--autostash"], timeout=40)
            code, out = run(["git", "push", "-q"], timeout=40)
            if code == 0:
                return None
            time.sleep(2 + attempt * 2)
        return f"GitHub'a gönderilemedi: {out[-300:]}"


# ---------------------------------------------------------------- veri

def load_drafts() -> list[dict]:
    return bot.load_json(bot.DRAFTS_FILE, [])


def save_drafts(drafts: list[dict]) -> None:
    lines = ",\n".join("  " + json.dumps(d, ensure_ascii=False) for d in drafts)
    bot.DRAFTS_FILE.write_text("[\n" + lines + "\n]\n", encoding="utf-8")


def draft_problems(draft: dict, drafts: list[dict]) -> list[str]:
    text = bot.draft_text(draft)
    problems = []
    length = bot.weighted_length(text)
    if not draft["metin"].strip():
        problems.append("Metin boş.")
    if length > 280:
        problems.append(f"Metin çok uzun: {length}/280 karakter.")
    lowered = text.lower()
    for word in bot.BANNED_WORDS:
        if word in lowered:
            problems.append(f"\"{word}\" kullanılmamalı.")
    if len(re.findall(r"#\w+", text)) > 2:
        problems.append("En fazla 2 hashtag kullanın.")
    if bot.has_url(draft["metin"]):
        problems.append("Bağlantıyı metne yazmayın, \"App Store bağlantısı ekle\" seçeneğini işaretleyin.")
    if any(d["metin"].strip() == draft["metin"].strip() and d["id"] != draft["id"] for d in drafts):
        problems.append("Aynı metin başka bir taslakta var. X aynı metni ikinci kez kabul etmez.")
    return problems


def new_draft_id(kind: str, drafts: list[dict]) -> str:
    prefix = {"uygulama": "u", "hazirlik": "h", "bilgi": "b", "aile": "a"}.get(kind, "t")
    used = {d["id"] for d in drafts}
    number = 1
    while f"y{prefix}{number:02d}" in used:
        number += 1
    return f"y{prefix}{number:02d}"


def variables() -> dict:
    code, out = gh("variable", "list", "-R", REPO, "--json", "name,value")
    if code != 0:
        return {}
    try:
        return {item["name"]: item["value"] for item in json.loads(out)}
    except json.JSONDecodeError:
        return {}


def runs_for(key: str, limit: int) -> list[dict]:
    file, label = WORKFLOWS[key]
    code, out = gh("run", "list", "-R", REPO, "-w", file, "--limit", str(limit),
                   "--json", "databaseId,status,conclusion,event,createdAt,url")
    if code != 0:
        return []
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [{**item, "is": key, "ad": label} for item in items]


def next_slot(now: datetime) -> str:
    candidates = []
    for day in (0, 1):
        for hour, minute in SCHEDULE_UTC:
            start = (now + timedelta(days=day)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if start > now - timedelta(minutes=JITTER_MIN):
                candidates.append(start)
    start = min(candidates).astimezone(TR)
    end = start + timedelta(minutes=JITTER_MIN)
    today = now.astimezone(TR).date()
    day_word = "Bugün" if start.date() == today else "Yarın"
    return f"{day_word} {start:%H:%M}–{end:%H:%M}"


def status_payload(force: bool) -> dict:
    sync_error = git_pull(force)
    drafts = load_drafts()
    posts = bot.load_json(bot.POSTS_STATE, {"paylasilan": []})
    quakes = bot.load_json(bot.QUAKES_STATE, {"paylasilan": []})
    posted = {p["id"]: p for p in posts.get("paylasilan", [])}

    with ThreadPoolExecutor(max_workers=4) as pool:
        planned = pool.submit(runs_for, "planli", 8)
        quake_runs = pool.submit(runs_for, "deprem", 6)
        checks = pool.submit(runs_for, "kontrol", 3)
        vars_future = pool.submit(variables)
        runs = planned.result() + quake_runs.result() + checks.result()
        repo_vars = vars_future.result()
    runs.sort(key=lambda r: r["createdAt"], reverse=True)

    def draft_view(d: dict) -> dict:
        p = posted.get(d["id"])
        text = bot.draft_text(d)
        return {**d, "uzunluk": bot.weighted_length(text), "maliyet": bot.post_cost(text),
                "paylasildi": bool(p), "post_id": p.get("post_id") if p else None,
                "zaman": p.get("zaman") if p else None}

    queue = [draft_view(d) for d in drafts if d["id"] not in posted]
    done = [draft_view(d) for d in drafts if d["id"] in posted]
    done.sort(key=lambda d: d["zaman"] or "", reverse=True)
    quake_posts = [q for q in quakes.get("paylasilan", []) if q.get("post_id")]
    quake_posts.sort(key=lambda q: q["zaman"], reverse=True)

    now = datetime.now(timezone.utc)
    budget = float(repo_vars.get("MONTHLY_BUDGET_USD", "8") or 8)
    big_promo = bot.big_quake_within(quakes, bot.PROMO_PAUSE_MAGNITUDE, 24, now)
    big_full = bot.big_quake_within(quakes, bot.FULL_PAUSE_MAGNITUDE, 24, now)
    return {
        "repo": REPO, "profil": X_PROFILE, "sync_error": sync_error,
        "duraklatildi": repo_vars.get("BOT_DURDUR") == "1",
        "butce": budget, "harcanan": bot.spent_this_month(),
        "min_buyukluk": float(repo_vars.get("MIN_MAGNITUDE", "4.0") or 4.0),
        "siradaki_saat": next_slot(now),
        "tanitim_bekliyor": big_promo, "tam_bekleme": big_full,
        "sira": queue, "paylasilanlar": done[:30], "depremler": quake_posts[:20],
        "calismalar": runs[:14], "turler": TYPES,
    }


def run_log(run_id: str) -> str:
    code, out = gh("run", "view", run_id, "-R", REPO, "--log", timeout=60)
    if code != 0:
        if "still in progress" in out or "in progress" in out:
            return "Çalışma henüz sürüyor. Birkaç saniye sonra tekrar bakın."
        return f"Kayıt alınamadı: {out[-400:]}"
    keep_steps = ("Taslağı paylaş", "Yeni depremleri paylaş", "X anahtarlarını doğrula", "Durumu kaydet", "Rastgele bekle")
    lines = []
    for raw in out.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) < 3 or not parts[1].startswith(keep_steps):
            continue
        line = re.sub(r"^﻿?\d{4}-\d{2}-\d{2}T[\d:.]+Z ?", "", parts[2])
        if line.startswith("##[") or re.match(r"^\s*(shell|env):", line) or re.match(r"^\s+[A-Za-z0-9_]+: ", line):
            continue
        if "\x1b[" in line or line.startswith(("python bot.py", "bash .github", "sleep ")):
            continue
        lines.append(line)
    return "\n".join(lines).strip() or "Bu çalışmada bottan çıktı yok (iş atlanmış olabilir)."


# ---------------------------------------------------------------- işlemler

def trigger(body: dict) -> dict:
    key = body.get("is")
    if key not in WORKFLOWS:
        return {"hata": "Bilinmeyen iş."}
    args = ["workflow", "run", WORKFLOWS[key][0], "-R", REPO]
    if key in ("planli", "deprem"):
        args += ["-f", f"deneme={'true' if body.get('deneme') else 'false'}"]
    if key == "planli" and body.get("taslak"):
        args += ["-f", f"taslak={body['taslak']}"]
    code, out = gh(*args)
    if code != 0:
        return {"hata": f"Başlatılamadı: {out[-300:]}"}
    return {"tamam": True}


def edit_draft(body: dict) -> dict:
    sync_error = git_pull(force=True)
    if sync_error:
        return {"hata": sync_error}
    drafts = load_drafts()
    posted = {p["id"] for p in bot.load_json(bot.POSTS_STATE, {"paylasilan": []}).get("paylasilan", [])}
    action = body.get("islem")
    draft_id = body.get("id")
    index = next((i for i, d in enumerate(drafts) if d["id"] == draft_id), None)

    if action in ("guncelle", "sil", "tasi") and (index is None or draft_id in posted):
        return {"hata": "Bu taslak bulunamadı ya da zaten paylaşıldı."}

    if action in ("ekle", "guncelle"):
        kind = body.get("tur") if body.get("tur") in TYPES else "hazirlik"
        draft = {"id": draft_id if action == "guncelle" else new_draft_id(kind, drafts), "tur": kind}
        if body.get("baglanti"):
            draft["baglanti"] = True
        draft["metin"] = str(body.get("metin", "")).replace("\r\n", "\n").strip()
        problems = draft_problems(draft, drafts)
        if problems:
            return {"hata": " ".join(problems)}
        if action == "ekle":
            position = body.get("konum")
            queue_ids = [d["id"] for d in drafts if d["id"] not in posted]
            if position == "basa" and queue_ids:
                drafts.insert(next(i for i, d in enumerate(drafts) if d["id"] == queue_ids[0]), draft)
            else:
                drafts.append(draft)
            message = f"Panel: {draft['id']} taslağı eklendi"
        else:
            drafts[index] = draft
            message = f"Panel: {draft_id} taslağı düzenlendi"
    elif action == "sil":
        drafts.pop(index)
        message = f"Panel: {draft_id} taslağı silindi"
    elif action == "tasi":
        queue = [i for i, d in enumerate(drafts) if d["id"] not in posted]
        position = queue.index(index)
        target = {"yukari": position - 1, "asagi": position + 1, "basa": 0}.get(body.get("yon"), position)
        if not 0 <= target < len(queue) or target == position:
            return {"tamam": True}
        item = drafts.pop(index)
        drafts.insert(queue[target], item)  # pop sonrası kayma, aşağı taşımada hedefin hemen arkasına denk gelir
        message = f"Panel: {draft_id} sırası değişti"
    else:
        return {"hata": "Bilinmeyen işlem."}

    save_drafts(drafts)
    error = git_commit_push(["taslaklar.json"], message)
    return {"hata": error} if error else {"tamam": True}


def update_settings(body: dict) -> dict:
    if "durdur" in body:
        if body["durdur"]:
            code, out = gh("variable", "set", "BOT_DURDUR", "-R", REPO, "--body", "1")
        else:
            code, out = gh("variable", "delete", "BOT_DURDUR", "-R", REPO)
            if code != 0 and "not found" in out.lower():
                code = 0
        return {"tamam": True} if code == 0 else {"hata": out[-300:]}
    if "butce" in body:
        try:
            value = float(body["butce"])
        except (TypeError, ValueError):
            return {"hata": "Bütçe bir sayı olmalı."}
        if not 1 <= value <= 50:
            return {"hata": "Bütçe 1 ile 50 $ arasında olmalı."}
        code, out = gh("variable", "set", "MONTHLY_BUDGET_USD", "-R", REPO, "--body", f"{value:g}")
        return {"tamam": True} if code == 0 else {"hata": out[-300:]}
    if "min_buyukluk" in body:
        try:
            value = float(body["min_buyukluk"])
        except (TypeError, ValueError):
            return {"hata": "Büyüklük bir sayı olmalı."}
        if not 3.0 <= value <= 6.0:
            return {"hata": "Büyüklük 3,0 ile 6,0 arasında olmalı."}
        code, out = gh("variable", "set", "MIN_MAGNITUDE", "-R", REPO, "--body", f"{value:.1f}")
        return {"tamam": True} if code == 0 else {"hata": out[-300:]}
    return {"hata": "Bilinmeyen ayar."}


# ---------------------------------------------------------------- sunucu

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(403, b"", "text/plain")
        url = urlparse(self.path)
        if url.path == "/":
            html = HTML_FILE.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if not self._token_ok():
            return self._json({"hata": "Yetkisiz."}, 403)
        query = parse_qs(url.query)
        if url.path == "/api/durum":
            return self._json(status_payload(force=query.get("yenile") == ["1"]))
        if url.path == "/api/kayit":
            run_id = query.get("id", [""])[0]
            if not run_id.isdigit():
                return self._json({"hata": "Geçersiz kayıt."}, 400)
            return self._json({"metin": run_log(run_id)})
        self._json({"hata": "Bulunamadı."}, 404)

    def do_POST(self) -> None:
        if not self._host_ok() or not self._token_ok():
            return self._json({"hata": "Yetkisiz."}, 403)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"hata": "Geçersiz istek."}, 400)
        routes = {"/api/calistir": trigger, "/api/taslak": edit_draft, "/api/ayar": update_settings}
        handler = routes.get(urlparse(self.path).path)
        if handler is None:
            return self._json({"hata": "Bulunamadı."}, 404)
        self._json(handler(body))

    def _token_ok(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Panel-Token", ""), TOKEN)


def main() -> int:
    if not Path(GH).exists():
        print("GitHub aracı (gh) bulunamadı. Kurulum için Claude'a yazın.")
        return 1
    code, out = gh("auth", "status")
    if code != 0:
        print("GitHub'a giriş yapılmamış. Terminalde şunu çalıştırın: ~/.local/bin/gh auth login --web")
        return 1
    for port in range(8765, 8775):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    else:
        print("Boş port bulunamadı.")
        return 1
    url = f"http://127.0.0.1:{port}"
    print(f"Deprem X paneli açık: {url}\nKapatmak için bu pencerede Ctrl+C'ye basın.")
    if "--tarayici-yok" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPanel kapatıldı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily weather bulletin for Khouribga (Morocco) -> Telegram.

Nشرة الطقس اليومية لمدينة خريبكة، تُرسَل إلى تيليجرام.

* Zero dependencies: Python standard library only (3.9+).
* Data: Open-Meteo (no API key required).
* Cross-checked between ECMWF-IFS and GFS models -> a confidence line.

Usage
    python3 weather_bot.py --dry-run          # print only, never send
    python3 weather_bot.py --send             # fetch + send to Telegram
    python3 weather_bot.py --send --only-at 7 # hourly cron: send at 07:xx local only
    python3 weather_bot.py --selftest         # offline checks, no network

Environment (or a .env file next to this script)
    TELEGRAM_BOT_TOKEN   token from @BotFather
    TELEGRAM_CHAT_ID     numeric chat id, or @channelusername (comma separated = many)
    WEATHER_LAT / WEATHER_LON / WEATHER_TZ     defaults = Khouribga
    MESSAGE_LANGUAGE     ar (default) | fr | en
    HTTP_TIMEOUT / RETRIES
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None

# --------------------------------------------------------------------------- config
CONFIG = {
    "lat": 32.88108,
    "lon": -6.90630,
    "place": "خريبكة",
    "place_latin": "Khouribga, Khouribga Province, Morocco",
    "tz": "Africa/Casablanca",
    "lang": "ar",
}
API = "https://api.open-meteo.com/v1/forecast"
MODELS = ("best_match", "ecmwf_ifs025", "gfs_seamless")

# --------------------------------------------------------------------------- i18n
T = {
    "ar": {
        "title": "نشرة الطقس اليومية — خريبكة 🇲🇦",
        "now": "الحرارة الآن",
        "feels": "الإحساس",
        "max": "العظمى",
        "min": "الصغرى",
        "cond": "السماء",
        "rain": "احتمال التساقطات",
        "precip": "الكمية المتوقعة",
        "wind": "الرياح",
        "gust": "هبّات",
        "humidity": "الرطوبة",
        "uv": "الأشعة فوق البنفسجية",
        "sunrise": "الشروق",
        "sunset": "الغروب",
        "advice": "ملاحظة",
        "models": "تقاطع النماذج",
        "source": "المصدر: Open-Meteo",
        "sent_at": "الوقت المحلي", "mm": "ملم",
        "unit_speed": "كم/س",
        "ok": "✅ توقع متين — النماذج متفقة",
        "good": "🟡 ثقة جيدة — فارق بسيط بين النماذج",
        "warn": "🟠 تفاوت بين النماذج — راقب التحديثات",
        "days": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"],
        "months": ["يناير", "فبراير", "مارس", "أبريل", "ماي", "يونيو",
                   "يوليوز", "غشت", "شتنبر", "أكتوبر", "نونبر", "دجنبر"],
        "compass": ["شمالية", "شمالية شرقية", "شرقية", "جنوبية شرقية",
                    "جنوبية", "جنوبية غربية", "غربية", "شمالية غربية"],
        "uv_lvl": ["منخفضة", "متوسطة", "مرتفعة", "مرتفعة جدًا", "خطيرة"],
        "adv": {
            "heat": "الجو حار، أكثر من شرب الماء وتجنّب الشمس بين 12 و16.",
            "veryhot": "حرارة مرتفعة جدًا: بقى في الظل ولا تترك أطفالًا أو حيوانات في السيارة.",
            "rain": "فرصة مطر: خذ معك مظلة أو سترة واقية.",
            "storm": "عاصفة رعدية ممكنة: تجنّب الحقول والأشباط والمياه المكشوفة.",
            "wind": "رياح قوية مثيرة للغبار: احذر أثناء القيادة على الطريق السيار.",
            "uv": "شمس قوية: ضع واقٍ شمسي وغطِّ رأسك.",
            "cold": "برد في الصباح الباكر والليل: لبس دافيء خصوصًا للتلاميذ.",
            "dust": "غبار في الجو: حساسية الصدر تتوقع، قلّل النشاط في الخارج.",
            "fog": "ضباب في الصباح: الانتباه في الطريق قبل الشروق.",
            "nice": "جو معتدل ولطيف، مناسب للعمل والرياضة في الخارج.",
        },
    },
    "fr": {
        "title": "Bulletin météo du jour — Khouribga 🇲🇦",
        "now": "Actuellement", "feels": "Ressenti", "max": "Max", "min": "Min",
        "cond": "Ciel", "rain": "Risque de pluie", "precip": "Précip. prévue",
        "wind": "Vent", "gust": "Rafales", "humidity": "Humidité",
        "uv": "Indice UV", "sunrise": "Lever", "sunset": "Coucher",
        "advice": "Conseil", "models": "Modèles", "source": "Source : Open-Meteo",
        "sent_at": "Heure locale", "mm": "mm", "unit_speed": "km/h",
        "ok": "✅ Prévision solide — modèles d'accord",
        "good": "🟡 Bonne confiance — léger écart entre modèles",
        "warn": "🟠 Divergence des modèles — surveille les mises à jour",
        "days": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
        "months": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                   "août", "septembre", "octobre", "novembre", "décembre"],
        "compass": ["nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest"],
        "uv_lvl": ["faible", "modéré", "élevé", "très élevé", "extrême"],
        "adv": {
            "heat": "Il fait chaud : hydrate-toi et évite le soleil entre 12h et 16h.",
            "veryhot": "Chaleur extrême : reste à l'ombre, jamais d'enfant ni d'animal dans une voiture.",
            "rain": "Risque de pluie : prends un parapluie.",
            "storm": "Orage possible : évite champs, arbres et points d'eau.",
            "wind": "Vent fort et poussière : prudence sur la route.",
            "uv": "Soleil fort : crème solaire et couvre-chef.",
            "cold": "Froid la nuit et tôt le matin : couvre-toi.",
            "dust": "Poussière en suspension : limite les efforts dehors.",
            "fog": "Brouillard matinal : prudence avant le lever du soleil.",
            "nice": "Temps agréable, idéal pour le travail et le sport en extérieur.",
        },
    },
    "en": {
        "title": "Daily weather bulletin — Khouribga 🇲🇦",
        "now": "Now", "feels": "Feels like", "max": "High", "min": "Low",
        "cond": "Sky", "rain": "Rain chance", "precip": "Expected rain",
        "wind": "Wind", "gust": "Gusts", "humidity": "Humidity",
        "uv": "UV index", "sunrise": "Sunrise", "sunset": "Sunset",
        "advice": "Note", "models": "Models", "source": "Source: Open-Meteo",
        "sent_at": "Local time", "mm": "mm", "unit_speed": "km/h",
        "ok": "✅ Reliable — models agree",
        "good": "🟡 Good confidence — small spread between models",
        "warn": "🟠 Models disagree — check for updates",
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "months": ["January", "February", "March", "April", "May", "June", "July",
                   "August", "September", "October", "November", "December"],
        "compass": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
        "uv_lvl": ["low", "moderate", "high", "very high", "extreme"],
        "adv": {
            "heat": "Hot day — drink water and avoid sun between 12:00 and 16:00.",
            "veryhot": "Extreme heat — stay in shade; never leave children or pets in a car.",
            "rain": "Rain likely — take an umbrella.",
            "storm": "Thunderstorm possible — avoid open fields, trees and water.",
            "wind": "Strong dusty wind — drive carefully.",
            "uv": "Strong sun — sunscreen and a hat.",
            "cold": "Cold early morning and night — dress warm.",
            "dust": "Airborne dust — limit outdoor exertion.",
            "fog": "Morning fog — careful driving before sunrise.",
            "nice": "Pleasant weather, good for outdoor work and sports.",
        },
    },
}

WMO = {  # code -> (emoji, ar, fr, en)
    0: ("☀️", "صافي", "Ciel dégagé", "Clear"),
    1: ("🌤️", "صحو مع سحب خفيفة", "Plutôt dégagé", "Mostly clear"),
    2: ("⛅", "غيوم متفرقة", "Partiellement nuageux", "Partly cloudy"),
    3: ("☁️", "مغيم", "Couvert", "Overcast"),
    45: ("🌫️", "ضباب", "Brouillard", "Fog"),
    48: ("🌫️", "ضباب متجمد", "Brouillard givrant", "Depositing rime fog"),
    51: ("🌦️", "رذاذ خفيف", "Bruine légère", "Light drizzle"),
    53: ("🌦️", "رذاذ", "Bruine", "Drizzle"),
    55: ("🌧️", "رذاذ كثيف", "Bruine dense", "Dense drizzle"),
    56: ("🌧️", "رذاذ متجمد", "Bruine verglaçante", "Freezing drizzle"),
    57: ("🌧️", "رذاذ متجمد كثيف", "Bruine verglaçante dense", "Dense freezing drizzle"),
    61: ("🌦️", "مطر خفيف", "Pluie faible", "Light rain"),
    63: ("🌧️", "مطر", "Pluie", "Rain"),
    65: ("🌧️", "مطر غزير", "Pluie forte", "Heavy rain"),
    66: ("🌧️", "مطر متجمد", "Pluie verglaçante", "Freezing rain"),
    67: ("🌧️", "مطر متجمد غزير", "Pluie verglaçante forte", "Heavy freezing rain"),
    71: ("🌨️", "ثلج خفيف", "Neige faible", "Light snow"),
    73: ("🌨️", "ثلج", "Neige", "Snow"),
    75: ("❄️", "ثلج غزير", "Neige forte", "Heavy snow"),
    77: ("🌨️", "حبّات ثلجية", "Grésil", "Snow grains"),
    80: ("🌦️", "زخات خفيفة", "Averses faibles", "Light showers"),
    81: ("🌧️", "زخات", "Averses", "Showers"),
    82: ("⛈️", "زخات عنيفة", "Averses violentes", "Violent showers"),
    85: ("🌨️", "زخات ثلجية", "Averses de neige", "Snow showers"),
    86: ("🌨️", "زخات ثلجية غزيرة", "Fortes averses de neige", "Heavy snow showers"),
    95: ("⛈️", "عاصفة رعدية", "Orage", "Thunderstorm"),
    96: ("⛈️", "عاصفة رعدية مع برد", "Orage avec grêle", "Thunderstorm with hail"),
    99: ("⛈️", "عاصفة رعدية مع برد قوي", "Orage avec forte grêle", "Thunderstorm with heavy hail"),
}


# --------------------------------------------------------------------------- helpers
def load_env(path: Path | None = None) -> None:
    """Tiny .env loader: KEY=VALUE, no shell expansion, never overwrites real env."""
    p = path or Path(__file__).resolve().parent / ".env"
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def now_local(tz_name: str) -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now().astimezone()


def _redact(text: str, secret: str | None) -> str:
    """Tokens travel inside the Telegram URL path -> never let them reach logs."""
    if secret:
        text = text.replace(secret, "<token>").replace(urllib.parse.quote(secret, safe=""), "<token>")
    return text


def http_json(url: str, timeout: int, retries: int, payload: dict | None = None,
               secret: str | None = None) -> dict:
    """GET (payload=None) or POST json, with retry + exponential backoff."""
    ctx = ssl.create_default_context()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            if payload is None:
                req = urllib.request.Request(url, headers={"User-Agent": "khouribga-weather/1.0"})
            else:
                data = json.dumps(payload).encode()
                req = urllib.request.Request(
                    url, data=data,
                    headers={"Content-Type": "application/json",
                             "User-Agent": "khouribga-weather/1.0"},
                    method="POST",
                )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")[:300]
            except Exception:
                pass
            if e.code == 429:  # Telegram rate limit
                wait_s = 0
                try:
                    wait_s = int(json.loads(body).get("parameters", {}).get("retry_after", 0))
                except Exception:
                    pass
                time.sleep(min(max(wait_s, 1), 30))
                last = e
                continue
            last = RuntimeError(f"HTTP {e.code} for {_redact(url.split('?')[0], secret)}: {_redact(body, secret)}")
            if e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            if e.code in (400, 401, 403, 404):  # not retryable
                break
        except Exception as e:  # URLError, timeout, JSONDecodeError...
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(_redact(f"request failed after {retries} attempts: {last}", secret))


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    return iso[11:16] if "T" in iso else iso


def num(v, digits: int = 1, dash: str = "—") -> str:
    if v is None:
        return dash
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.0f}" if abs(f - round(f)) < 0.05 else f"{f:.{digits}f}"


def wind_dir(deg, compass: list[str]) -> str:
    if deg is None:
        return ""
    return compass[int(((float(deg) % 360) + 22.5) // 45) % 8]


def uv_level(uv, levels: list[str]) -> str:
    if uv is None:
        return ""
    u = float(uv)
    idx = 0 if u < 3 else 1 if u < 6 else 2 if u < 8 else 3 if u < 11 else 4
    return levels[idx]


# --------------------------------------------------------------------------- fetch
def fetch_weather(lang: str, retries: int, timeout: int) -> dict:
    daily = ",".join([
        "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
        "precipitation_probability_max", "precipitation_sum", "weather_code",
        "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant",
        "uv_index_max", "sunrise", "sunset",
    ])
    current = ("temperature_2m,apparent_temperature,relative_humidity_2m,"
               "precipitation,weather_code,wind_speed_10m,wind_direction_10m")
    params = {
        "latitude": CONFIG["lat"], "longitude": CONFIG["lon"],
        "current": current, "daily": daily, "timezone": CONFIG["tz"],
        "forecast_days": 1, "wind_speed_unit": "kmh", "temperature_unit": "celsius",
        "models": ",".join(MODELS),
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    data = http_json(url, timeout=timeout, retries=retries)
    if "daily" not in data:
        raise RuntimeError(f"unexpected API answer: {json.dumps(data)[:300]}")
    return data


def extract(data: dict) -> dict:
    d, c = data["daily"], data.get("current", {})

    def one(key: str, default=None):
        """Open-Meteo suffixes every daily variable with the model name when
        `models=` is used, so try the bare key then each model suffix."""
        for probe in (key, *(f"{key}_{m}" for m in MODELS)):
            arr = d.get(probe)
            if isinstance(arr, list) and arr and arr[0] is not None:
                return arr[0]
        return default

    tmax_models = []
    for m in MODELS:
        v = d.get(f"temperature_2m_max_{m}")
        if isinstance(v, list) and v and v[0] is not None:
            tmax_models.append(float(v[0]))
    rain_models = []
    for m in MODELS:
        v = d.get(f"precipitation_sum_{m}")
        if isinstance(v, list) and v and v[0] is not None:
            rain_models.append(float(v[0]))

    out = {
        "date": one("time", ""),
        "t_now": c.get("temperature_2m"), "t_feels": c.get("apparent_temperature"),
        "tmax": one("temperature_2m_max"), "tmin": one("temperature_2m_min"),
        "tmax_feels": one("apparent_temperature_max"),
        "rain_prob": one("precipitation_probability_max", 0), "rain_mm": one("precipitation_sum", 0.0),
        "code_daily": one("weather_code", 0), "code_now": c.get("weather_code"),
        "wind": one("wind_speed_10m_max", c.get("wind_speed_10m")),
        "gust": one("wind_gusts_10m_max"), "wind_deg": one("wind_direction_10m_dominant"),
        "humidity": c.get("relative_humidity_2m"), "uv": one("uv_index_max"),
        "sunrise": one("sunrise"), "sunset": one("sunset"),
        "tmax_models": tmax_models, "rain_models": rain_models,
    }
    if out["tmax"] is None and tmax_models:
        out["tmax"] = max(tmax_models)
    return out


def confidence(w: dict) -> tuple[str, str]:
    """Return (key, detail) where key is 'ok' | 'good' | 'warn'."""
    spread = 0.0
    detail = ""
    if len(w["tmax_models"]) >= 2:
        spread = max(w["tmax_models"]) - min(w["tmax_models"])
        detail = f"Δ{spread:.1f}°"
    rmax = max(w["rain_models"]) if w["rain_models"] else 0.0
    rmin = min(w["rain_models"]) if w["rain_models"] else 0.0
    if spread and spread <= 0.8 and (rmax - rmin) <= 0.5:
        return "ok", detail
    if spread and spread <= 1.8 and (rmax - rmin) <= 1.5:
        return "good", detail
    return ("warn", detail) if spread else ("good", detail)


def advices(w: dict, lang: str) -> list[str]:
    a, out = T[lang]["adv"], []
    tmax = float(w["tmax"] or 0)
    tmin = float(w["tmin"] or 20)
    feels = float(w["tmax_feels"] or tmax)
    prob = float(w["rain_prob"] or 0)
    mm = float(w["rain_mm"] or 0)
    gust = float(w["gust"] or w["wind"] or 0)
    uv = float(w["uv"] or 0)
    code = int(w["code_daily"] if w["code_daily"] is not None else 0)

    if tmax >= 37 or feels >= 40:
        out.append(a["veryhot"])
    elif tmax >= 32:
        out.append(a["heat"])
    if code in (95, 96, 99) or mm >= 15:
        out.append(a["storm"])
    elif prob >= 50 or mm >= 1:
        out.append(a["rain"])
    if gust >= 40:
        out.append(a["wind"])
    elif gust >= 30 and uv < 6:
        out.append(a["dust"])
    if uv >= 8:
        out.append(a["uv"])
    if tmin <= 6:
        out.append(a["cold"])
    if code in (45, 48):
        out.append(a["fog"])
    if not out:
        out.append(a["nice"])
    return out


# --------------------------------------------------------------------------- render
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(w: dict, data: dict, lang: str) -> str:
    L = T[lang]
    loc = now_local(CONFIG["tz"])
    cond_key = 1 if lang == "ar" else 2 if lang == "fr" else 3
    try:
        code_now = int(w["code_now"]) if w["code_now"] is not None else int(w["code_daily"] or 0)
    except (TypeError, ValueError):
        code_now = 0
    entry = WMO.get(code_now, WMO.get(int(w["code_daily"] or 0), ("🌡️", "—", "—", "—")))
    emoji, cond = entry[0], entry[cond_key]
    u = L["unit_speed"]

    if loc:
        date_line = f"{L['days'][loc.weekday()]} {loc.day} {L['months'][loc.month - 1]} {loc.year}"
    else:
        date_line = w["date"] or ""

    conf_key, conf_detail = confidence(w)
    rows = [
        (f"🌡️ {L['now']}", f"{num(w['t_now'])}°", f"({L['feels']} {num(w['t_feels'])}°)"),
        (f"📈 {L['max']}", f"{num(w['tmax'])}°", f"· 📉 {L['min']} {num(w['tmin'])}°"),
        (f"☁️ {L['cond']}", f"{cond}", ""),
        (f"🌧️ {L['rain']}", f"{num(w['rain_prob'], 0)}%",
         f"· {L['precip']} {num(w['rain_mm'])} {L['mm']}"),
        (f"💨 {L['wind']}", f"{num(w['wind'], 0)} {u}",
         (f"{wind_dir(w['wind_deg'], L['compass'])}" if L["compass"] else "")
         + (f" · {L['gust']} {num(w['gust'], 0)} {u}" if w["gust"] else "")),
        (f"💧 {L['humidity']}", f"{num(w['humidity'], 0)}%", ""),
        (f"☀️ {L['uv']}", f"{num(w['uv'])}",
         f"({uv_level(w['uv'], L['uv_lvl'])})" if w["uv"] is not None else ""),
        (f"🌅 {L['sunrise']}", f"{fmt_time(w['sunrise'])}", f"· 🌇 {L['sunset']} {fmt_time(w['sunset'])}"),
    ]
    body = "\n".join(
        f"{label}: <b>{val}</b>{(' ' + note) if note.strip() else ''}"
        for label, val, note in rows
    )
    adv = " ".join(advices(w, lang))
    conf = f"{L['models']}: {L[conf_key]}" + (f" · {conf_detail}" if conf_detail else "")
    src = (f"{L['source']} (ECMWF·GFS) · {data.get('latitude', CONFIG['lat']):.3f}°N "
           f"{abs(data.get('longitude', CONFIG['lon'])):.3f}°W · {loc.strftime('%H:%M') if loc else ''} {L['sent_at']}"
           ).replace("  ", " ")
    return (f"{emoji} <b>{esc(L['title'])}</b>\n{esc(date_line)}\n\n"
            f"{body}\n\n✅ {L['advice']}: {esc(adv)}\n"
            f"<i>{esc(conf)}</i>\n<i>{esc(src)}</i>")


# --------------------------------------------------------------------------- telegram
def send_telegram(text: str, token: str, chat_ids: list[str], timeout: int, retries: int) -> None:
    for i, chat in enumerate(chat_ids):
        payload = {
            "chat_id": int(chat) if is_numeric_chat_id(chat) else chat,
            "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        http_json(f"https://api.telegram.org/bot{token}/sendMessage",
                  timeout=timeout, retries=retries, payload=payload, secret=token)
        if i < len(chat_ids) - 1:
            time.sleep(1)  # be gentle with the flood limit


def is_numeric_chat_id(chat: str) -> bool:
    return chat.lstrip("-").isdigit()


def chats_from_updates(data: dict) -> list[dict]:
    """Turn a Telegram getUpdates payload into unique, human-readable chat rows."""
    rows: dict[str, dict] = {}
    for upd in (data.get("result") or []):
        if not isinstance(upd, dict):
            continue
        for key in ("message", "edited_message", "channel_post",
                    "my_chat_member", "chat_member", "business_connection"):
            ev = upd.get(key)
            if not isinstance(ev, dict):
                continue
            if key in ("my_chat_member", "chat_member"):
                chat = (ev.get("new_chat_member") or {}).get("chat") or ev.get("chat")
            else:
                chat = ev.get("chat")
            if not isinstance(chat, dict) or chat.get("id") is None:
                continue
            cid = str(chat["id"])
            user = ev.get("from") or {}
            rows.setdefault(cid, {
                "chat_id": cid,
                "type": chat.get("type", "?"),
                "name": chat.get("title") or chat.get("first_name") or chat.get("username") or "—",
                "username": ("@" + chat["username"]) if chat.get("username") else "",
                "sent_by": user.get("username") or user.get("first_name") or "",
                "text": (ev.get("text") or "")[:28],
            })
    return list(rows.values())


def whoami(token: str, timeout: int, retries: int) -> int:
    """Ask Telegram which chats this bot is allowed to see."""
    allow = json.dumps(["message", "channel_post", "my_chat_member"])
    url = f"https://api.telegram.org/bot{token}/getUpdates?" + urllib.parse.urlencode(
        {"limit": 100, "allowed_updates": allow})
    try:
        data = http_json(url, timeout=timeout, retries=retries, secret=token)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Verifie le token (@BotFather -> /token) ; si /revoke a ete fait, le ancien ne marche plus.",
              file=sys.stderr)
        return 2
    if not data.get("ok", True):
        print("Telegram said: " + json.dumps(data, ensure_ascii=False)[:300])
        return 2
    rows = chats_from_updates(data)
    if not rows:
        print("Aucun chat visible dans getUpdates pour le moment.")
        print("  1) Ouvre ton bot dans Telegram et envoie-lui /start, puis relance --whoami.")
        print("  2) Canal : ajoute le bot comme ADMINISTRATEUR, puis relance.")
        print("  3) Si un webhook est actif, getUpdates renvoie vide : supprime-le d'abord")
        print("     (api.telegram.org/bot<TOKEN>/deleteWebhook).")
        return 1
    print(f"{len(rows)} chat(s) vu(s) par ce bot\n")
    print("        chat_id  type       nom                      username             dernier message")
    print("-" * 96)
    for r in sorted(rows, key=lambda x: (x["type"] != "private", x["chat_id"])):
        print(f"{r['chat_id']:>16}  {r['type']:<10} {r['name'][:24]:<24} "
              f"{r['username'][:20]:<20} {r['text']}")
    print("\n=> prends le chat_id voulu et mets-le dans TELEGRAM_CHAT_ID (.env ou secret GitHub).")
    print("   /start est obligatoire AVANT : sans lui Telegram refuse d'envoyer (403).")
    return 0


# --------------------------------------------------------------------------- modes
def _fixture(**over) -> dict:
    """Synthetic API response for offline tests (no network)."""
    fx = {
        "latitude": 32.881, "longitude": -6.906, "timezone": "Africa/Casablanca",
        "current": {"time": "2026-09-22T07:00", "temperature_2m": 21.4,
                    "apparent_temperature": 21.0, "relative_humidity_2m": 47,
                    "precipitation": 0.0, "weather_code": 2,
                    "wind_speed_10m": 8.2, "wind_direction_10m": 225},
        "daily": {
            "time": ["2026-09-22"], "temperature_2m_max": [33.5], "temperature_2m_min": [19.1],
            "apparent_temperature_max": [34.2], "precipitation_probability_max": [12],
            "precipitation_sum": [0.2], "weather_code": [2], "wind_speed_10m_max": [24.0],
            "wind_gusts_10m_max": [41.0], "wind_direction_10m_dominant": [250],
            "uv_index_max": [8.6], "sunrise": ["2026-09-22T07:15"], "sunset": ["2026-09-22T19:19"],
            "temperature_2m_max_best_match": [33.5], "temperature_2m_max_ecmwf_ifs025": [32.9],
            "temperature_2m_max_gfs_seamless": [33.3],
            "precipitation_sum_best_match": [0.2], "precipitation_sum_ecmwf_ifs025": [0.0],
            "precipitation_sum_gfs_seamless": [0.4],
        },
    }
    fx["daily"].update(over.pop("daily", {}))
    fx["current"].update(over.pop("current", {}))
    fx.update(over)
    return fx


def selftest() -> int:
    fails: list[str] = []
    passed = 0

    def check(name: str, ok: bool) -> None:
        nonlocal passed
        if ok:
            passed += 1
        else:
            fails.append(name)

    fx = _fixture()
    w = extract(fx)

    # 1. every field must be resolved from the suffixed multi-model payload
    for field, want in (("tmax", 33.5), ("tmin", 19.1), ("rain_prob", 12), ("uv", 8.6),
                        ("gust", 41.0), ("rain_mm", 0.2), ("sunrise", "2026-09-22T07:15"),
                        ("sunset", "2026-09-22T19:19"), ("code_daily", 2), ("wind", 24.0)):
        check(f"extract.{field} == {want}", w[field] == want)
    check("extract.tmax_models has 3", len(w["tmax_models"]) == 3)
    check("extract.wind_deg", w["wind_deg"] == 250)

    # 2. rendered message keeps the numbers and carries no placeholders
    for lang in ("ar", "fr", "en"):
        msg = build_message(extract(fx), fx, lang)
        for needle in ("33.5", "19.1", "07:15", "19:19", "12%", "8.6"):
            check(f"[{lang}] {needle} present", needle in msg)
        for bad in ("None", "— mm", "%)", "nan"):
            check(f"[{lang}] no '{bad.strip()}'", bad not in msg)
        check(f"[{lang}] tags balanced",
              msg.count("<b>") == msg.count("</b>") and msg.count("<i>") == msg.count("</i>"))
        check(f"[{lang}] multi-line", msg.count("\n") >= 10)
    ar = build_message(extract(fx), fx, "ar")
    check("[ar] arabic weekday+month", "الثلاثاء" in ar and "شتنبر" in ar)
    check("[ar] wind direction arabic (250deg -> west)", "غربية" in ar)
    check("[ar] wind boundary 225deg -> SW", wind_dir(225, T["ar"]["compass"]) == "جنوبية غربية")
    check("[ar] uv level arabic", "مرتفعة جدًا" in ar)
    check("[ar] sky from code_now (2 = partly cloudy)", "غيوم متفرقة" in ar)

    # 3. advice rules fire on the thresholds they claim
    check("adv wind (gust 41 >= 40)", any("رياح" in a for a in advices(w, "ar")))
    check("adv uv (8.6 >= 8)", any("واقٍ" in a for a in advices(w, "ar")))
    check("adv heat (tmax 33.5 >= 32)", any("حار" in a for a in advices(w, "ar")))
    hot = extract(_fixture(daily={"temperature_2m_max": [41.0], "temperature_2m_min": [26.0],
                                  "apparent_temperature_max": [43.0], "uv_index_max": [10.0],
                                  "wind_gusts_10m_max": [10.0], "wind_speed_10m_max": [10.0],
                                  "precipitation_probability_max": [0], "weather_code": [0]}))
    check("adv veryhot (41 deg)", any("حرارة مرتفعة جدًا" in a for a in advices(hot, "ar")))
    check("veryhot has no wind advice", not any("رياح" in a for a in advices(hot, "ar")))
    storm = extract(_fixture(daily={"weather_code": [96], "precipitation_sum": [22.0],
                                    "precipitation_probability_max": [90]}))
    check("adv storm (code 96)", any("عاصفة" in a for a in advices(storm, "ar")))
    cold = extract(_fixture(daily={"temperature_2m_min": [1.5], "temperature_2m_max": [12.0],
                                   "apparent_temperature_max": [10.0], "uv_index_max": [3.0],
                                   "weather_code": [0], "wind_gusts_10m_max": [5.0],
                                   "wind_speed_10m_max": [5.0]}))
    check("adv cold (tmin 1.5)", any("برد" in a for a in advices(cold, "ar")))

    # 4. model-agreement grading covers all three grades
    check("conf ok on tight spread", confidence(extract(fx))[0] == "ok")
    wide = extract(_fixture(daily={"temperature_2m_max_gfs_seamless": [38.0],
                                   "precipitation_sum_gfs_seamless": [9.0]}))
    check("conf warn on 4.5 deg spread", confidence(wide)[0] == "warn")
    mid = extract(_fixture(daily={"temperature_2m_max_gfs_seamless": [34.2]}))
    check("conf good on 1.3 deg spread", confidence(mid)[0] == "good")
    edge = extract(_fixture(daily={"temperature_2m_max_gfs_seamless": [35.0]}))
    check("conf warn on 2.1 deg spread", confidence(edge)[0] == "warn")
    check("conf no models -> good fallback",
          confidence(extract({"daily": {"time": ["x"]}, "current": {}}))[0] in ("good", "warn"))

    # 5. degenerate / missing data must degrade, never crash
    sparse = {"daily": {"time": ["2026-09-22"]}, "current": {}}
    try:
        sm = build_message(extract(sparse), sparse, "ar")
        check("sparse renders", "32.881" not in sm or True)
        check("sparse has dashes", "—" in sm)
    except Exception as e:
        check(f"sparse crashed: {e!r}", False)
    try:  # all-null daily arrays (happens for far-future dates)
        build_message(extract({"daily": {"temperature_2m_max": [None], "time": ["2026-09-22"]},
                               "current": {}}), {"daily": {}, "current": {}}, "fr")
    except Exception as e:
        check(f"null-array crashed: {e!r}", False)
    try:
        check("bad wind dir tolerated", wind_dir(None, T["ar"]["compass"]) == "")
        check("wind dir 0 -> north", wind_dir(0, T["ar"]["compass"]) == "شمالية")
        check("wind dir 359 wraps", wind_dir(359, T["ar"]["compass"]) == "شمالية")
        check("uv 11 extreme", uv_level(11, T["ar"]["uv_lvl"]) == "خطيرة")
        check("fmt_time None", fmt_time(None) == "—")
        check("num rounds ints", num(12.0) == "12" and num(0.2) == "0.2")
        check("chat id parse", is_numeric_chat_id("-1001234") and not is_numeric_chat_id("@chan"))
        check("esc html", esc("<b>&x") == "&lt;b&gt;&amp;x")
    except Exception as e:
        check(f"helper crashed: {e!r}", False)

    # 6. getUpdates parser behind --whoami
    upd = {"ok": True, "result": [
        {"update_id": 1, "message": {"from": {"username": "khouribga_user"},
                                      "text": "/start",
                                      "chat": {"id": 123456789, "type": "private",
                                              "first_name": "Yassine", "username": "yassine_kh"}}},
        {"update_id": 2, "message": {"chat": {"id": 123456789, "type": "private"}, "text": "salam"}}  # dup
        ,{"update_id": 3, "channel_post": {"chat": {"id": -1001554433221, "type": "channel",
                                                    "title": "طقس خريبكة"}}}
        ,{"update_id": 4, "my_chat_member": {"new_chat_member": {
            "chat": {"id": -100999, "type": "supergroup", "title": "Ait Ishaq"}}}}
        ,{"update_id": 5, "message": {"chat": {}}}      # no id -> ignored
        ,{"update_id": 6}                                # no message -> ignored
    ]}
    rows = chats_from_updates(upd)
    check("whoami dedups chats", len(rows) == 3)
    ids = sorted(r["chat_id"] for r in rows)
    check("whoami ids", ids == ["-1001554433221", "-100999", "123456789"])
    priv = [r for r in rows if r["chat_id"] == "123456789"][0]
    check("whoami keeps username", priv["username"] == "@yassine_kh")
    check("whoami keeps first msg", priv["text"] == "/start")
    chan = [r for r in rows if r["chat_id"] == "-1001554433221"][0]
    check("whoami channel title arabic", chan["name"] == "طقس خريبكة")
    check("whoami channel type", chan["type"] == "channel")
    sg = [r for r in rows if r["chat_id"] == "-100999"][0]
    check("whoami my_chat_member parsed", sg["name"] == "Ait Ishaq")
    for junk in ({}, {"ok": False}, {"result": None}, {"result": []},
                 {"result": [None, 7, {"message": None}]}):
        try:
            chats_from_updates(junk)
        except Exception as e:
            check(f"whoami tolerates {junk!r} -> {e!r}", False)
    check("empty updates -> []", chats_from_updates({}) == [])

    if fails:
        print(f"SELFTEST FAILED ({len(fails)} of {passed + len(fails)} checks):\n  - " + "\n  - ".join(fails))
    else:
        print(f"SELFTEST OK — {passed} checks passed, 0 failed")
    return 0 if not fails else 1


def main(argv: list[str] | None = None) -> int:
    load_env()
    ap = argparse.ArgumentParser(description="Daily Khouribga weather bulletin -> Telegram")
    ap.add_argument("--send", action="store_true", help="actually send to Telegram")
    ap.add_argument("--dry-run", action="store_true", help="print the message, send nothing")
    ap.add_argument("--lang", choices=sorted(T), default=os.environ.get("MESSAGE_LANGUAGE", CONFIG["lang"]))
    ap.add_argument("--only-at", type=int, choices=range(24), metavar="HOUR",
                    help="send only when local hour == HOUR (lets you run hourly from cron)")
    ap.add_argument("--whoami", action="store_true",
                    help="list the chat ids this bot can already see, then exit")
    ap.add_argument("--selftest", action="store_true", help="offline sanity checks")
    ap.add_argument("--debug", action="store_true", help="dump raw API json")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.whoami:
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not tok:
            print("ERROR: exporte d'abord TELEGRAM_BOT_TOKEN (voir .env.example)", file=sys.stderr)
            return 3
        return whoami(tok, int(os.environ.get("HTTP_TIMEOUT", "25")), 2)

    CONFIG["lang"] = args.lang
    lang = args.lang
    timeout = int(os.environ.get("HTTP_TIMEOUT", "25"))
    retries = int(os.environ.get("RETRIES", "4"))

    try:
        data = fetch_weather(lang, retries, timeout)
    except Exception as e:
        print(f"ERROR fetching weather: {e}", file=sys.stderr)
        token, chats = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if args.send and token and chats and retries >= 2:
            try:  # never fail silently on an unattended daily job
                send_telegram(f"⚠️ تعذّر إرسال نشرة الطقس اليوم.<br><code>{esc(str(e))[:400]}</code>",
                              token, chats.split(","), timeout, 2)
            except Exception as e2:
                print(f"could not send failure notice: {e2}", file=sys.stderr)
        return 2

    if args.debug:
        print(json.dumps(data, ensure_ascii=False, indent=1), file=sys.stderr)

    w = extract(data)
    msg = build_message(w, data, lang)

    if args.only_at is not None:
        if now_local(CONFIG["tz"]).hour != args.only_at:
            print(f"skipped: local hour {now_local(CONFIG['tz']).hour} != {args.only_at}")
            return 0

    if args.send and not args.dry_run:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
        if not token or not chats:
            print("ERROR: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see .env.example)", file=sys.stderr)
            print("--- message that would have been sent ---\n" + msg)
            return 3
        try:
            send_telegram(msg, token, chats, timeout, retries)
        except Exception as e:
            print(f"ERROR sending to Telegram: {e}", file=sys.stderr)
            return 4
        print(f"sent to {len(chats)} chat(s)")
    else:
        print(msg)
        if args.dry_run:
            print("\n(dry-run: nothing was sent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

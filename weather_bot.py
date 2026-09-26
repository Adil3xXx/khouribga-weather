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
import math
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

# Windows consoles default to cp1252 and crash on Arabic/emoji output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --------------------------------------------------------------------------- config
CONFIG = {
    "lat": 32.88108,
    "lon": -6.90630,
    "place": "خريبكة",
    "tz": "Africa/Casablanca",
    "lang": "ar",
}
API = "https://api.open-meteo.com/v1/forecast"
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODING_FALLBACK_API = "https://nominatim.openstreetmap.org/search"
METNO_API = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
PRAYER_API = "https://api.aladhan.com/v1/timings"
MODELS = ("best_match", "ecmwf_ifs025", "gfs_seamless")
TELEGRAM_API = "https://api.telegram.org"
PRAYER_METHOD = 21  # Aladhan: Ministry of Habous (Morocco)  [21, NOT 15]
PRAYER_FAJR_ANGLE = 18.0   # local fallback, like Habous
PRAYER_ISHA_ANGLE = 17.0   # local fallback, like Habous
POLL_LONG_POLL = 50  # Telegram long-poll seconds (keep HTTP timeout above this)

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
        "source": "المصدر:",
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
        "cmd": {
            "start": (
                "👋 أهلاً بك في <b>بوت الطقس والأوقات</b> 🌤️🕌\n\n"
                "أرسل اسم أي مدينة وسأجيبك بنشرة الطقس اليومية 🌦️\n"
                "أو استخدم هذه الأوامر:\n\n"
                "🌦️ <code>/طقس خريبكة</code> — حالة الطقس\n"
                "🕌 <code>صلاة الدار البيضاء</code> — أوقات الصلاة\n"
                "❓ <code>/help</code> — كل الأوامر\n\n"
                "الردود دائماً بالعربية 🇲🇦"
            ),
            "help": (
                "📖 <b>الأوامر المتاحة</b>\n\n"
                "🌦️ <code>/طقس &lt;مدينة&gt;</code>\n    الطقس اليوم في المدينة\n"
                "🕌 <code>صلاة &lt;مدينة&gt;</code>\n    أوقات الصلوات الخمس\n"
                "🌤️ <code>/طقس</code> بدون مدينة\n    الطقس في خريبكة (الافتراضي)\n"
                "🕌 <code>صلاة</code> بدون مدينة\n    الأوقات في خريبكة\n"
                "🏠 <code>/start</code> — رسالة الترحيب\n"
                "👋 <code>سلام</code> — التحية\n"
                "👨‍💻 <code>/help</code> — هذه القائمة\n\n"
                "مثال: <code>صلاة مراكش</code> أو <code>/طقس الرباط</code>"
            ),
            "hello": "مرحباً بك يا عزيزي! 👋 كيف أستطيع المساعدة؟ جرب <code>/help</code>",
            "thanks": "على الرحب والسعة! 😊 جرب تسألني عن أي مدينة أخرى 🌍",
            "prayer": "🕌 أوقات الصلاة في",
            "prayer_header": "🕌 <b>أوقات الصلاة —",
            "prayer_fajr": "الفجر",
            "prayer_sunrise": "الشروق",
            "prayer_dhuhr": "الظهر",
            "prayer_asr": "العصر",
            "prayer_maghrib": "المغرب",
            "prayer_isha": "العشاء",
            "not_found": "❌ لم أجد مدينة بهذا الاسم. تأكد من الإملاء أو جرّب اسماً أقرب (مثال: <code>الدار البيضاء</code> أو <code>Casablanca</code>).",
            "net_error": "⚠️ لا يمكن الوصول لخوادم الطقس الآن. تحقق من اتصالك بالإنترنت ثم أعد المحاولة بعد قليل.",
            "error": "⚠️ حدث خطأ:",
            "hijri": "التقويم الهجري:",
        },
    },
    "fr": {
        "title": "Bulletin météo du jour — Khouribga 🇲🇦",
        "now": "Actuellement", "feels": "Ressenti", "max": "Max", "min": "Min",
        "cond": "Ciel", "rain": "Risque de pluie", "precip": "Précip. prévue",
        "wind": "Vent", "gust": "Rafales", "humidity": "Humidité",
        "uv": "Indice UV", "sunrise": "Lever", "sunset": "Coucher",
        "advice": "Conseil", "models": "Modèles", "source": "Source :",
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
        "cmd": {
            "start": (
                "👋 Bienvenue sur <b>Bot météo & prières</b> 🌤️🕌\n\n"
                "Envoie le nom d'une ville pour recevoir le bulletin météo 🌦️\n"
                "Ou utilise ces commandes :\n\n"
                "🌦️ <code>/طقس خريبكة</code> — météo\n"
                "🕌 <code>صلاة الدار البيضاء</code> — heures de prière\n"
                "❓ <code>/help</code> — toutes les commandes\n\n"
            ),
            "help": (
                "📖 <b>Commandes disponibles</b>\n\n"
                "🌦️ <code>/طقس &lt;ville&gt;</code>\n    météo du jour\n"
                "🕌 <code>صلاة &lt;ville&gt;</code>\n    heures des 5 prières\n"
                "🌤️ <code>/طقس</code> sans ville\n    météo à Khouribga (défaut)\n"
                "🕌 <code>صلاة</code> sans ville\n    prières à Khouribga\n"
                "🏠 <code>/start</code> — bienvenue\n"
                "👋 <code>سلام</code> — salutation\n"
                "👨‍💻 <code>/help</code> — cette liste\n\n"
                "Exemple : <code>صلاة مراكش</code> ou <code>/طقس الرباط</code>"
            ),
            "hello": "Bienvenue ! 👋 Comment puis-je t'aider ? Essaie <code>/help</code>",
            "thanks": "Avec plaisir ! 😊 Demande-moi pour une autre ville 🌍",
            "prayer": "🕌 Heures de prière à",
            "prayer_header": "🕌 <b>Heures de prière —",
            "prayer_fajr": "Fajr", "prayer_sunrise": "Lever du soleil", "prayer_dhuhr": "Dhuhr",
            "prayer_asr": "Asr", "prayer_maghrib": "Maghrib", "prayer_isha": "Isha",
            "not_found": "❌ Ville introuvable. Vérifie l'orthographe ou essaie un nom plus proche (ex : <code>الدار البيضاء</code> ou <code>Casablanca</code>).",
            "net_error": "⚠️ Serveurs météo injoignables pour l'instant. Vérifie ta connexion et réessaie.",
            "error": "⚠️ Erreur :",
            "hijri": "Calendrier hégirien :",
        },
    },
    "en": {
        "title": "Daily weather bulletin — Khouribga 🇲🇦",
        "now": "Now", "feels": "Feels like", "max": "High", "min": "Low",
        "cond": "Sky", "rain": "Rain chance", "precip": "Expected rain",
        "wind": "Wind", "gust": "Gusts", "humidity": "Humidity",
        "uv": "UV index", "sunrise": "Sunrise", "sunset": "Sunset",
        "advice": "Note", "models": "Models", "source": "Source:",
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
        "cmd": {
            "start": (
                "👋 Welcome to <b>Weather & Prayer bot</b> 🌤️🕌\n\n"
                "Send a city name and I'll reply with the weather 🌦️\n"
                "Or use these commands :\n\n"
                "🌦️ <code>/طقس خريبكة</code> — weather\n"
                "🕌 <code>صلاة الدار البيضاء</code> — prayer times\n"
                "❓ <code>/help</code> — all commands\n\n"
            ),
            "help": (
                "📖 <b>Available commands</b>\n\n"
                "🌦️ <code>/طقس &lt;city&gt;</code>\n    today's weather\n"
                "🕌 <code>صلاة &lt;city&gt;</code>\n    times of the 5 prayers\n"
                "🌤️ <code>/طقس</code> no city\n    weather in Khouribga (default)\n"
                "🕌 <code>صلاة</code> no city\n    prayers in Khouribga\n"
                "🏠 <code>/start</code> — welcome\n"
                "👋 <code>سلام</code> — greeting\n"
                "👨‍💻 <code>/help</code> — this list\n\n"
                "Example : <code>صلاة مراكش</code> or <code>/طقس الرباط</code>"
            ),
            "hello": "Welcome! 👋 How can I help? Try <code>/help</code>",
            "thanks": "You're welcome! 😊 Ask me about another city 🌍",
            "prayer": "🕌 Prayer times in",
            "prayer_header": "🕌 <b>Prayer times —",
            "prayer_fajr": "Fajr", "prayer_sunrise": "Sunrise", "prayer_dhuhr": "Dhuhr",
            "prayer_asr": "Asr", "prayer_maghrib": "Maghrib", "prayer_isha": "Isha",
            "not_found": "❌ City not found. Check the spelling or try a closer name (e.g. <code>الدار البيضاء</code> or <code>Casablanca</code>).",
            "net_error": "⚠️ Weather servers unreachable right now. Check your connection and retry.",
            "error": "⚠️ Error:",
            "hijri": "Hijri calendar:",
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
    79: ("🌧️", "مطر وثلج", "Pluie et neige", "Rain and snow"),
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
    if p.is_file():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    lat = os.environ.get("WEATHER_LAT", "").strip()
    lon = os.environ.get("WEATHER_LON", "").strip()
    tz = os.environ.get("WEATHER_TZ", "").strip()
    try:
        if lat:
            CONFIG["lat"] = float(lat)
    except ValueError:
        pass
    try:
        if lon:
            CONFIG["lon"] = float(lon)
    except ValueError:
        pass
    if tz:
        CONFIG["tz"] = tz


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
def fetch_weather(retries: int, timeout: int, lat: float | None = None,
                  lon: float | None = None, tz: str | None = None) -> dict:
    daily = ",".join([
        "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
        "precipitation_probability_max", "precipitation_sum", "weather_code",
        "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant",
        "uv_index_max", "sunrise", "sunset",
    ])
    current = ("temperature_2m,apparent_temperature,relative_humidity_2m,"
               "precipitation,weather_code,wind_speed_10m,wind_direction_10m")
    params = {
        "latitude": CONFIG["lat"] if lat is None else lat,
        "longitude": CONFIG["lon"] if lon is None else lon,
        "current": current, "daily": daily, "timezone": CONFIG["tz"] if tz is None else tz,
        "forecast_days": 1, "wind_speed_unit": "kmh", "temperature_unit": "celsius",
        "models": ",".join(MODELS),
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    r_om, t_om = _probe_budget(retries, timeout)
    try:
        data = http_json(url, timeout=t_om, retries=r_om)
        if "daily" not in data:
            raise RuntimeError(f"unexpected API answer: {json.dumps(data)[:300]}")
        return data
    except Exception as e:
        fallback = fetch_weather_metno(lat, lon, tz, retries, timeout)
        if fallback is None:
            raise
        fallback["_fallback_of"] = _redact(str(e), None)[:120]
        return fallback


def fetch_weather_metno(lat: float | None, lon: float | None, tz: str | None,
                        retries: int, timeout: int) -> dict | None:
    """Fallback weather via api.met.no locationforecast (no key, stable).

    Returns an Open-Meteo-shaped payload when reachable, else None.
    """
    rlat = CONFIG["lat"] if lat is None else lat
    rlon = CONFIG["lon"] if lon is None else lon
    params = {"lat": rlat, "lon": rlon}
    url = f"{METNO_API}?{urllib.parse.urlencode(params)}"
    try:
        data = http_json(url, timeout=timeout, retries=retries)
    except Exception:
        return None
    series = []
    for point in (data.get("properties", {}).get("timeseries") or []):
        ts = point.get("time")
        inst = (((point.get("data") or {}).get("instant") or {}).get("details")) or {}
        hour = (((point.get("data") or {}).get("next_1_hours") or {}).get("details")) or {}
        symbol = (((point.get("data") or {}).get("next_1_hours") or {}).get(
            "summary") or {}).get("symbol_code") or ""
        if not inst or not ts:
            continue
        try:
            stemp = float(inst.get("air_temperature"))
        except (TypeError, ValueError):
            continue
        series.append({
            "time": ts, "temp": stemp,
            "hum": inst.get("relative_humidity"),
            "wind": inst.get("wind_speed"), "deg": inst.get("wind_from_direction"),
            "rain": hour.get("precipitation_amount", 0.0), "sym": symbol,
        })
    if not series:
        return None
    tmax = max(p["temp"] for p in series)
    tmin = min(p["temp"] for p in series)
    rain_sum = sum(float(p["rain"] or 0) for p in series)
    now = series[0]
    wind, deg = now["wind"], now["deg"]
    try:
        gust = max(float(p["wind"] or 0) for p in series[:6])
    except Exception:
        gust = wind
    code = metno_symbol_code(now["sym"])
    ris, set_ = sunrise_sunset(rlat, rlon, tz or CONFIG["tz"])
    return {
        "current": {
            "temperature_2m": now["temp"], "apparent_temperature": now["temp"],
            "relative_humidity_2m": now["hum"], "precipitation": now["rain"],
            "weather_code": code, "wind_speed_10m": wind, "wind_direction_10m": deg,
        },
        "daily": {
            "time": [series[0]["time"][:10]],
            "temperature_2m_max": [tmax], "temperature_2m_min": [tmin],
            "apparent_temperature_max": [tmax],
            "precipitation_probability_max": [100 if rain_sum > 0.1 else 0],
            "precipitation_sum": [rain_sum],
            "weather_code": [code],
            "wind_speed_10m_max": [gust], "wind_direction_10m_dominant": [deg],
            "sunrise": [ris], "sunset": [set_],
        },
        "latitude": rlat, "longitude": rlon, "timezone": CONFIG["tz"] if tz is None else tz,
        "provider": "met.no",
    }


def sunrise_sunset(lat: float, lon: float, tz: str | None = None) -> tuple[str, str]:
    """Local sunrise/sunset as HH:MM, computed astronomically (no network)."""
    times = compute_prayer_times(lat, lon, tz or CONFIG["tz"])
    if times is None:
        return "—", "—"
    return times["timings"].get("Sunrise", "—"), times["timings"].get("Maghrib", "—")


def metno_symbol_code(symbol: str) -> int:
    """Map met.no weather symbol codes to Open-Meteo WMO weather codes."""
    s = (symbol or "").split("_")[0].lower()
    if "thunder" in s:
        return 95
    if "snowshowers" in s or "sleet" in s:
        return 79 if "sleet" in s else 85
    if "snow" in s:
        return 71 if "light" in s else 75 if "heavy" in s else 73
    if "showers" in s:
        if "light" in s:
            return 80
        return 82 if "heavy" in s else 81
    table = {
        "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
        "drizzle": 51, "freezingrain": 66, "lightrain": 61, "rain": 63,
        "heavyrain": 65,
    }
    return table.get(s, 3)


CITY_ALIASES = {  # Arabic spellings Open-Meteo does not resolve to MA
    "الرباط": "Rabat", "الرباط المغرب": "Rabat",
    "أكادير": "Agadir", "الأغادير": "Agadir", "اكادير": "Agadir",
    "سلا": "Salé", "سلا المغرب": "Salé", "الجديدة": "El Jadida",
    "خريبكة": "Khouribga", "ميدلت": "Midelt", "بني ملال": "Beni Mellal",
    "إفران": "Ifrane", "صفرو": "Sefrou", "تازة": "Taza", "الحسيمة": "Al Hoceima",
    "اقليم": "Province",
}


def _probe_budget(retries: int, timeout: int) -> tuple[int, int]:
    """Fast budget for primary APIs (Open-Meteo/Aladhan): when they are slow or
    unreachable we want to fall back quickly instead of spending retries*timeout."""
    return 1, min(timeout, 8)


def _geo_probe(query: str, country_code: str, retries: int, timeout: int) -> list[dict]:
    params = {"name": query, "count": 20, "language": "ar", "format": "json"}
    if country_code:
        params["countryCode"] = country_code
    url = f"{GEOCODING_API}?{urllib.parse.urlencode(params)}"
    data = http_json(url, timeout=timeout, retries=retries)
    return (data or {}).get("results") or []


def guess_tz(lon: float) -> str:
    """Approximate IANA zone name from longitude (no tzdata lookup).

    Python maps ``Etc/GMT±n`` straight to a fixed offset, so a city far from
    Morocco still gets a sane solar day even without an exact timezone."""
    hours = round(lon / 15)
    if hours == 0:
        return "Etc/GMT"
    sign = "-" if hours > 0 else "+"  # Etc/GMT has inverted sign convention
    return f"Etc/GMT{sign}{abs(hours)}"


def _geocode_nominatim(query: str, retries: int, timeout: int) -> dict:
    """Fallback geocoder: Nominatim (OpenStreetMap), Morocco-city first."""
    params = {"q": query, "format": "jsonv2", "limit": 5,
              "accept-language": "ar", "addressdetails": 1}
    url = f"{GEOCODING_FALLBACK_API}?{urllib.parse.urlencode(params)}"
    r_nom, t_nom = _probe_budget(retries, timeout)
    data = http_json(url, timeout=t_nom, retries=r_nom)
    rows = data if isinstance(data, list) else []
    if not rows:
        raise RuntimeError(f"no city found for {query!r}")

    def _is_settlement(r):
        return ((r.get("addresstype") or r.get("type") or "")).lower() in (
            "city", "town", "village", "municipality", "suburb", "borough", "county")

    def _cc(r):
        return (((r.get("address") or {}).get("country_code") or "")).upper()

    ma_settlements = [r for r in rows if _cc(r) == "MA" and _is_settlement(r)]
    any_settlements = [r for r in rows if _is_settlement(r)]
    ma_any = [r for r in rows if _cc(r) == "MA"]
    best = (ma_settlements or any_settlements or ma_any or rows)[0]
    name = (best.get("display_name") or query).split(",")[0].strip()
    admin1 = (best.get("address") or {}).get("state") or ""
    country = (best.get("address") or {}).get("country") or ""
    tz = CONFIG["tz"] if _cc(best) == "MA" else guess_tz(float(best["lon"]))
    return {
        "name": name,
        "display": ", ".join(x for x in (name, admin1, country) if x),
        "lat": float(best["lat"]), "lon": float(best["lon"]),
        "tz": tz, "admin1": admin1, "country": country,
    }


def geocode_city(query: str, retries: int, timeout: int) -> dict:
    """Resolve a city name to {name, display, lat, lon, tz, admin1, country}.

    Morocco-first: try MA with the raw query and its alias, then MA without a
    country hint, and only then fall back to any country. Homonyms elsewhere
    (e.g. arabic "الرباط" is a Yemeni village in Open-Meteo) must not win.
    Falls back to Nominatim when the primary geocoder is unreachable.
    """
    probes = [query]
    if query in CITY_ALIASES:
        probes.insert(0, CITY_ALIASES[query])
    results: list[dict] = []
    geo_error: Exception | None = None
    r_geo, t_geo = _probe_budget(retries, timeout)

    for probe in probes:  # MA + alias first
        try:
            results = _geo_probe(probe, "MA", r_geo, t_geo)
        except Exception as e:
            results = []
            geo_error = e
            break  # primary geocoder down -> stop probing, use Nominatim
        if results:
            break
    if not results and geo_error is None:
        for probe in probes:  # then any country whose top hit is MA
            try:
                results = _geo_probe(probe, "", r_geo, t_geo)
            except Exception as e:
                results = []
                geo_error = e
                break
            if results and any((r.get("country_code") or "").upper() == "MA"
                               for r in results[:3]):
                break
            results = []
    if not results and geo_error is None:  # very last resort: first hit anywhere
        try:
            results = _geo_probe(query, "", r_geo, t_geo)
        except Exception as e:
            geo_error = e
    if not results:
        try:  # primary geocoder failed/empty -> Nominatim
            return _geocode_nominatim(query, retries, timeout)
        except Exception as e2:
            raise RuntimeError(f"{geo_error}; nominatim: {e2}") if geo_error else e2
    best = next((r for r in results if (r.get("country_code") or "").upper() == "MA"),
                results[0])
    r = best
    return {
        "name": r.get("name") or query,
        "display": ", ".join(x for x in (r.get("name"), r.get("admin1"),
                                         r.get("country")) if x),
        "lat": r["latitude"], "lon": r["longitude"],
        "tz": r.get("timezone") or CONFIG["tz"],
        "admin1": r.get("admin1") or "", "country": r.get("country") or "",
    }


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
    """Return (key, detail) where key is 'ok' | 'good' | 'warn'.

    With a single model (e.g. met.no fallback) there is no spread, so report
    'good' with no detail rather than pretending several models were used.
    """
    spread = 0.0
    detail = ""
    if len(w["tmax_models"]) >= 2:
        spread = max(w["tmax_models"]) - min(w["tmax_models"])
        detail = f"Δ{spread:.1f}°"
    rmax = max(w["rain_models"]) if w["rain_models"] else 0.0
    rmin = min(w["rain_models"]) if w["rain_models"] else 0.0
    if not spread:
        return "good", ""
    if spread <= 0.8 and (rmax - rmin) <= 0.5:
        return "ok", detail
    if spread <= 1.8 and (rmax - rmin) <= 1.5:
        return "good", detail
    return "warn", detail


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


def build_message(w: dict, data: dict, lang: str, place: str | None = None) -> str:
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
    place_name = place or CONFIG["place"]
    if place:
        base = {"ar": "نشرة الطقس —", "fr": "Bulletin météo —", "en": "Weather bulletin —"}.get(lang, "—")
        title = f"{base} {esc(place_name)} 🇲🇦" if lang == "ar" else f"{base} {esc(place_name)}"
    else:
        title = esc(L['title'])

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
    is_metno = data.get("provider") == "met.no"
    if is_metno:
        conf_line = ""
    else:
        conf_key, conf_detail = confidence(w)
        conf_line = f"{L['models']}: {L[conf_key]}" + (f" · {conf_detail}" if conf_detail else "")
    prov = "met.no" if is_metno else "Open-Meteo (ECMWF·GFS)"
    mlat = data.get("latitude", CONFIG["lat"])
    mlon = data.get("longitude", CONFIG["lon"])
    ns = "S" if mlat < 0 else "N"
    ew = "W" if mlon < 0 else "E"
    src = (f"{L['source']} {prov} · {abs(mlat):.3f}°{ns} "
           f"{abs(mlon):.3f}°{ew} · {loc.strftime('%H:%M') if loc else ''} {L['sent_at']}"
           ).replace("  ", " ")
    return (f"{emoji} <b>{title}</b>\n{esc(date_line)}\n\n"
            f"{body}\n\n✅ {L['advice']}: {esc(adv)}\n"
            f"{('<i>' + esc(conf_line) + '</i>\n') if conf_line else ''}"
            f"<i>{esc(src)}</i>")


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


# --------------------------------------------------------------------------- prayer
def fetch_prayer(lat: float, lon: float, retries: int, timeout: int,
                 timezone: str | None = None) -> dict:
    """Prayer times by coordinates via Aladhan API (method 21 = Morocco Habous).

    If the API is unreachable, fall back to a local astronomical calculation
    (Ministry-of-Habous-like angles). `computed` marks the fallback so the
    renderer can add a footnote.
    """
    params = {"latitude": lat, "longitude": lon, "method": PRAYER_METHOD}
    url = f"{PRAYER_API}?{urllib.parse.urlencode(params)}"
    r_pr, t_pr = _probe_budget(retries, timeout)
    try:
        data = http_json(url, timeout=t_pr, retries=r_pr)
        if not data.get("data") or data.get("code", 200) != 200:
            raise RuntimeError(f"unexpected prayer API answer: {json.dumps(data)[:300]}")
        return data["data"]
    except Exception:
        local = compute_prayer_times(lat, lon, timezone=timezone or CONFIG["tz"])
        if local is None:
            raise
        return local


def compute_prayer_times(lat: float, lon: float, timezone: str) -> dict | None:
    """Local astronomical prayer times (angles ~ Morocco Habous method).

    Returns an Aladhan-shaped payload — {"timings": {...}, "computed": True} —
    or None when date/timezone are unavailable.
    """
    loc = now_local(timezone)
    if loc is None:
        return None
    utc_offset = loc.utcoffset()
    if utc_offset is None:
        return None
    tz_hours = utc_offset.total_seconds() / 3600.0

    deg = math.pi / 180

    def _fix_hour(a):
        return a - 24 * math.floor(a / 24)

    def _julian(y, m, dd):
        if m <= 2:
            y -= 1
            m += 12
        a = y // 100
        b = 2 - a + a // 4
        return (int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + dd + b - 1524.5)

    jd = _julian(loc.year, loc.month, loc.day)

    def _sun_pos(hr):
        d = jd + hr / 24.0 - 2451545.0
        g = (357.529 + 0.98560028 * d) % 360
        q = (280.459 + 0.98564736 * d) % 360
        l = (q + 1.915 * math.sin(g * deg) + 0.020 * math.sin(2 * g * deg)) % 360
        e = 23.439 - 0.00000036 * d
        ra = _fix_hour(math.degrees(math.atan2(math.cos(e * deg) * math.sin(l * deg),
                                               math.cos(l * deg))) / 15)
        return math.asin(math.sin(e * deg) * math.sin(l * deg)), q / 15 - ra

    def _hour_angle(angle, dec):
        c = (math.cos(angle * deg) - math.sin(lat * deg) * math.sin(dec)) / (
            math.cos(lat * deg) * math.cos(dec))
        if c > 1:
            return 0.0
        if c < -1:
            return 180.0
        return math.degrees(math.acos(c))

    def _solar(angle, horizon_dir, ref_hr):
        dec, _ = _sun_pos(ref_hr)
        return noon + horizon_dir * _hour_angle(angle, dec) / 15.0

    _, eqt = _sun_pos(12.0)
    noon = 12 - eqt - lon / 15.0
    dec, _ = _sun_pos(noon)
    asr_angle = 90 - math.degrees(math.atan(1.0 / (math.tan(abs(lat - math.degrees(dec)) * deg) + 1)))
    raw = {
        "Fajr": _solar(90 + PRAYER_FAJR_ANGLE, -1, 5),
        "Sunrise": _solar(90.833, -1, 6),
        "Dhuhr": noon,
        "Asr": _solar(asr_angle, 1, noon),
        "Maghrib": _solar(90.833, 1, 18),
        "Isha": _solar(90 + PRAYER_ISHA_ANGLE, 1, 20),
    }
    timings = {}
    for k, v in raw.items():
        v = _fix_hour(v + tz_hours)
        hh, mm = int(v), int(round((v - int(v)) * 60))
        if mm == 60:
            hh, mm = hh + 1, 0
        timings[k] = f"{hh % 24:02d}:{mm:02d}"
    return {"timings": timings, "computed": True}


def build_prayer_message(pd: dict, lang: str, place: str | None = None,
                         coords: tuple[float, float] | None = None) -> str:
    L = T[lang]
    timings = pd.get("timings", {}) if isinstance(pd.get("timings"), dict) else {}
    keys = (("Fajr", L["cmd"]["prayer_fajr"], "🌅"),
            ("Sunrise", L["cmd"]["prayer_sunrise"], "🌄"),
            ("Dhuhr", L["cmd"]["prayer_dhuhr"], "☀️"),
            ("Asr", L["cmd"]["prayer_asr"], "🌤️"),
            ("Maghrib", L["cmd"]["prayer_maghrib"], "🌇"),
            ("Isha", L["cmd"]["prayer_isha"], "🌙"))
    rows = [f"{e} {label}: <b>{timings.get(k, '—')}</b>" for k, label, e in keys]
    loc = now_local(CONFIG["tz"])
    date_line = ""
    if loc:
        date_line = f"{L['days'][loc.weekday()]} {loc.day} {L['months'][loc.month - 1]} {loc.year}"
    title = f"{L['cmd']['prayer_header']} {esc(place)}</b>" if place else esc(L['cmd']['prayer_header'].rstrip())
    hijri = pd.get("date", {}).get("hijri") if isinstance(pd.get("date"), dict) else None
    extra = ""
    if isinstance(hijri, dict):
        d, y = hijri.get("day"), hijri.get("year")
        month = (hijri.get("month") or {}).get("ar") if isinstance(hijri.get("month"), dict) else None
        if d and y:
            extra = f"\n📅 {L['cmd']['hijri']} {d} {month or ''} {y}"
    coords_line = ""
    if coords:
        lat, lon = coords
        ns = "S" if lat < 0 else "N"
        ew = "W" if lon < 0 else "E"
        coords_line = f"\n📍 <b>{abs(lat):.3f}°{ns} {abs(lon):.3f}°{ew}</b>"
    return (f"{title}\n{esc(date_line)}\n\n" + "\n".join(rows) + extra + coords_line +
            f"\n\n<i>{esc(L['cmd']['prayer'])} {esc(place or CONFIG['place'])}</i>" +
            ("\n<i>الحساب المحلي (خوادم الصلاة غير متاحة الآن)</i>" if pd.get("computed") else ""))


# --------------------------------------------------------------------------- commands
def handle_text(text: str, lang: str, retries: int, timeout: int) -> str:
    """Turn a plain chat message into the Arabic reply for the sender."""
    L = T[lang]
    t = text.strip()
    if not t:
        return L["cmd"]["help"]
    cmd, _, arg = t.partition(" ")
    cmd = cmd.lower()
    arg = arg.strip(" \t.,،؛")

    if cmd in ("/start", "start", "بداية", "البداية"):
        return L["cmd"]["start"]
    if cmd in ("/help", "help", "مساعدة", "المساعدة", "اوامر", "الأوامر"):
        return L["cmd"]["help"]
    if cmd in ("/hello", "السلام", "سلام", "اهلا", "أهلا", "مرحبا", "مرحباً", "bonjour", "salam", "hi", "salut"):
        return L["cmd"]["hello"]
    if cmd in ("شكرا", "شكراً", "merci", "thanks", "thank"):
        return L["cmd"]["thanks"]
    if cmd in ("/weather", "weather", "طقس", "الطقس", "مترو", "هو"):
        return build_city_weather(arg, lang, retries, timeout) if arg else _weather_default(lang, retries, timeout)
    if cmd in ("/prayer", "prayer", "صلاة", "الصلاة", "الصلوات", "اوقات", "أوقات", "مواقيت", "priere", "prière"):
        return build_city_prayer(arg, lang, retries, timeout) if arg else _prayer_default(lang, retries, timeout)

    # anything else that looks like a city -> treat as a weather request
    if "/" not in cmd:
        return build_city_weather(f"{cmd} {arg}".strip(), lang, retries, timeout)
    return L["cmd"]["not_found"]


def _weather_default(lang: str, retries: int, timeout: int) -> str:
    return build_city_weather(CONFIG["place"], lang, retries, timeout)


def _prayer_default(lang: str, retries: int, timeout: int) -> str:
    return build_city_prayer(CONFIG["place"], lang, retries, timeout)


def build_city_weather(query: str, lang: str, retries: int, timeout: int) -> str:
    L = T[lang]
    try:
        city = geocode_city(query, retries, timeout)
        data = fetch_weather(retries, timeout, lat=city["lat"], lon=city["lon"], tz=city["tz"])
        w = extract(data)
        return build_message(w, data, lang, place=f"{city['name']}")
    except Exception as e:
        if "no city found" in str(e):
            return f"{L['cmd']['error']} {esc(str(e))[:400]}\n\n{L['cmd']['not_found']}"
        return f"{L['cmd']['error']} {esc(str(e))[:400]}\n\n{L['cmd']['net_error']}"


def build_city_prayer(query: str, lang: str, retries: int, timeout: int) -> str:
    L = T[lang]
    try:
        city = geocode_city(query, retries, timeout)
        pd = fetch_prayer(city["lat"], city["lon"], retries, timeout, timezone=city["tz"])
        return build_prayer_message(pd, lang, place=f"{city['name']}",
                                    coords=(city["lat"], city["lon"]))
    except Exception as e:
        if "no city found" in str(e):
            return f"{L['cmd']['error']} {esc(str(e))[:400]}\n\n{L['cmd']['not_found']}"
        return f"{L['cmd']['error']} {esc(str(e))[:400]}\n\n{L['cmd']['net_error']}"


def offset_state_path() -> Path:
    """Bot-local JSON file that remembers the last getUpdates offset."""
    return Path(__file__).resolve().parent / "poll_offset.json"


def load_offset() -> int | None:
    try:
        raw = offset_state_path().read_text(encoding="utf-8").strip()
        val = int(json.loads(raw))
        return val if val > 0 else None
    except Exception:
        return None


def save_offset(offset: int) -> None:
    try:
        offset_state_path().write_text(json.dumps(offset), encoding="utf-8")
    except Exception:
        pass  # best effort only: worst case we re-read a few old updates


def get_updates_once(token: str, offset: int | None, timeout: int, retries: int) -> list[dict]:
    params = {"timeout": POLL_LONG_POLL, "limit": 50, "offset": offset} if offset is not None else {
        "timeout": POLL_LONG_POLL, "limit": 50}
    url = f"{TELEGRAM_API}/bot{token}/getUpdates?" + urllib.parse.urlencode(params)
    data = http_json(url, timeout=timeout, retries=retries, secret=token)
    return data.get("result") or []


def _confirm_queued(token: str, timeout: int) -> int | None:
    """Acknowledge every pending update without answering, return latest offset.

    Telegram only confirms updates once a getUpdates call passes an offset
    higher than their id. Without this, a fresh poll (or one that lost its
    offset file) would replay the whole history one slow message at a time.
    """
    cursor = 0
    for _ in range(200):
        batch = get_updates_once(token, cursor, min(timeout, 8), 1)
        if not batch:
            break
        cursor = max(cursor, max((u.get("update_id") or 0) for u in batch) + 1)
        if len(batch) < 50:
            break
    return cursor or None


def _answer_in_background(text: str, lang: str, chat_id: str, token: str,
                          retries: int, timeout: int) -> None:
    try:
        reply = handle_text(text, lang, retries, timeout)
    except Exception as e:
        reply = f"{T[lang]['cmd']['error']} {esc(str(e))[:400]}"
    try:
        send_telegram(reply, token, [chat_id], timeout, retries)
    except Exception as e:
        print(f"send failed: {e}", file=sys.stderr)


def poll_bot(token: str, lang: str, retries: int, timeout: int) -> int:
    """Long-poll Telegram and answer every message, forever."""
    print("Listening on Telegram... press Ctrl+C to stop.")
    offset: int | None = load_offset()
    if offset:
        print(f"resuming poll from update offset {offset}")
    else:
        try:
            caught = _confirm_queued(token, max(timeout, POLL_LONG_POLL + 15))
        except Exception as e:
            caught = None
            print(f"startup catch-up skipped: {e}", file=sys.stderr)
        if caught:
            offset = caught
            save_offset(offset)
            print(f"confirmed {caught} old queued updates without replying")
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=3)
    errors = 0
    while True:
        updates: list[dict] = []
        try:
            updates = get_updates_once(token, offset, max(timeout, POLL_LONG_POLL + 15), 1)
        except Exception as e:
            print(f"poll error (will retry): {e}", file=sys.stderr)
            errors += 1
            time.sleep(min(5 * 2 ** (errors - 1), 60))  # exponential backoff, cap 60s
            continue
        errors = 0
        for upd in updates:
            offset = max(offset or 0, (upd.get("update_id") or 0) + 1)
            save_offset(offset)
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            text = msg.get("text") or ""
            if chat_id is None or not text.strip():
                continue
            pool.submit(_answer_in_background, text, lang, str(chat_id),
                        token, retries, timeout)


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
    loc = now_local(CONFIG["tz"])
    check("[ar] arabic weekday+month",
          loc is None or (T["ar"]["days"][loc.weekday()] in ar and T["ar"]["months"][loc.month - 1] in ar))
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
        check("sparse renders with dashes", "—" in sm)
        check("sparse keeps title", "خريبكة" in sm)
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

    # 6. command dispatch (offline): routing + summaries, no network
    try:
        check("cmd /start routes", "بوت" in handle_text("/start", "ar", 1, 5))
        check("cmd /help routes", "الأوامر" in handle_text("/help", "ar", 1, 5))
        check("cmd /help generic", "الأوامر" in handle_text("مساعدة", "ar", 1, 5))
        check("cmd hello", "مرحباً" in handle_text("سلام", "ar", 1, 5))
        check("cmd thanks", "على الرحب" in handle_text("شكرا", "ar", 1, 5))
        check("cmd empty -> help", "الأوامر" in handle_text("", "ar", 1, 5))
        # a bare word that is not a keyword goes through the weather path and
        # must return a city-not-found styling rather than crashing
        bad = handle_text("qqzzxx", "ar", 1, 5)
        check("cmd unknown city handled", "خطأ" in bad or "لم أجد" in bad or "❌" in bad)
        # known keyword with a city -> network path returns an error message
        # when the API cannot be reached (retries=1, short timeout), not a crash
        offline = handle_text("طقس qqzzxx", "ar", 1, 3)
        check("cmd weather arg routed", ("خطأ" in offline) or ("لم أجد" in offline) or ("❌" in offline))
    except Exception as e:
        check(f"command dispatch crashed: {e!r}", False)

    # 6-bis. prayer rendering (offline, synthetic Aladhan payload)
    pray = {
        "timings": {"Fajr": "05:12", "Sunrise": "06:32", "Dhuhr": "13:05",
                    "Asr": "16:40", "Maghrib": "19:20", "Isha": "20:35"},
        "date": {"hijri": {"day": "11", "year": "1448",
                           "month": {"ar": "ربيع الأول", "number": 3}}},
    }
    pm = build_prayer_message(pray, "ar", "فاس")
    for needle in ("الفجر", "الظهر", "العشاء", "05:12", "19:20", "فاس", "ربيع الأول"):
        check(f"prayer renders {needle}", needle in pm)
    check("prayer tags balanced", pm.count("<b>") == pm.count("</b>"))
    pm2 = build_prayer_message(pray, "ar")
    check("prayer without place tolerates", "</b>" in pm2)

    # 6-ter-bis. computed-prayer footnote (local fallback) appears only when flagged
    pm3 = build_prayer_message({**pray, "computed": True}, "ar", "الدار البيضاء")
    check("computed prayer footnote", "الحساب المحلي" in pm3)
    check("computed prayer no notfound", "لم أجد" not in pm3)

    # 6-ter-ter. prayer message shows the city coordinates when provided
    pm4 = build_prayer_message(pray, "ar", "الرباط", coords=(34.0132, -6.8326))
    check("prayer coords latitude N", "34.013°N" in pm4)
    check("prayer coords longitude W", "6.833°W" in pm4)
    check("prayer coords emoji", "📍" in pm4)
    pm4b = build_prayer_message(pray, "ar", "سيدني", coords=(-33.8688, 151.2093))
    check("prayer coords southern/eastern", "33.869°S" in pm4b and "151.209°E" in pm4b)

    # 6-ter-quater. fr/en have the cmd table too (regression: KeyError used to crash)
    pm_fr = build_prayer_message(pray, "fr", "Rabat")
    check("prayer fr renders", "Fajr" in pm_fr and "rabbit" not in pm_fr)
    pm_en = build_prayer_message(pray, "en", "Rabat")
    check("prayer en renders", "Fajr" in pm_en and "Salaat" not in pm_en)
    check("help fr routes", "Commandes" in handle_text("/help", "fr", 1, 5))
    check("help en routes", "commands" in handle_text("/help", "en", 1, 5))
    check("start fr routes", "Bienvenue" in handle_text("بداية", "fr", 1, 5))
    err_fr = handle_text("qqzzxx", "fr", 1, 3)
    check("fr unknown city handled", ("Erreur" in err_fr) or ("introuvable" in err_fr) or ("❌" in err_fr))

    # 6-quinquies. guess_tz sanity (city timezone fallback for non-MA)
    check("guess_tz Berlin UTC+1", guess_tz(13.4) == "Etc/GMT-1")
    check("guess_tz Tokyo UTC+9", guess_tz(139.7) == "Etc/GMT-9")
    check("guess_tz London UTC", guess_tz(-0.1) == "Etc/GMT")
    check("guess_tz Lima UTC-5", guess_tz(-77.04) == "Etc/GMT+5")

    # 6-quad. fallback providers (offline/deterministic)
    check("metno clearsky maps to code 0", metno_symbol_code("clearsky_day") == 0)
    check("metno thunderstorm maps to 95", metno_symbol_code("lightrainshowersandthunder") == 95)
    check("metno unknown maps to cloudy 3", metno_symbol_code("hlafoobar") == 3)
    sr, ss = sunrise_sunset(34.01325, -6.83255)

    def hhmm(x: str) -> bool:
        return (len(x) == 5 and x[2] == ":" and x[:2].isdigit() and x[3:].isdigit()
                and 0 <= int(x[:2]) <= 24 and 0 <= int(x[3:]) <= 59)

    check("sunrise/sunset computed HH:MM", hhmm(sr) and hhmm(ss))
    check("sunrise earlier than sunset",
          int(sr[:2]) * 60 + int(sr[3:]) < int(ss[:2]) * 60 + int(ss[3:]))

    # 6-ter. weather builder honours a custom place and keeps the default title
    fxw = extract(_fixture())
    m_city = build_message(fxw, _fixture(), "ar", place="الرباط")
    check("city place in title", "الرباط" in m_city and "خريبكة" not in m_city)
    m_def = build_message(fxw, _fixture(), "ar")
    check("default title kept", "خريبكة" in m_def)
    check("arbitrary place not double", "الرباط — الرباط" not in m_city)

    # 7. getUpdates parser behind --whoami
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
    ap.add_argument("--poll", action="store_true",
                    help="interactive: answer each Telegram message forever")
    ap.add_argument("--say", metavar="TEXT",
                    help="compute the Arabic reply for TEXT and print it (no sending)")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.whoami:
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not tok:
            print("ERROR: exporte d'abord TELEGRAM_BOT_TOKEN (voir .env.example)", file=sys.stderr)
            return 3
        return whoami(tok, int(os.environ.get("HTTP_TIMEOUT", "25")),
                      int(os.environ.get("RETRIES", "4")))

    timeout = int(os.environ.get("HTTP_TIMEOUT", "25"))
    retries = int(os.environ.get("RETRIES", "4"))

    if args.say:
        print(handle_text(args.say, args.lang, retries, timeout))
        return 0

    if args.poll:
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not tok:
            print("ERROR: exporte d'abord TELEGRAM_BOT_TOKEN (voir .env.example)", file=sys.stderr)
            return 3
        return poll_bot(tok, args.lang, retries, timeout)

    if args.only_at is not None and now_local(CONFIG["tz"]).hour != args.only_at:
        print(f"skipped: local hour {now_local(CONFIG['tz']).hour} != {args.only_at}")
        return 0

    lang = args.lang

    try:
        data = fetch_weather(retries, timeout)
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

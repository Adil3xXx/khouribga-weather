# نشرة طقس خريبكة اليومية على تيليجرام 🇲🇦

سكريبت واحد بلا مكتبات خارجية، يجيب طقس **اليوم** لمدينة **خريبكة** (32.881°N، 6.906°W)
ويرسله على تيليجرام كل يوم على الساعة **7:00 صباحًا** بتوقيت المغرب، باللغة العربية.

**ليش النشرة "موثوقة"؟** الأرقام الأساسية (العظمى والتساقطات) تُحسب من **تقاطع ثلاثة نماذج**
— `best_match` + **ECMWF-IFS 0.25°** + **GFS** — وكل نشرة تحمل سطر ثقة:

| السطر | معناه |
|---|---|
| ✅ توقع متين — النماذج متفقة | الفرق بين النماذج ≤ 0.8° و≤ 0.5 ملم |
| 🟡 ثقة جيدة — فارق بسيط | الفرق ≤ 1.8° |
| 🟠 تفاوت بين النماذج | فرق > 1.8° ⇒ تابع تحديث النهار |

> ⚠️ لا يوجد نموذج "صحيح 100%". هاد المشروع كيقرّب الاحتمال وكيوريك قدّاش النماذج متّفقة،
> وكلشي مصدره Open-Meteo (بلا مفتاح API) — ماشي مصدر رسمي من المديرية الوطنية للأرصاد.

---

## 1) جرّبها فورا (بلا حساب تيليجرام)

```bash
cd khouribga-weather-bot
python3 weather_bot.py --selftest     # 109 فحص بلا أنترنت
python3 weather_bot.py --dry-run      # يطبع النشرة الحقيقية بلا ما يبعت والو
```

## 2) صاوب البوت ديالك (3 دقايق)

1. في تيليجرام فتّح [@BotFather](https://t.me/BotFather) → `/newbot` → سمّي البوت → خدّي **التوكن**.
2. صيفط `/start` للبوت ديالك (باش يسمحو ليه يبعت ليك).
3. افتح `https://api.telegram.org/bot<التوكن>/getUpdates` وخذ `chat.id` (رقم بحال `123456789`).
   - **لقناة**: زيد البوت **مشرف** فالقناة واستعمل `@channel_username` بدل الرقم.
   - **لمجموعة**: زيد البوت للمجموعة، والـ `chat.id` يكون سالب (`-100xxxxxxxxxx`).
4. `cp .env.example .env && chmod 600 .env` واملأ `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID`.
5. اختبار البعت الحقيقي: `python3 weather_bot.py --send`

> 🔒 التوكن بحال باسورد. حطّو غير فـ `.env` (ممنوع من git، شوف `.gitignore`) ولا فـ Secrets،
> وما تديروش فشي صورة عامة. إلا تسرّب: `/revoke` عند BotFather وكافي.

## 2-bis) كيفاش تجب الـ chat ID — Récupérer ton chat ID

**الأسرع / Le plus rapide — laisse le script le trouver :**
```bash
TELEGRAM_BOT_TOKEN="123:AA..." python3 weather_bot.py --whoami
```
كيطلع جدول فيه كل المحادثات اللي البوت كيشوفها (الخاصة، الزمر، القنوات). من بعد حطّ الرقم فـ `TELEGRAM_CHAT_ID`.
(ماتنساش صفيط `/start` للبوت **قبل**، إلا الجدول طاع خاوي.)

**الطريقة 2 — عبر المتصفح (بلا أي أداة):**
1. صفيط `/start` للبوت ديالك فـ Telegram.
2. فتّح `https://api.telegram.org/bot<TOKEN>/getUpdates` فمتصفح.
3. فـ JSON قلّب على `"chat":{"id":123456789,...}` → هادا هو الـ chat ID ديالك.

```bash
# نفس الحاجة فـ terminal (كيخفي التوكن من الـ history إلا حطيتو مسبقا فـ env)
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates" | jq '.result[].message.chat'
```

**الطريقة 3 — بوت مساعد** (إلا ما بغيتيش تلمس التوكن): صفيط `/start` لـ @userinfobot
ولا @getmyid_bot، كيرجعوك رقمك (محادثة خاصة = رقم موجب، زمرة/قناة = كيبدا بـ `-100`).

| نوع المحادثة | شكل الـ chat_id | ملاحظة |
|---|---|---|
| خاص (privé) | `123456789` | خاصك تصيفط `/start` للبوت |
| زمرة / groupe | `-1001234567890` | زيد البوت للزمرة (ماكيكفيش تكون فـ list) |
| قناة / canal | `-1001554433221` ولا `@nom_channel` | زيد البوت **مشرفًا** مع حق النشر |

> إلا `getUpdates` رجع `[]` خاوي: كاين **webhook** نشّط عليه (الحل: `.../deleteWebhook`)،
> ولا البوت ما شافش رسالة منك. إلا رجع `403 Forbidden: bot can't initiate` → ما صفيطيش `/start`.

## 3) جدولة كل يوم — اختار طريقة وحدة

### أ) GitHub Actions (مجان، بلا سيرفر — مُوصى به)
ارفع محتوى هاد المجلد **فجذر repo** (باش `weather_bot.py` يكون فـ root)، فعّل
**Actions → General → Workflow permissions: Read-only**، ومن بعد:

```bash
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh workflow run daily-weather.yml          # اختبار يدوي
```

`daily-weather.yml` كيخدم **كل ساعة** ولكن السكربت كيبعت غير ملي تكون **7:00 بخريبكة**
(`--only-at 7`). هكا حتى **توقيف التوقيت الصيفي فالمغرب (أسابيع رمضان)** ما كيخربش وقت الإرسال.
التكلفة: ~8 دقائق تنفيذ فالشهر.

### ب) Linux / VPS — cron ولا systemd
```bash
./install.sh                    # كينسخ فـ ~/khouribga-weather-bot وكيدير cron على 7:00
tail -f ~/khouribga-weather-bot/weather.log
```
أو systemd (أفضل: كيعاود إلا طلع السيرفر خارج التوقيت):
```bash
sudo mkdir -p /opt/khouribga-weather-bot && sudo cp weather_bot.py .env /opt/khouribga-weather-bot/
sudo cp khouribga-weather.service khouribga-weather.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now khouribga-weather.timer
systemctl list-timers khouribga-weather.timer
```

### ج) Windows
```bat
schtasks /Create /TN "KhouribgaWeather" /SC DAILY /ST 07:00 ^
 /TR "py C:\khouribga-weather-bot\weather_bot.py --send" /F
```

### د) Mac (launchd)
`~/Library/LaunchAgents/com.khouribga.weather.plist` بـ `StartCalendarInterval` = 7h، ولا cron.

## 4) الأوامر كاملة

| الأمر | الوظيفة |
|---|---|
| `--send` | يجيب الطقس ويبعت على تيليجرام |
| `--dry-run` | يطبع بلا بعت (آمن) |
| `--whoami` | كيطلع الـ chat ID اللي البوت كيشوف (من بعد `/start`) |
| `--send --only-at 7` | يبعت غير فـ 7:00 المحلي (للـ cron اللي كيخدم كل ساعة) |
| `--selftest` | فحوصات بلا أنترنت على معطيات وهمية |
| `--lang fr\|en\|ar` | تغيير اللغة |
| `--debug` | يطبع JSON الخام ديال API |
| `--poll` | **الوضع التفاعلي**: كيجاوب على كل رسالة فـ تيليجرام (الطقس + الصلاة) |
| `--say "طقس الرباط"` | كيجرّب جواب رسالة فآحدة بالعربية بلا ما يبعت (اختبار) |

الخروج: `0` نجاح/تخطّي · `2` فشل API · `3` نقص توكن · `4` فشل تيليجرام.
عند فشل الجلب، النشرة كتبدّل برسالة تنبيه على تيليجرام (إلا كان التوكن موجود) باش **ما يعطّلّكش
الصباح بلا ما تعرف**. `RETRIES=4` مع تراجع أُسّي، و429 كيتعامل معاه بـ `retry_after`.

### أوامر المحادثة (لما `--poll` كيخدم)

| اللي كتبعته للبوت | الجواب |
|---|---|
| `طقس <مدينة>` أو `/طقس <مدينة>` | نشرة الطقس اليومية للمدينة (عربي) |
| `صلاة <مدينة>` أو `/prayer <مدينة>` | أوقات الصلوات الخمس للمدينة (طريقة الأوقاف المغربية) |
| `/start` | رسالة الترحيب |
| `/help` | كل الأوامر |
| أي اسم مدينة وحدو (مثلا `الرباط`) | نشرة الطقس ديالها |

الطقس: Open-Meteo (تقاطع ECMWF/GFS مثل النشرة اليومية). الصلاة: Aladhan API بطريقة
وزارة الأوقاف المغربية (method 15). بلا مفاتيح، بلا تبعيات إضافية. الأولوية للمدن المغربية
(كود MA) ثم المطابقة العامة.

**الموثوقية عند انقطاع الخوادم:** عند فشل Open-Meteo/Aladhan كيتبدل المصدر
أوتوماتيكيًا بلا تدخل:

| المصدر الرئيسي | البديل عندما يتعطّل |
|---|---|
| الجغرافيا: Open-Meteo Geocoding | Nominatim (OpenStreetMap) |
| الطقس: Open-Meteo (ECMWF·GFS) | met.no (للطقس اليوم) |
| الصلاة: Aladhan API | حساب فلكي محلي بزوايا الأوقاف (18°/17°) مع سطر «الحساب المحلي» |

💡 النشرة من met.no كتبيّن «المصدر: met.no» وبدون سطر تقاطع النماذج، وأوقات الصلاة المحلية
كيصحبها سطر «الحساب المحلي». كي ما كان أحد المصدرين محجوب (أو بطيئ) الجواب كيوصل فبضع ثوان.

## 5) بدّل المدينة /زيد إشعارات
غيّر `WEATHER_LAT` و `WEATHER_LON` فـ `.env` (مثلا بني ملال: `32.3373`, `-6.3470`).
لإشعار حرارة إضافية فـ `.env.example` ما كاينش — زيد سطر فـ `advices()` فـ `weather_bot.py`
(مثلا `if tmax >= 45: out.append("حرارة قصوى")`) — ولا قوليها وكيديرها ليك.

## 6) مشاكل شائعة

| العرض | الحل |
|---|---|
| `HTTP 401 Unauthorized` | توكن غالط ولا محطوط `/revoke` |
| `403 Forbidden: bot was kicked` | طاح البوت من المحادثة/القناة |
| `400 chat not found` | `chat_id` غالط ولا ما صيفطتيش `/start` للبوت |
| `429` | تيليجرام كيمنع الإغراق — كيتعاود أوتوماتيكيا |
| ما وصل والو من GitHub | شوف Actions logs؛ غالباً secret ناقص ولا repo خاص بـ minutes=0 |
| وصلات على 6:00 لا 7:00 | نظامك فـ UTC؛ استعمل `--only-at` ولا `TZ=` |

## الملفات
```
weather_bot.py              السكربت (Python 3.9+، مكتبات معيارية فقط)
.env.example                قالب الإعدادات  →  انسخه لـ .env
install.sh                  تنصيب + cron على لينكس
.github/workflows/daily-weather.yml   الجدولة المجانية على GitHub
khouribga-weather.{service,timer}    بديل systemd
preview.txt                 شكل النشرة كما ستصل
```

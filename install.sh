#!/usr/bin/env bash
# تنصيب على سيرفر/PC بلينكس: ينسخ الملفات ويعرّف مهمة cron كل يوم على 7:00
set -euo pipefail
APP_DIR="${APP_DIR:-$HOME/khouribga-weather-bot}"
HOUR="${HOUR:-7}"
MARKER="# khouribga-weather-daily"

mkdir -p "$APP_DIR"
cp "$(dirname "$0")/weather_bot.py" "$APP_DIR/"
[ -f "$APP_DIR/.env" ] || { cp "$(dirname "$0")/.env.example" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"; }
chmod 700 "$APP_DIR/.env"
PY="$(command -v python3)"
"$PY" -m pip install --quiet -r "$(dirname "$0")/requirements.txt" 2>/dev/null || true
"$PY" "$APP_DIR/weather_bot.py" --selftest

( crontab -l 2>/dev/null | grep -v "$MARKER" ; \
  echo "0 $HOUR * * * cd $APP_DIR && $PY weather_bot.py --send >> $APP_DIR/weather.log 2>&1 $MARKER" ) | crontab -

echo
echo "Done. Next: edit $APP_DIR/.env (token + chat id), then test with:"
echo "  cd $APP_DIR && python3 weather_bot.py --send"
echo "Note: cron uses the SYSTEM clock. If this server is on UTC (not Casablanca time),"
echo "use hourly scheduling with the built-in local-time guard instead:"
echo "  ( crontab -l | grep -v guard ; echo '* * * * * cd $APP_DIR && $PY weather_bot.py --send --only-at $HOUR >> $APP_DIR/weather.log 2>&1 # guard' ) | crontab -"

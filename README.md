# Polymarket Bot

## 1) Depoyu indir
```bash
git clone <REPO_URL>
cd Polymarket_Bot
```

## 2) Sanal ortam oluştur + aktif et
```bash
python3 -m venv venv
source venv/bin/activate
```
(Windows için: venv\Scripts\activate)
Bu adım README’de önerilen standart kurulum akışıdır. (Ref: polymarket_bot_py/README.md)

## 3) Gereksinimleri yükle
```bash
pip install -r requirements.txt
pip install -r polymarket_bot_py/requirements.txt
```
Projede hem ana dizinde hem de polymarket_bot_py/ altında ayrı requirements bulunuyor; ikisini de kurmak en güvenlisi. (Ref: requirements.txt, polymarket_bot_py/requirements.txt)


## 4) Playwright tarayıcılarını kur
```bash
playwright install
```
Bot Playwright kullandığı için tarayıcı kurulumunu zorunlu. (Ref: polymarket_bot_py/README.md)

## 5) .env dosyasını oluştur
```bash
cp polymarket_bot_py/.env.example polymarket_bot_py/.env
```
Sonra .env içini ihtiyacına göre güncelle:
Free modda sadece giriş için Chrome açılacaksa HEADLESS=false önerilir.
Trade mod için DRY_RUN=false yaparak gerçek işlem açtırabilirsin.
(Ref: polymarket_bot_py/.env.example, polymarket_bot_py/README.md)

# 🚀 Çalıştırma Komutları
## ✅ Free Mod (Chrome aç ve açık kalsın)
```bash
python -m polymarket_bot_py.bot.main --mode free
```
Chrome açılır, sen manuel giriş yaparsın. Bot Chrome’u kapatmaz.
(Ref: polymarket_bot_py/README.md)

## ✅ Trade Mod (events.ndjson okuyup otomatik trade)
```bash
python -m polymarket_bot_py.bot.main --mode trade
```
track_polymarket_activity.py arka planda çalışır, events.ndjson dosyasını günceller ve bot her dakika en üst event ile trade yapar.
(Ref: polymarket_bot_py/README.md)

## ✅ Standart Scheduler Mod (15 dakikada bir çalışır)
```bash
python -m polymarket_bot_py.bot.main
```
(Ref: polymarket_bot_py/README.md)
⚠️ Notlar
Chrome’u bot asla kapatmaz (AUTO_CLOSE_BROWSER=false varsayılan).
Kapatmak istersen terminalden Ctrl+C ile durdurabilirsin.
(Ref: polymarket_bot_py/README.md)

# Polymarket Playwright Bot

Polymarket web UI üzerinde çalışan, tarayıcı tabanlı otomasyon botu. Persisten kullanıcı profili ile giriş bilgileri saklanır, her 15 dakikada bir tek deneme yapar ve fiyat farkı eşiğini aşarsa kendini duraklatır.

## Kurulum (Mac / Node 20+)
1. Node 20 kullanın (`nvm use 20`).
2. Depoyu klonlayın ve klasöre girin.
3. Bağımlılıkları yükleyin:
   ```bash
   npm install
   npx playwright install
   ```
4. Ortam değişkenlerini ayarlamak için `.env` dosyasını `.env.example` üzerinden oluşturun.

## Yapı
```
.
├─ src/
│  ├─ config.ts       # .env okuma ve config
│  ├─ selectors.ts    # UI locator tanımları
│  ├─ utils.ts        # yardımcı fonksiyonlar (log, parsePrice vb.)
│  ├─ state.ts        # duraklatma ve run-key durumu
│  ├─ bot.ts          # tek çalıştırma akışı
│  └─ index.ts        # zamanlama döngüsü
├─ storage/           # Playwright persistent profil
├─ runs/              # log, screenshot, trace çıktıları
├─ .env.example
└─ README.md
```

## Ortam değişkenleri
`.env` dosyasında desteklenen alanlar:

```
MARKET_URL=https://polymarket.com/event/bitcoin-up-or-down
SIDE=UP            # veya DOWN
LIMIT_PRICE=0.98
SHARES=10
DIFF_THRESHOLD_USD=100
PAUSE_MINUTES=60
HEADLESS=false
TIMEZONE=Europe/Istanbul
```

## Çalıştırma
```
npm run dev
```
- `storage/profile` persistent context ile açılır; ilk çalıştırmada Polymarket girişini manuel yapın.
- Bot her 5 saniyede bir zamanı kontrol eder; dakikalar 00/15/30/45 olduğunda ve aynı pencere içinde daha önce çalışmadıysa deneme yapar.

## Güvenlik ve davranış
- “PRICE TO BEAT” ve “CURRENT PRICE” UI’dan okunur, sayı parse edilemezse veya selector bulunamazsa işlem yapılmaz (fail-closed).
- `|current - beat|` `DIFF_THRESHOLD_USD` değerini aşarsa `PAUSE_MINUTES` kadar duraklar, screenshot ve trace kaydedilir.
- Hata durumunda trace ve ekran görüntüsü `runs/` klasörüne yazılır.

## Playwright codegen (kayıt)
UI değişikliklerini görmek veya yeni selector çıkarmak için:
```
# Mevcut profili yükleyerek
npx playwright codegen --load-storage=storage/profile.json <MARKET_URL>
# veya persistent profil diziniyle
npx playwright codegen --user-data-dir=storage/profile <MARKET_URL>
```

## Notlar
- MetaMask otomasyonu yoktur; Polymarket iç bakiyesini kullanır.
- Limit price, shares ve side değerleri sabittir; karar verme yapılmaz.

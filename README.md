# Polymarket Copytrader (Paper Trading)

Bu repo, Polymarket üzerinde belirli bir wallet'ın trade aktivitelerini dinleyip, belirlenen multiplier ile ölçekleyerek paper-trade kopyasını yapan bir sistem sağlar. Websocket öncelikli, HTTP polling fallback'li, event normalizasyonlu ve Streamlit dashboard'lu bir mimari içerir.

## Mimari (kısa)

- **sources/**: Websocket ve HTTP polling aktivitelerini okuyan kaynaklar.
- **engine/**: Normalizasyon, risk kontrolleri, slippage, paper-trade execution ve copy engine.
- **storage/**: event dedup state ve NDJSON loglama.
- **dashboard.py**: Streamlit dashboard.
- **app.py**: CLI entrypoint, orchestration.

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r polymarket_copytrader/requirements.txt
```

## Çalıştırma

Websocket (öncelikli):

```bash
python polymarket_copytrader/app.py \
  --wallet 0xYourWallet \
  --multiplier 0.1 \
  --ws_url wss://your-polymarket-ws-url \
  --events_ndjson \
  --trades_ndjson \
  --dashboard
```

HTTP fallback:

```bash
python polymarket_copytrader/app.py \
  --wallet 0xYourWallet \
  --multiplier 0.1 \
  --http_url https://your-polymarket-http-endpoint \
  --poll_interval 2.5 \
  --dashboard
```

## Dashboard

Streamlit otomatik başlatılır (`--dashboard`). Dashboard `output/dashboard_state.json` dosyasını okuyarak canlı KPI ve işlem listesi gösterir.

## Çıktılar

- `output/state.json`: event dedup seti.
- `output/events.ndjson`: canonical event log (opsiyonel).
- `output/trades.ndjson`: paper trades log (opsiyonel).
- `output/report.md`: session raporu.

## Notlar

- Event normalizasyonu robust olacak şekilde tasarlanmıştır; farklı şemalarda gelen verileri canonical modele çevirir.
- Uygun risk kontrolleri (max position, notional, cooldown) eklenmiştir.
- Real trading'e genişletilebilmesi için copy engine ayrıştırılmıştır.

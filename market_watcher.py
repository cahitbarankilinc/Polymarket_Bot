import asyncio
import json
import websockets
import sys
import re
from datetime import datetime, timezone
from dateutil import parser
from discovery import find_active_window

# ----------------------------
# Configuration
# ----------------------------
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

class MarketWatcher:
    def __init__(self, market_data):
        self.ids = {"YES": market_data['yes_id'], "NO": market_data['no_id']}
        self.end_time = parser.isoparse(market_data['end_time'])
        self.title = market_data['title']
        self.condition_id = market_data['condition_id']  # <--- THE MARKET ID
        
        # Store only prices, no positions
        self.prices = {"YES": 0.0, "NO": 0.0}
        
        print(f"\n👀 WATCHING: {self.title}")
        print(f"   Ends at:   {market_data['end_time']}")
        print(f"   Market ID: {self.condition_id}")  # <--- PRINT IT HERE
        print(f"   YES Token: {self.ids['YES']}")
        print(f"   NO Token:  {self.ids['NO']}")
        print("-" * 60)

    def get_time_remaining(self):
        now = datetime.now(timezone.utc)
        return (self.end_time - now).total_seconds()

    def refresh_display(self):
        time_rem = int(self.get_time_remaining())
        
        # Format prices nicely (e.g., "45¢")
        y_price = int(self.prices["YES"] * 100)
        n_price = int(self.prices["NO"] * 100)
        
        # Carriage return (\r) overwrites the line
        status = (
            f"\r⏱️ T-{time_rem}s | "
            f"YES: {y_price}¢ | "
            f"NO: {n_price}¢      " 
        )
        sys.stdout.write(status)
        sys.stdout.flush()

    def update_price(self, asset_id, price):
        if price == 0: return
        
        # Map Asset ID to "YES" or "NO" side
        if asset_id == self.ids["YES"]:
            self.prices["YES"] = price
        elif asset_id == self.ids["NO"]:
            self.prices["NO"] = price
            
        self.refresh_display()

# ----------------------------
# Main Loop (The Daemon)
# ----------------------------
async def main_loop():
    while True:
        print("\n🔍 Scanning for active market...")
        market = await find_active_window()
        
        if not market:
            print("💤 No active market found. Retrying in 30s...")
            await asyncio.sleep(30)
            continue

        # Pass the entire market object to the watcher
        watcher = MarketWatcher(market)
        
        try:
            async with websockets.connect(WS_URL) as ws:
                # Subscribe to Level 1 Data (Best Bid/Ask)
                sub_msg = {"assets_ids": [market['yes_id'], market['no_id']], "type": "level1"}
                await ws.send(json.dumps(sub_msg))
                
                while True:
                    # Check if market expired
                    if watcher.get_time_remaining() <= 0:
                        print("\n🏁 MARKET CLOSED. Rotating...")
                        break

                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=10)
                        data = json.loads(msg)
                        
                        # Handle list of updates (Standard Polymarket format)
                        if isinstance(data, list):
                            for item in data:
                                process_item(item, watcher)
                        # Handle single update object
                        elif isinstance(data, dict):
                            process_item(data, watcher)

                    except asyncio.TimeoutError:
                        # Keep connection alive if market is quiet
                        await ws.ping()
                    except Exception as e:
                        print(f"\n⚠️ Stream Error: {e}")
                        break
        except Exception as e:
            print(f"\n❌ Connection Error: {e}")
        
        print("🔄 Waiting 4s for next market cycle...")
        await asyncio.sleep(4)

def process_item(item, watcher):
    """Parses WebSocket messages for price data"""
    # 1. Level 1 Updates (Best Ask is the price to Buy)
    if item.get('event_type') == 'level1':
        aid = item.get('asset_id')
        ask = item.get('best_ask')
        if aid and ask:
            watcher.update_price(aid, float(ask))
            
    # 2. Price Change Updates (Alternative channel format)
    elif item.get('event_type') == 'price_change':
        for c in item.get('price_changes', []):
            watcher.update_price(c['asset_id'], float(c.get('best_ask') or 0))

    # 3. Book Snapshot (Initial state)
    elif item.get('event_type') == 'book':
        asks = item.get('asks', [])
        if asks: 
            watcher.update_price(item['asset_id'], float(asks[0]['price']))

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("\n👋 Exiting Market Watcher")
import asyncio
import json
import aiohttp
from datetime import datetime, timedelta
import pytz
from urllib.parse import quote_plus

# Configuration
API_URL = "https://gamma-api.polymarket.com/public-search"
ET_TZ = pytz.timezone("America/New_York")

# ----------------------------
# Time Helpers
# ----------------------------
def current_et():
    """Get current time in Eastern Time."""
    return datetime.now(ET_TZ)

def get_window_boundaries(now_et=None):
    """Calculate the start and end of the current 15-minute window."""
    if now_et is None:
        now_et = current_et()
    
    # Round down to nearest 15 minutes
    minute = (now_et.minute // 15) * 15
    start = now_et.replace(minute=minute, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    return start, end

def title_variants(start):
    """Generate search query variations based on Polymarket naming conventions."""
    # Polymarket uses formats like: "Bitcoin Up or Down - November 22, 10:15PM ET"
    date_str = start.strftime("%B %d").replace(" 0", " ") # "November 22"
    time_str = start.strftime("%I:%M%p").lstrip("0").upper() # "10:15PM"
    
    return [
        f"Bitcoin Up or Down {date_str} {time_str} ET",
        f"Bitcoin Up or Down - {date_str}, {time_str} ET",
        f"Bitcoin Up or Down - {date_str} {time_str} ET",
    ]

# ----------------------------
# Market Discovery Logic
# ----------------------------
async def find_active_window():
    """
    Scans the Gamma API for the currently active 15-minute Bitcoin market.
    Returns a dictionary with market details or None.
    """
    now_et = current_et()
    start, end = get_window_boundaries(now_et)
    
    print(f"🔍 Scanning for window: {start.strftime('%I:%M')} – {end.strftime('%I:%M %p')} ET")

    async with aiohttp.ClientSession() as session:
        # Generate queries for the current window and the next window 
        # (sometimes the API indexes the next one slightly before the current one ends)
        queries = title_variants(start) + title_variants(end)
        
        for q in queries:
            url = f"{API_URL}?q={quote_plus(q)}"
            
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"⚠️ API Error: {resp.status} for query {q}")
                        continue
                    data = await resp.json()
            except Exception as e:
                print(f"⚠️ Connection Error: {e}")
                continue

            events = data.get("events", [])
            if not events:
                continue

            for ev in events:
                # Valid markets are usually the first item in the 'markets' array
                m = ev.get("markets", [{}])[0]

                # Extract timing
                start_ts = m.get("eventStartTime") or ev.get("startTime")
                end_ts = m.get("endDate") or ev.get("endDate")

                if not start_ts or not end_ts:
                    continue

                # Convert to datetime objects for comparison
                start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).astimezone(ET_TZ)
                end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00")).astimezone(ET_TZ)

                # Filter 1: Ensure it is a short-term market (duration <= 30 mins)
                duration = (end_dt - start_dt).total_seconds()
                if duration > 1800: 
                    continue

                # Filter 2: Ensure it is currently active
                if start_dt <= now_et < end_dt:
                    token_ids = json.loads(m["clobTokenIds"])
                    title = ev.get("title", "BTC 15m")
                    
                    return {
                        "title": title,
                        "yes_id": token_ids[0],
                        "no_id": token_ids[1],
                        "start_time": start_dt.isoformat(),
                        "end_time": end_dt.isoformat(),
                        "condition_id": m.get("conditionId"),
                        "question_id": m.get("questionID")
                    }

    return None

# ----------------------------
# Execution
# ----------------------------
async def main():
    print("--- Polymarket 15m Bitcoin Discovery ---\n")
    
    try:
        market = await find_active_window()
        
        if market:
            print("\n✅ MARKET FOUND")
            print(f"Title:      {market['title']}")
            print(f"YES ID:     {market['yes_id']}")
            print(f"NO ID:      {market['no_id']}")
            print(f"Start:      {market['start_time']}")
            print(f"End:        {market['end_time']}")
        else:
            print("\n❌ No active market found. (Is the API lagging or market closed?)")
            
    except Exception as e:
        print(f"\n💥 Critical Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
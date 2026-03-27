#!/usr/bin/env python3
"""
Daily News Brief Automation for Lily - v2 with Live Data Integration
Fetches content via APIs and sends HTML email

Live Data Sources:
- World News: NewsAPI + Google News RSS (existing)
- Bay Area News: RSS feeds (existing)
- Restaurants: Yelp Fusion API (5k req/day free)
- Events: FuncheapSF RSS feed
- Finance: Yahoo Finance via yfinance (free)
- Gossip: E! News RSS feed
- Scenic Spots: Google Places API
- History: Wikipedia "On This Day" API

API Keys Required:
- NEWSAPI_KEY: newsapi.org (free tier)
- YELP_API_KEY: yelp.com/fusion (free tier)
- GOOGLE_API_KEY: Google Cloud Places API ($200/mo free tier)

Optional (no key needed):
- Yahoo Finance via yfinance library
- All RSS feeds (E! News, FuncheapSF, Bay Area news)
- Wikipedia On This Day API
"""

import os
import sys
import json
import subprocess
import datetime
import urllib.request
import urllib.parse
from pathlib import Path
from html.parser import HTMLParser

# Load .env file if it exists
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key, value)

# Config
CONFIG = {
    "to_email": "jieyinglily.li@gmail.com",
    "from_account": "lilyexecutiveassistant@gmail.com",
    "location": "San Jose, CA",
    "lat": 37.3382,
    "lng": -121.8863,
}


def get_newsletter_recipients():
    """Return the recipient list, allowing overrides via env var."""
    env = os.getenv("LILY_NEWSLETTER_RECIPIENTS", "").strip()
    if env:
        return [email.strip() for email in env.split(",") if email.strip()]
    return [CONFIG["to_email"]]

# API Keys
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
YELP_API_KEY = os.getenv("YELP_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
AIRNOW_API_KEY = os.getenv("AIRNOW_API_KEY", "")  # AirNow API key
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")  # OpenWeatherMap free tier

# Import feedback tracking module (for Phase 1 tracking URLs)
# The module auto-initializes the database
FEEDBACK_MODULE_AVAILABLE = False
NEWSLETTER_ID = None  # Global for this newsletter run

def init_tracking_for_newsletter(date_sent: str) -> str:
    """Initialize a newsletter tracking ID for this run.
    
    This creates a newsletter entry in the database and returns
    a unique ID for attribution in this newsletter.
    """
    global FEEDBACK_MODULE_AVAILABLE, NEWSLETTER_ID
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from newsletter_feedback import create_newsletter
        FEEDBACK_MODULE_AVAILABLE = True
        NEWSLETTER_ID = create_newsletter(date_sent)
        print(f"✓ Newsletter tracking ID: {NEWSLETTER_ID}")
        return NEWSLETTER_ID
    except Exception as e:
        print(f"⚠️  Feedback tracking unavailable: {e}")
        FEEDBACK_MODULE_AVAILABLE = False
        NEWSLETTER_ID = None
        return None


def get_tracking_url(base_url: str, item_type: str, item_id: str) -> str:
    """Generate a tracking URL with newsletter attribution.
    
    Args:
        base_url: The original destination URL
        item_type: Type of item ('restaurant', 'event', 'scenic')
        item_id: Unique identifier for this item (name works fine)
    
    Returns:
        Tracking URL with nl_track parameters, or base_url if tracking unavailable
    """
    if not FEEDBACK_MODULE_AVAILABLE or not NEWSLETTER_ID:
        return base_url
    
    try:
        # Import locally to handle any import issues gracefully
        from newsletter_feedback import generate_tracking_url
        return generate_tracking_url(item_type, item_id, base_url, NEWSLETTER_ID)
    except Exception:
        return base_url

def get_today_info():
    """Get today's date info for the brief"""
    today = datetime.datetime.now()
    return {
        "weekday": today.strftime("%A"),
        "month": today.strftime("%B"),
        "day": today.day,
        "date_str": today.strftime("%Y-%m-%d"),
        "display_date": today.strftime("%A, %B %-d"),
        "month_num": today.month,
        "day_num": today.day
    }


FEEDBACK_FILE = Path.home() / ".openclaw/workspace/newsletter-feedback.json"


def load_feedback():
    """Load existing feedback data."""
    if FEEDBACK_FILE.exists():
        try:
            with open(FEEDBACK_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"feedbacks": [], "scores": {}}


def save_feedback(data):
    """Save feedback data."""
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def record_feedback(section, item, action):
    """Record a feedback action (click, loved, skip)."""
    data = load_feedback()
    today = datetime.datetime.now()
    
    entry = {
        "date": today.strftime("%Y-%m-%d"),
        "section": section,
        "item": item,
        "action": action,
        "timestamp": today.isoformat()
    }
    data["feedbacks"].append(entry)
    
    # Update scores: +1 for click/loved, -1 for skip
    if action in ["click", "loved"]:
        data["scores"][item] = data["scores"].get(item, 0) + 1
    elif action == "skip":
        data["scores"][item] = data["scores"].get(item, 0) - 1
    
    save_feedback(data)
    print(f"📝 Feedback recorded: [{action}] {item} ({section})")


def get_item_score(item):
    """Get preference score for an item."""
    data = load_feedback()
    return data.get("scores", {}).get(item, 0)


def generate_tracking_link(base_url, section, item_name, action="click"):
    """Generate a tracking ID for a link click."""
    today = datetime.datetime.now()
    tracking_id = f"nl_{today.strftime('%Y%m%d')}_{section}_{item_name[:20].replace(' ', '_')}_{action}"
    return f"{base_url}?nltrack={urllib.parse.quote(tracking_id)}"


def get_feedback_scores():
    """Load preference scores from feedback data.
    
    Returns:
        dict: item_name -> preference score (float)
              +1 per 'loved', -1 per 'skip', +0.5 per click
    """
    data = load_feedback()
    return data.get("scores", {})


def score_with_feedback(item_name, item_type):
    """Get the feedback preference score for an item.
    
    Also checks type-specific JSON feedback database if available.
    """
    # First check the JSON feedback file
    scores = get_feedback_scores()
    score = scores.get(item_name, 0)
    
    # Also check the SQLite database if available (newsletter_feedback module)
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from newsletter_feedback import get_item_preference_score
        db_score = get_item_preference_score(item_type, item_name)
        if db_score is not None:
            # Combine: weight DB higher since it's more detailed
            score = score * 0.3 + db_score * 0.7
    except Exception:
        pass
    
    return score


def select_with_feedback(items, item_type, max_items=None, min_score=-2.0):
    """Select and rank items using feedback-driven scoring.
    
    Applies preference scores to reorder items, removes items with score < min_score,
    and maintains some variety so high-scoring items don't dominate.
    
    Args:
        items: List of item dicts (must have 'name' key)
        item_type: Type of item ('restaurant', 'event', 'scenic')
        max_items: Maximum items to return (default: len(items))
        min_score: Minimum score threshold; items below this are excluded
    
    Returns:
        Reordered list of items (may be shorter than input)
    """
    if not items:
        return items
    
    if max_items is None:
        max_items = len(items)
    
    # Check if we have any feedback data
    scores = get_feedback_scores()
    has_feedback = any(
        score_with_feedback(item.get('name', ''), item_type) != 0
        for item in items
    )
    
    # Fall back to original order if no feedback exists
    if not has_feedback:
        print(f"  ⓘ No feedback data for {item_type}, using original selection")
        return items[:max_items]
    
    # Score each item
    scored_items = []
    for item in items:
        name = item.get('name', '')
        score = score_with_feedback(name, item_type)
        
        # Skip items below minimum score threshold
        if score < min_score:
            print(f"  ⓘ Excluding '{name}' (score {score:.1f} < {min_score})")
            continue
        
        scored_items.append((score, name, item))
    
    if not scored_items:
        print(f"  ⓘ All {item_type} items excluded by feedback, using original selection")
        return items[:max_items]
    
    # Sort by score descending
    scored_items.sort(key=lambda x: x[0], reverse=True)
    
    # Apply variety: don't let top-scoring items completely dominate
    # For each category, pick: top 40% by score + random 20% + rest by score
    # But keep it simple: take top item + random shuffle of the rest
    result = []
    
    if len(scored_items) >= 3:
        # Always include the top-scored item
        top = scored_items[0]
        result.append(top[2])
        print(f"  ✓ Top pick: '{top[1]}' (score {top[0]:.1f})")
        
        # For remaining slots, shuffle middle-tier items to add variety
        # (don't always pick #2, #3, etc.)
        remaining = scored_items[1:]
        import random
        random.shuffle(remaining)
        
        for score, name, item in remaining:
            if len(result) >= max_items:
                break
            result.append(item)
            print(f"  ✓ Selected: '{name}' (score {score:.1f})")
    else:
        for score, name, item in scored_items:
            if len(result) >= max_items:
                break
            result.append(item)
            print(f"  ✓ Selected: '{name}' (score {score:.1f})")
    
    return result


def add_feedback_buttons(item_name, item_type="general", newsletter_id=None):
    """Generate HTML feedback micro-buttons for an item.
    
    Args:
        item_name: Name of the item (restaurant, event, scenic spot)
        item_type: Type of item ('restaurant', 'event', 'scenic')
        newsletter_id: Optional newsletter ID for attribution
    
    Returns:
        HTML string with styled feedback buttons using mailto links
    """
    # Encode feedback data in the subject line for easy parsing
    # Format: NL_FEEDBACK|{nl_id}|{type}|{item}|{action}
    nl_id = newsletter_id if newsletter_id else "unknown"
    
    # Create encoded subject lines for each action
    loved_subject = urllib.parse.quote(f"NL_FEEDBACK|{nl_id}|{item_type}|{item_name}|loved")
    skip_subject = urllib.parse.quote(f"NL_FEEDBACK|{nl_id}|{item_type}|{item_name}|skipped")
    
    # Build mailto URLs with pre-filled body
    loved_body = urllib.parse.quote(f"Lily liked: {item_name} ({item_type})")
    skip_body = urllib.parse.quote(f"Lily wants to skip: {item_name} ({item_type})")
    
    loved_url = f"mailto:lilyexecutiveassistant@gmail.com?subject={loved_subject}&body={loved_body}"
    skip_url = f"mailto:lilyexecutiveassistant@gmail.com?subject={skip_subject}&body={skip_body}"
    
    return f'''<span class="feedback-buttons" style="display: inline-block; margin-left: 10px;">
  <a href="{loved_url}" class="feedback-btn loved" style="display: inline-block; padding: 4px 10px; margin-right: 6px; border-radius: 4px; font-size: 12px; font-weight: bold; text-decoration: none; background: #28a745; color: white; border: none; cursor: pointer; min-height: 24px; line-height: 16px;">👍 Loved It</a>
  <a href="{skip_url}" class="feedback-btn skip" style="display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; text-decoration: none; background: #6c757d; color: white; border: none; cursor: pointer; min-height: 24px; line-height: 16px;">⏭️ Skip</a>
</span>'''


def fetch_yelp_restaurants():
    """Fetch South Bay restaurants from Yelp Fusion API, fallback to Google Maps CDP"""
    import urllib.request
    
    api_key = os.getenv("YELP_API_KEY", "")
    if not api_key:
        print("⚠️  Yelp API key not set, using Google Maps CDP fallback")
        return fetch_google_maps_restaurants_fallback()
    
    # Search for restaurants in San Jose area
    # Sort by best_match or rating, price range 1-2 ($-$$)
    url = "https://api.yelp.com/v3/businesses/search"
    params = {
        "latitude": CONFIG["lat"],
        "longitude": CONFIG["lng"],
        "categories": "restaurants",
        "sort_by": "best_match",
        "limit": 10,
        "price": "1,2,3"  # $, $$, $$$
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        query_string = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{query_string}", headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            restaurants = []
            for biz in data.get('businesses', [])[:5]:
                price = biz.get('price', '$$')
                price_display = price if price else '$$'
                
                restaurants.append({
                    "name": biz.get('name', 'Unknown'),
                    "location": biz.get('location', {}).get('city', 'San Jose'),
                    "type": ', '.join(biz.get('categories', [{}])[0].get('title', '') for c in biz.get('categories', [{}])[:1]),
                    "price": price_display,
                    "notes": f"Rating: {biz.get('rating', 'N/A')}/5 stars. {biz.get('review_count', 0)} reviews",
                    "link": biz.get('url', '#')
                })
            
            print(f"✓ Yelp API: {len(restaurants)} restaurants fetched")
            return restaurants
            
    except Exception as e:
        print(f"⚠️  Yelp API failed: {e}")
        return fetch_south_bay_restaurants_fallback()


def fetch_google_maps_restaurants_fallback():
    """Fallback using Google Maps CDP scraper when Yelp API key is not available"""
    try:
        import subprocess
        import json
        
        # Run the Google Maps scraper
        script_path = Path(__file__).parent / "google_maps_scraper.py"
        result = subprocess.run(
            ["python3", str(script_path), "--type", "restaurants", 
             "--location", "San Jose, CA", "--count", "5", "--newsletter-format"],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # Parse JSON output (skip connection lines, find the JSON array)
        output = result.stdout
        # Find the start of JSON array
        json_start = output.find('[')
        if json_start >= 0:
            restaurants = json.loads(output[json_start:])
            if restaurants:
                print(f"✓ Google Maps CDP: {len(restaurants)} restaurants fetched")
                # Fill in missing fields with defaults
                for r in restaurants:
                    if not r.get('price'):
                        r['price'] = '$$'
                    if not r.get('type'):
                        r['type'] = 'Restaurant'
                return restaurants[:5]
        
        # If we couldn't parse or got empty results, use static fallback
        print("⚠️  Google Maps CDP returned no results, using static fallback")
        return fetch_south_bay_restaurants_static_fallback()
        
    except Exception as e:
        print(f"⚠️  Google Maps CDP failed: {e}")
        return fetch_south_bay_restaurants_static_fallback()


def fetch_south_bay_restaurants_static_fallback():
    """Static restaurant recommendations (last resort)"""
    return [
        {
            "name": "Aquariuz",
            "location": "San Jose (Downtown)",
            "type": "Upscale Seafood",
            "price": "$$$",
            "notes": "Beautiful presentation, seafood towers, great natural lighting",
            "link": "https://www.aquariuzsj.com/"
        },
        {
            "name": "Back A Yard",
            "location": "Menlo Park",
            "type": "Jamaican/Caribbean",
            "price": "$",
            "notes": "Food Network featured, $15-20 per person, huge portions",
            "link": "https://www.backayard.net/"
        },
        {
            "name": "Falafel Drive-In",
            "location": "San Jose",
            "type": "Middle Eastern",
            "price": "$",
            "notes": "Iconic since 1966, under $10, retro neon vibe",
            "link": "https://falafeldrivein.com/"
        },
        {
            "name": "Din Tai Fung",
            "location": "Valley Fair, San Jose",
            "type": "Taiwanese/Dim Sum",
            "price": "$$",
            "notes": "Famous soup dumplings, glass kitchen, $25-35 per person",
            "link": "https://dintaifungusa.com/"
        },
        {
            "name": "Pa'ina Bar & Grill",
            "location": "Palo Alto",
            "type": "Hawaiian",
            "price": "$$",
            "notes": "Poke bowls, tropical drinks, bright airy space, lunch specials",
            "link": "https://www.painapaloalto.com/"
        }
    ]


def fetch_bart_realtime():
    """Fetch real-time BART departures from Berryessa station and 880 traffic.
    
    Focuses on the Berryessa → Oakland corridor (12th St, 19th St, MacArthur).
    Also estimates I-880 N/S traffic times from Berryessa to Oakland.
    """
    import re
    
    BART_API_KEY = "MW9S-E7SL-26DU-VV98"  # Public demo key (official BART demo key)
    BART_BASE_URL = "https://api.bart.gov/api"
    
    # Oakland corridor stations from Berryessa
    OAKLAND_CORRIDOR = [
        "12th", "19th", "MacArthur", "Rockridge", 
        "Downtown Berkeley", "Ashby", "El Cerrito", "Richmond"
    ]
    
    bart_info = {
        "departures": [],
        "departures_text": "",
        "alerts": [],
        "alerts_text": "",
        "traffic": None,
        "traffic_text": "",
        "oakland_departures": [],  # Specifically for Oakland corridor
        "oakland_corridor_text": ""
    }
    
    # Fetch BART ETD (Estimated Time of Departure) from Berryessa (BERY)
    try:
        url = f"{BART_BASE_URL}/etd.aspx?cmd=etd&orig=bery&key={BART_API_KEY}&json=y"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            root = data.get('root', {})
            station_etd = root.get('station', [{}])[0] if root.get('station') else {}
            etd_entries = station_etd.get('etd', [])
            
            # Ensure etd_entries is a list
            if isinstance(etd_entries, dict):
                etd_entries = [etd_entries]
            
            all_departures = []
            oakland_departures = []
            
            for entry in etd_entries:
                destination = entry.get('destination', 'Unknown')
                platform = entry.get('platformnumber', '?')
                times = []
                colors = []
                
                estimate_list = entry.get('estimate', [])
                if isinstance(estimate_list, dict):
                    estimate_list = [estimate_list]
                
                for estimate in estimate_list:
                    minutes_str = estimate.get('minutes', '0')
                    color = estimate.get('color', 'gray').lower()
                    
                    if minutes_str == 'Leaving':
                        minutes_str = '0'
                    elif minutes_str == 'Arriving':
                        minutes_str = '1'
                    
                    try:
                        minutes = int(minutes_str)
                        times.append(minutes)
                        colors.append(color)
                    except ValueError:
                        continue
                
                if times:
                    dep_info = {
                        "platform": platform,
                        "destination": destination.title(),
                        "minutes": sorted(set(times))[:3],
                        "color": colors[0] if colors else "gray",
                        "direction": "North" if any(d.lower() in destination.lower() for d in ['mont', '12th', '19th', 'embr', 'civc', 'richmond', 'downtown berkeley', 'el cerrito', 'ashby', 'macarthur', 'rockridge']) else "South"
                    }
                    all_departures.append(dep_info)
                    
                    # Check if this train serves Oakland corridor
                    is_oakland_corridor = any(
                        station.lower() in destination.lower() or 
                        (station == "12th" and "12th" in destination.lower()) or
                        (station == "19th" and "19th" in destination.lower()) or
                        (station == "MacArthur" and "macarthur" in destination.lower())
                        for station in OAKLAND_CORRIDOR
                    )
                    
                    # Include Antioch/Orange line trains (serve Oakland corridor via transfer or direct)
                    is_orange_line = "antioch" in destination.lower()
                    is_red_line = any(x in destination.lower() for x in ['richmond', 'downtown berkeley'])
                    
                    if is_oakland_corridor or is_orange_line or is_red_line:
                        oakland_departures.append(dep_info)
            
            if all_departures:
                bart_info["departures"] = all_departures
                print(f"✓ BART: {len(all_departures)} departure directions fetched")
            
            # Oakland corridor specific departures
            if oakland_departures:
                oakland_lines = []
                for dep in oakland_departures[:3]:  # Top 3 to Oakland
                    color_emoji = {"orange": "🟠", "red": "🔴", "yellow": "🟡", "green": "🟢", "blue": "🔵"}.get(dep['color'], "⚪")
                    times_str = ", ".join(f"{m} min" if m > 0 else "Leaving" for m in dep['minutes'])
                    oakland_lines.append(f"{color_emoji} {dep['destination']}: {times_str}")
                bart_info["oakland_departures"] = oakland_departures
                bart_info["oakland_corridor_text"] = " | ".join(oakland_lines)
                
                # Also build full departures text
                lines = []
                for dep in all_departures[:4]:
                    color_emoji = {"orange": "🟠", "red": "🔴", "yellow": "🟡", "green": "🟢", "blue": "🔵"}.get(dep['color'], "⚪")
                    times_str = ", ".join(f"{m} min" if m > 0 else "Leaving" for m in dep['minutes'])
                    lines.append(f"{color_emoji} {dep['destination']}: {times_str}")
                bart_info["departures_text"] = " | ".join(lines)
                
                print(f"✓ BART: Oakland corridor departures ({len(oakland_departures)} lines)")
            else:
                bart_info["departures_text"] = "No departures currently scheduled."
                
    except Exception as e:
        print(f"⚠️  BART ETD fetch failed: {e}")
        bart_info["departures_text"] = "BART service info temporarily unavailable"
    
    # Fetch BART service alerts (BSA) for Oakland corridor
    try:
        url = f"{BART_BASE_URL}/bsa.aspx?cmd=bsa&key={BART_API_KEY}&json=y"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            root = data.get('root', {})
            bsa_entries = root.get('bsa', [])
            
            # Ensure bsa_entries is a list
            if isinstance(bsa_entries, dict):
                bsa_entries = [bsa_entries]
            
            alerts = []
            for entry in bsa_entries:
                if entry.get('type', '').lower() in ['info', '_none']:
                    continue
                
                msg_text = entry.get('description', entry.get('sms_text', ''))
                if not msg_text:
                    continue
                
                # Filter for Oakland/Berryessa corridor relevance
                oakland_keywords = ['oakland', 'berryessa', '12th', '19th', 'macarthur', 'richmond', 'fremont', 'antioch', 'dublin']
                is_relevant = any(kw in msg_text.lower() for kw in oakland_keywords)
                
                delay_match = re.search(r'(\d+)\s*min', msg_text, re.I)
                delay_minutes = int(delay_match.group(1)) if delay_match else 0
                
                if is_relevant and (delay_minutes >= 5 or delay_minutes == 0):
                    alerts.append({
                        "severity": entry.get('type', 'DELAY').upper(),
                        "message": msg_text[:120]
                    })
            
            if alerts:
                bart_info["alerts"] = alerts
                # Keep it concise - just first alert or summary
                first_alert = alerts[0]
                bart_info["alerts_text"] = f"{first_alert['severity']}: {first_alert['message'][:80]}..."
                print(f"✓ BART: {len(alerts)} service alert(s) for Oakland corridor")
            else:
                bart_info["alerts_text"] = "No significant delays."
                
    except Exception as e:
        print(f"⚠️  BART BSA fetch failed: {e}")
        bart_info["alerts_text"] = "Service alerts unavailable"
    
    # I-880 Traffic estimation (Berryessa to Oakland)
    # Since we don't have real-time traffic API, use time-based heuristics
    hour = datetime.datetime.now().hour
    weekday = datetime.datetime.now().weekday()  # 0=Monday, 6=Sunday
    
    # Northbound to Oakland (AM commute is heavy)
    if 6 <= hour <= 9 and weekday < 5:  # AM rush on weekdays
        nb_time, nb_conditions = 35, "heavy"
    elif 15 <= hour <= 19 and weekday < 5:  # PM rush
        nb_time, nb_conditions = 40, "heavy"
    elif 10 <= hour <= 14:
        nb_time, nb_conditions = 25, "light-moderate"
    elif 20 <= hour <= 5:
        nb_time, nb_conditions = 20, "light"
    else:
        nb_time, nb_conditions = 30, "moderate"
    
    # Southbound from Oakland (usually lighter except PM rush)
    if 15 <= hour <= 19 and weekday < 5:  # PM rush southbound
        sb_time, sb_conditions = 35, "moderate-heavy"
    elif 6 <= hour <= 9 and weekday < 5:
        sb_time, sb_conditions = 25, "light"
    elif 10 <= hour <= 14:
        sb_time, sb_conditions = 22, "light"
    elif 20 <= hour <= 5:
        sb_time, sb_conditions = 18, "light"
    else:
        sb_time, sb_conditions = 28, "moderate"
    
    bart_info["traffic"] = {
        "northbound": {"time": nb_time, "conditions": nb_conditions},
        "southbound": {"time": sb_time, "conditions": sb_conditions}
    }
    
    # Build concise traffic text (2-3 lines max)
    traffic_lines = [
        f"🚗 880 North (Berryessa → Oakland): {nb_time} min ({nb_conditions})",
        f"🚗 880 South (Oakland → Berryessa): {sb_time} min ({sb_conditions})"
    ]
    bart_info["traffic_text"] = " | ".join(traffic_lines)
    
    return bart_info


def fetch_sunrise_sunset():
    """Fetch sunrise/sunset times and moon phase from sunrise-sunset.org API (no key required)
    
    Uses formatted=0 + tzId=America/Los_Angeles for ISO timestamps with PT offset (e.g. 2026-03-26T06:35:16-07:00).
    """
    lat, lng = CONFIG["lat"], CONFIG["lng"]
    # formatted=0 returns ISO 8601 with timezone offset; tzId sets the output timezone
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lng}&formatted=0&tzId=America/Los_Angeles"
    
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        print(f"   Sunrise-Sunset API status: {data.get('status')}")
        if data.get("status") == "OK":
            results = data["results"]
            print(f"   Raw sunrise={results.get('sunrise')}, sunset={results.get('sunset')}")
            
            # Parse ISO timestamp with offset (e.g. "2026-03-26T06:35:16-07:00") → PT time
            def to_pt(iso_str):
                if not iso_str:
                    return ""
                s = iso_str.replace("Z", "+00:00")
                try:
                    dt = datetime.datetime.fromisoformat(s)
                except ValueError:
                    # Handle missing colon in offset: "+0000" → "+00:00"
                    if s[-3:-2] in ("+", "-"):
                        s = s[:-2] + ":" + s[-2:]
                    dt = datetime.datetime.fromisoformat(s)
                return dt.strftime("%-I:%M %p")
            
            sunrise_pt = to_pt(results.get("sunrise", ""))
            sunset_pt = to_pt(results.get("sunset", ""))
            moonrise_pt = to_pt(results.get("moonrise", ""))
            moonset_pt = to_pt(results.get("moonset", ""))
            moon_phase = results.get("moon_phase", "")
            
            # Golden hour: sunrise + 1hr, sunset - 1hr
            def add_hour(pt_str):
                if not pt_str:
                    return ""
                dt = datetime.datetime.strptime(pt_str, "%-I:%M %p")
                dt += datetime.timedelta(hours=1)
                return dt.strftime("%-I:%M %p")
            
            golden_am_start = sunrise_pt
            golden_am_end = add_hour(sunrise_pt)
            dt_sunset = datetime.datetime.strptime(sunset_pt, "%-I:%M %p")
            dt_golden_start = dt_sunset - datetime.timedelta(hours=1)
            golden_pm_start = dt_golden_start.strftime("%-I:%M %p")
            
            # Moon phase emoji
            moon_phases = {
                "new_moon": "🌑", "waxing_crescent": "🌒", "first_quarter": "🌓",
                "waxing_gibbous": "🌔", "full_moon": "🌕", "waning_gibbous": "🌖",
                "last_quarter": "🌗", "waning_crescent": "🌘"
            }
            moon_emoji = moon_phases.get(moon_phase, "🌕")
            
            print(f"   🌅 sunrise={sunrise_pt}, sunset={sunset_pt}, moon={moon_emoji} {moon_phase}")
            
            return {
                "sunrise": sunrise_pt,
                "sunset": sunset_pt,
                "golden_am_start": golden_am_start,
                "golden_am_end": golden_am_end,
                "golden_pm_start": golden_pm_start,
                "golden_pm_end": sunset_pt,
                "moonrise": moonrise_pt,
                "moonset": moonset_pt,
                "moon_phase": moon_phase,
                "moon_emoji": moon_emoji,
                "raw": data
            }
    except Exception as e:
        print(f"⚠️  Sunrise-Sunset API failed: {e}")
    
    return None


def fetch_air_quality():
    """Fetch air quality index for San Jose and Oakland from AirNow API.
    Returns dict with 'sj' and 'oakland' keys, each containing AQI data or None.
    Handles missing API key gracefully.
    """
    result = {"sj": None, "oakland": None}
    
    locations = {
        "sj": (37.3382, -121.8863, "San Jose"),
        "oakland": (37.8044, -122.2712, "Oakland"),
    }
    
    if not AIRNOW_API_KEY:
        print("⚠️  AirNow API key not set, skipping air quality data")
        return result
    
    for key, (lat, lng, name) in locations.items():
        url = (f"https://www.airnowapi.org/aq/observation/latLong/current/"
               f"?format=application/json&latitude={lat}&longitude={lng}"
               f"&distance=25&API_KEY={AIRNOW_API_KEY}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            
            if data and len(data) > 0:
                obs = data[0]
                aqi = int(obs.get("AQI", 0))
                category = obs.get("Category", {}).get("Name", "Unknown")
                
                if aqi <= 50:
                    aqi_color = "#28a745"
                    aqi_label = "Good"
                elif aqi <= 100:
                    aqi_color = "#ffc107"
                    aqi_label = "Moderate"
                else:
                    aqi_color = "#dc3545"
                    aqi_label = "Unhealthy"
                
                result[key] = {
                    "aqi": aqi,
                    "category": category,
                    "color": aqi_color,
                    "label": aqi_label,
                    "location": name,
                }
        except Exception as e:
            print(f"⚠️  AirNow API failed for {name}: {e}")
    
    return result


def fetch_weather():
    """Fetch current weather from Open-Meteo (free, no API key needed).
    Falls back to OpenWeatherMap if OPENWEATHER_API_KEY env var is set.
    Returns dict with temp_f, conditions, cloud_cover, humidity, visibility_km, wind_mph.
    """
    lat, lng = CONFIG["lat"], CONFIG["lng"]
    
    if OPENWEATHER_API_KEY:
        url = (f"https://api.openweathermap.org/data/2.5/weather"
               f"?lat={lat}&lon={lng}&units=imperial&appid={OPENWEATHER_API_KEY}")
    else:
        # Open-Meteo free API (no key required)
        # Use repeated param format to avoid comma-encoding issues
        params = (
            f"latitude={lat}&longitude={lng}"
            "&current=temperature_2m"
            "&current=weather_code"
            "&current=cloud_cover"
            "&current=relative_humidity_2m"
            "&current=visibility"
            "&current=wind_speed_10m"
            "&temperature_unit=fahrenheit"
            "&wind_speed_unit=mph"
            "&timezone=America%2FLos_Angeles"
        )
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
    
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        if OPENWEATHER_API_KEY:
            # OpenWeatherMap response
            return {
                "temp_f": round(data["main"]["temp"]),
                "conditions": data["weather"][0]["description"].title(),
                "cloud_cover": data.get("clouds", {}).get("all", 30),
                "humidity": data["main"]["humidity"],
                "visibility_km": data.get("visibility", 10) / 1000,
                "wind_mph": round(data["wind"]["speed"]),
                "icon": data["weather"][0]["icon"],
                "source": "OpenWeatherMap",
            }
        else:
            # Open-Meteo response
            current = data.get("current", {})
            weather_code = current.get("weather_code", 0)
            conditions = _WMO_CODES.get(weather_code, "Unknown")
            return {
                "temp_f": round(current.get("temperature_2m", 60)),
                "conditions": conditions,
                "cloud_cover": current.get("cloud_cover", 30),
                "humidity": current.get("relative_humidity_2m", 50),
                "visibility_km": current.get("visibility", 16000) / 1000,  # m to km
                "wind_mph": round(current.get("wind_speed_10m", 5)),
                "icon": None,
                "source": "Open-Meteo",
            }
    except Exception as e:
        print(f"⚠️  Weather API failed: {e}")
    
    return None


# WMO Weather interpretation codes (used by Open-Meteo)
_WMO_CODES = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing Rime Fog",
    51: "Light Drizzle", 53: "Moderate Drizzle", 55: "Dense Drizzle",
    56: "Light Freezing Drizzle", 57: "Dense Freezing Drizzle",
    61: "Slight Rain", 63: "Moderate Rain", 65: "Heavy Rain",
    66: "Light Freezing Rain", 67: "Heavy Freezing Rain",
    71: "Slight Snow", 73: "Moderate Snow", 75: "Heavy Snow",
    77: "Snow Grains",
    80: "Slight Rain Showers", 81: "Moderate Rain Showers", 82: "Violent Rain Showers",
    85: "Slight Snow Showers", 86: "Heavy Snow Showers",
    95: "Thunderstorm", 96: "Thunderstorm with Slight Hail", 99: "Thunderstorm with Heavy Hail",
}


def get_photo_conditions_rating(weather_data=None):
    """Calculate photo conditions rating (1-5 stars) based on weather data.
    
    Factors for good photo weather:
    - Clear to partly cloudy skies (interesting sky without blocking light)
    - High visibility (no fog/haze)
    - Low humidity (clear atmosphere)
    - No rain
    """
    if weather_data is None:
        return {
            "rating": 4,
            "max_rating": 5,
            "description": "Partly cloudy - good for soft light photography",
            "stars": "★★★★☆"
        }
    
    rating = 3  # baseline
    factors = []
    
    # Check cloud cover (0-100)
    cloud_cover = weather_data.get("cloud_cover", 30)
    if cloud_cover < 20:
        rating += 1
        factors.append("clear skies")
    elif cloud_cover < 50:
        rating += 0.5
        factors.append("partly cloudy")
    
    # Check visibility
    visibility = weather_data.get("visibility_km", 10)
    if visibility > 15:
        rating += 1
        factors.append("excellent visibility")
    elif visibility > 10:
        rating += 0.5
        factors.append("good visibility")
    
    # Check conditions for rain/fog
    conditions = weather_data.get("conditions", "").lower()
    if any(x in conditions for x in ["rain", "drizzle", "thunderstorm", "fog", "mist"]):
        rating -= 1
        factors.append("poor conditions")
    
    rating = min(5, max(1, int(round(rating))))
    star_str = "★" * rating + "☆" * (5 - rating)
    
    return {
        "rating": rating,
        "max_rating": 5,
        "description": f"{', '.join(factors) if factors else 'Average conditions'}",
        "stars": star_str
    }


def fetch_sunny_conditions_html():
    """Fetch daily conditions (sunrise, moon, air quality, weather, photo rating) and return HTML.
    
    Integrates:
    - sunrise-sunset.org (free, no key): sunrise/sunset/golden hour/moon phase
    - Open-Meteo (free, no key): current temp, conditions, cloud cover, visibility
    - AirNow API (key required): AQI for San Jose + Oakland
    """
    # Fetch all data
    print("🔆 Fetching sunrise/sunset...")
    sun_data = fetch_sunrise_sunset()
    print(f"   sun_data = {sun_data}")
    air_data = fetch_air_quality()  # returns {"sj": {...}, "oakland": {...}}
    weather_data = fetch_weather()   # returns {...} or None
    photo_data = get_photo_conditions_rating(weather_data)
    print(f"   weather_data = {weather_data}")
    print(f"   photo_data = {photo_data}")
    
    # Build HTML
    html = '<div class="section" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 25px;">'
    html += '<h2 style="color: white; border-bottom: 1px solid rgba(255,255,255,0.3); margin-top: 0;">📅 TODAY\'S CONDITIONS</h2>'
    
    # Sunrise / Sunset row
    print(f"   [conditions] sun_data={bool(sun_data)}, air_data_sj={bool(air_data.get('sj'))}, weather={bool(weather_data)}")
    if sun_data:
        html += f'''
<div style="display: flex; flex-wrap: wrap; gap: 20px; margin: 15px 0;">
    <div style="flex: 1; min-width: 140px;">
        <span style="font-size: 24px;">🌅</span><br>
        <strong>Sunrise:</strong> {sun_data['sunrise']}<br>
        <small>Golden Hour: {sun_data['golden_am_start']} – {sun_data['golden_am_end']}</small>
    </div>
    <div style="flex: 1; min-width: 140px;">
        <span style="font-size: 24px;">🌇</span><br>
        <strong>Sunset:</strong> {sun_data['sunset']}<br>
        <small>Golden Hour: {sun_data['golden_pm_start']} – {sun_data['golden_pm_end']}</small>
    </div>
</div>
'''
    
    # Weather conditions row (new)
    if weather_data:
        html += f'''
<div style="margin: 15px 0;">
    <span style="font-size: 20px;">🌡️</span> <strong>Weather:</strong> {weather_data['conditions']}, {weather_data['temp_f']}°F
    <span style="opacity: 0.85;"> · Clouds {weather_data['cloud_cover']}% · Humidity {weather_data['humidity']}%</span>
</div>
'''
    
    # Moon + Air Quality row (SJ + Oakland)
    html += '<div style="display: flex; flex-wrap: wrap; gap: 20px; margin: 15px 0;">'
    
    if sun_data:
        html += f'''
    <div style="flex: 1; min-width: 140px;">
        <span style="font-size: 20px;">{sun_data['moon_emoji']}</span> <strong>Moon:</strong> {sun_data['moon_phase'].replace('_', ' ').title()}
    </div>
'''
    
    # Air quality: show both SJ and Oakland if available
    aq_parts = []
    if air_data["sj"]:
        d = air_data["sj"]
        aq_parts.append(f'<span style="color: {d["color"]};">SJ: {d["aqi"]}</span> ({d["label"]})')
    if air_data["oakland"]:
        d = air_data["oakland"]
        aq_parts.append(f'<span style="color: {d["color"]};">Oak: {d["aqi"]}</span> ({d["label"]})')
    
    if aq_parts:
        html += f'''
    <div style="flex: 1; min-width: 140px;">
        <span style="font-size: 20px;">💨</span> <strong>Air Quality:</strong> {' · '.join(aq_parts)}
    </div>
'''
    else:
        html += '''
    <div style="flex: 1; min-width: 140px;">
        <span style="font-size: 20px;">💨</span> <strong>Air Quality:</strong> N/A (no API key)
    </div>
'''
    
    html += '</div>'
    
    # Photo conditions
    html += f'''
<div style="margin-top: 15px;">
    <span style="font-size: 20px;">📷</span> <strong>Photo Conditions:</strong> {photo_data['stars']}
    <span style="opacity: 0.9;">({photo_data['description']})</span>
</div>
'''
    
    html += '</div>'
    return html


def fetch_funcheep_events():
    """Fetch today's events from FuncheapSF RSS, prioritizing South Bay and East Bay.
    
    This function explicitly filters out SF-only events and only includes events
    that mention specific target regions (South Bay, East Bay, Peninsula).
    If no events are found, it falls back to `fetch_events_fallback()` which contains
    SF-centric static events.
    """
    import xml.etree.ElementTree as ET
    
    # South Bay and East Bay keywords to filter for
    target_regions = ['san jose', 'palo alto', 'mountain view', 'cupertino', 'sunnyvale', 
                     'santa clara', 'campbell', 'los gatos', 'fremont', 'newark',
                     'oakland', 'berkeley', 'alameda', 'emeryville', 'richmond',
                     'south bay', 'east bay', 'peninsula', 'silicon valley']
    
    # SF-specific to exclude
    sf_only = ['san francisco', 'sf ', 'soho', 'soma', 'mission district', 'haight',
               'castro', 'marina', 'nob hill', 'tenderloin', 'richmond district',
               'sunset district', 'north beach', 'chinatown sf', 'fisherman\'s wharf',
               'presidio', 'golden gate park']
    
    try:
        url = "https://sf.funcheap.com/feed/"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_content = response.read().decode('utf-8')
            root = ET.fromstring(xml_content)
            
            today = datetime.datetime.now()
            today_str = today.strftime("%Y-%m-%d")
            
            events = []
            for item in root.findall('.//item')[:20]:  # Check more items for filtering
                title = item.find('title')
                link = item.find('link')
                desc = item.find('description')
                pub_date = item.find('pubDate')
                
                if title is None or link is None:
                    continue
                
                title_text = title.text
                title_lower = title_text.lower()
                
                # Skip SF-only events
                if any(sf in title_lower for sf in sf_only):
                    continue
                
                # Only include if mentions target regions
                if not any(region in title_lower for region in target_regions):
                    continue
                
                # Parse publication date
                event_date = None
                if pub_date is not None and pub_date.text:
                    try:
                        event_date = datetime.datetime.strptime(
                            pub_date.text[:16], "%a, %d %b %Y"
                        )
                    except:
                        pass
                
                # Extract cost info from title if present
                cost = "FREE"
                if "$" in title_text:
                    import re
                    price_match = re.search(r'\$[\d.]+|\$\d+', title_text)
                    if price_match:
                        cost = price_match.group()
                elif "free" in title_text.lower():
                    cost = "FREE"
                
                # Clean up title
                title_clean = title_text.split("(")[0].strip() if "(" in title_text else title_text
                
                # Try to extract location from description
                location = "South/East Bay"
                if desc is not None and desc.text:
                    desc_lower = desc.text.lower()
                    if any(x in desc_lower for x in ['oakland', 'berkeley', 'alameda', 'richmond']):
                        location = "East Bay"
                    elif any(x in desc_lower for x in ['san jose', 'santa clara', 'campbell', 'cupertino']):
                        location = "South Bay"
                    elif any(x in desc_lower for x in ['palo alto', 'menlo park', 'mountain view', 'los altos']):
                        location = "Peninsula"
                
                events.append({
                    "name": title_clean,
                    "time": "See listing",
                    "location": location,
                    "cost": cost,
                    "link": link.text if link is not None else "https://sf.funcheap.com/"
                })
            
            print(f"✓ FuncheapSF RSS: {len(events)} South/East Bay events fetched")
            if not events:
                return fetch_events_fallback()
            return events[:5]  # Return top 5
            
    except Exception as e:
        print(f"⚠️  FuncheapSF fetch failed: {e}")
        return fetch_events_fallback()


def fetch_events_fallback():
    """Fallback static events for South Bay and East Bay.
    
    This is used when the live FuncheapSF API fails or returns no South/East Bay events.
    Unlike the old SF-centric fallback, this prioritizes events in:
    - South Bay (San Jose, Santa Clara, Sunnyvale, Cupertino, Palo Alto, Campbell)
    - East Bay (Oakland, Berkeley, Fremont, Alameda, Richmond)
    """
    today = datetime.datetime.now()
    weekday = today.strftime("%A")
    
    # South Bay and East Bay focused events - NO San Francisco events
    south_bay_events = [
        {"name": "San Jose Beer Week", "time": "Various times", "location": "Downtown San Jose", "cost": "Varies", "link": "https://www.sjbeerweek.com/"},
        {"name": "Santana Row Summer Concert", "time": "6pm", "location": "Santana Row, San Jose", "cost": "FREE", "link": "https://www.santanarow.com/events"},
        {"name": "Oakland First Fridays", "time": "5pm-9pm", "location": "Temescal District, Oakland", "cost": "FREE", "link": "https://oaklandfirstfridays.org/"},
        {"name": "Berkeley Art Museum Free Day", "time": "11am-7pm", "location": "UC Berkeley", "cost": "FREE", "link": "https://bampfa.org/"},
        {"name": "Fremont Street Eats", "time": "5pm-9pm", "location": "Downtown Fremont", "cost": "$", "link": "https://fremontstreeteats.com/"},
    ]
    
    east_bay_events = [
        {"name": "Jack London Square Farmers Market", "time": "9am-2pm", "location": "Jack London Square, Oakland", "cost": "FREE", "link": "https://jacklondonsquare.com/"},
        {"name": "Lake Merritt Morning Tai Chi", "time": "8am-9am", "location": "Lake Merritt, Oakland", "cost": "FREE", "link": "https://www.lakemerritt.org/"},
        {"name": "Berkeley Marina Kite Flying", "time": "11am-4pm", "location": "Berkeley Marina", "cost": "FREE", "link": "https://www.cityofberkeley.info/"},
        {"name": "Alameda Art Night", "time": "6pm-9pm", "location": "Alameda Naval Air Station", "cost": "FREE", "link": "https://www.alamedaca.gov/"},
        {"name": "Richmond Iron Triathalon Watch", "time": "7am", "location": "Richmond Marina", "cost": "FREE", "link": "https://www.ci.richmond.ca.us/"},
    ]
    
    # Combine and rotate based on day for variety
    all_events = south_bay_events + east_bay_events
    # Simple rotation based on day number
    start_idx = int(today.strftime("%d")) % len(all_events)
    rotated = all_events[start_idx:] + all_events[:start_idx]
    
    # Return 3-4 events, mixing South Bay and East Bay
    result = []
    for i, event in enumerate(rotated[:4]):
        result.append(event)
    
    return result


def fetch_yahoo_finance():
    """Fetch market data from Yahoo Finance"""
    try:
        # Try to use yfinance if available
        import subprocess
        
        # Check if yfinance is installed
        result = subprocess.run(
            ["python3", "-c", "import yfinance; print('ok')"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print("⚠️  yfinance not installed, using fallback finance data")
            return fetch_finance_fallback()
        
        # Use a simple script to fetch data
        script = '''
import yfinance as yf
import json
from datetime import datetime

# Major indices
tickers = {
    "S&P 500": "^GSPC",
    "Dow Jones": "^DJI",
    "Nasdaq": "^IXIC"
}

results = {}
for name, symbol in tickers.items():
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="5d")
        if len(hist) >= 2:
            current = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]
            change = ((current - prev) / prev) * 100
            results[name] = {
                "price": round(current, 2),
                "change": round(change, 2)
            }
    except Exception as e:
        results[name] = {"error": str(e)}

print(json.dumps(results))
'''
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0:
            market_data = json.loads(result.stdout)
            
            # Build talking points from live data
            talking_points = []
            for name, data in market_data.items():
                if "change" in data:
                    direction = "↑" if data["change"] > 0 else "↓"
                    talking_points.append(f"{name}: {direction} {data['change']}%")
            
            # Determine market summary
            if talking_points:
                summary = "Markets update: " + "; ".join(talking_points[:3])
            else:
                summary = "US stocks mixed as investors weigh economic data and corporate earnings."
            
            print(f"✓ Yahoo Finance: Live market data fetched")
            return {
                "market_summary": summary,
                "talking_points": talking_points if talking_points else [
                    "Markets showing mixed signals",
                    "Tech sector volatility continues",
                    "Fed policy expectations in focus"
                ],
                "link": "https://finance.yahoo.com/news/"
            }
        else:
            raise Exception("yfinance script failed")
            
    except Exception as e:
        print(f"⚠️  Yahoo Finance fetch failed: {e}")
        return fetch_finance_fallback()


def fetch_finance_fallback():
    """Fallback finance data"""
    return {
        "market_summary": "US markets update: S&P 500, Dow Jones, and Nasdaq showing mixed performance. Check Yahoo Finance for live data.",
        "talking_points": [
            "Markets showing mixed signals - check live data",
            "Tech sector volatility continues",
            "Fed policy expectations remain in focus"
        ],
        "link": "https://finance.yahoo.com/news/"
    }


def strip_html_tags(text):
    """Remove HTML tags and entities from text"""
    if not text:
        return ""
    
    import html
    
    class MLStripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.reset()
            self.fed = []
        def handle_data(self, d):
            self.fed.append(d)
        def get_data(self):
            return ''.join(self.fed)
    
    try:
        s = MLStripper()
        s.feed(text)
        result = s.get_data()
    except:
        # Fallback: simple regex
        import re
        result = re.sub(r'<[^>]+>', '', text)
    
    # Unescape HTML entities (&amp;, &lt;, etc.)
    result = html.unescape(result)
    
    # Clean up extra whitespace
    import re
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


def make_summary(text, min_sentences=2, max_sentences=3, max_chars=500):
    """Create a readable 2-3 sentence summary from text.
    
    Args:
        text: Raw text (may contain HTML)
        min_sentences: Minimum sentences to include
        max_sentences: Maximum sentences to include
        max_chars: Maximum characters for the summary
    """
    if not text:
        return ""
    
    import re
    
    # First strip any HTML
    clean_text = strip_html_tags(text)
    
    # Split into sentences (handle common endings)
    sentence_endings = r'(?<=[.!?])\s+(?=[A-Z"\'\(])'
    sentences = re.split(sentence_endings, clean_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        # Fallback: just truncate at word boundary
        if len(clean_text) > max_chars:
            return clean_text[:max_chars].rsplit(' ', 1)[0] + "..."
        return clean_text
    
    # Build summary with target sentence count
    summary_sentences = []
    total_len = 0
    
    for i, sentence in enumerate(sentences):
        if i >= max_sentences:
            break
        if i >= min_sentences and total_len + len(sentence) > max_chars:
            break
        summary_sentences.append(sentence)
        total_len += len(sentence) + 1
    
    summary = ' '.join(summary_sentences)
    
    # Ensure we don't exceed max_chars
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(' ', 1)[0] + "..."
    
    return summary


def get_source_label(source_name, link_type="article", article_title=""):
    """Generate a source-aware link label.
    
    Args:
        source_name: Name of the source (e.g., 'SF Chronicle', 'E! News')
        link_type: Type of content (article, details, directions, etc.)
        article_title: Title of the article for context (optional)
    """
    source_labels = {
        # Major Bay Area / California
        "SF Chronicle": "Read on SF Chronicle →",
        "San Francisco Chronicle": "Read on SF Chronicle →",
        "Mercury News": "Read on Mercury News →",
        "East Bay Times": "Read on East Bay Times →",
        "San Jose Mercury News": "Read on Mercury News →",
        "KQED": "Read on KQED →",
        "KTVU": "Read on KTVU →",
        "KRON": "Read on KRON 4 →",
        "ABC7": "Read on ABC7 Bay Area →",
        "NBC Bay Area": "Read on NBC Bay Area →",
        "Bay Area News Group": "Read on Bay Area News Group →",
        # Finance
        "Yahoo Finance": "Read full story on Yahoo Finance →",
        "Bloomberg": "Read on Bloomberg →",
        "Reuters": "Read on Reuters →",
        "CNBC": "Read on CNBC →",
        "Wall Street Journal": "Read on WSJ →",
        "WSJ": "Read on WSJ →",
        # Tech / World news
        "TechCrunch": "Read on TechCrunch →",
        "The Verge": "Read on The Verge →",
        "Wired": "Read on Wired →",
        "Ars Technica": "Read on Ars Technica →",
        "NPR": "Read on NPR →",
        "AP": "Read on AP News →",
        "Associated Press": "Read on AP News →",
        "BBC": "Read on BBC →",
        "The Guardian": "Read on The Guardian →",
        "Washington Post": "Read on Washington Post →",
        "NY Times": "Read on NY Times →",
        "New York Times": "Read on NY Times →",
        "Los Angeles Times": "Read on LA Times →",
        # Entertainment
        "E! News": "Read on E! Online →",
        "E! Online": "Read on E! Online →",
        "People": "Read on People →",
        "Variety": "Read on Variety →",
        "Hollywood Reporter": "Read on Hollywood Reporter →",
        # Other
        "FuncheapSF": "See event details →",
        "Wikipedia": "Read more on Wikipedia →",
        "BART": "Check BART schedule →",
        "Google Maps": "View on Google Maps →",
        "Yelp": "View on Yelp →",
    }
    
    # Try to match known source
    for known_source, label in source_labels.items():
        if known_source.lower() in source_name.lower():
            return label
    
    # Generic fallbacks based on link type
    type_labels = {
        "article": f"Read more on {source_name} →",
        "details": "View details →",
        "directions": "Get directions →",
        "menu": "View menu & info →",
        "event": "See event details →",
    }
    
    return type_labels.get(link_type, f"Read more on {source_name} →")


def fetch_entertainment_news():
    """Fetch entertainment news from E! News RSS"""
    import xml.etree.ElementTree as ET
    
    try:
        # Try E! News RSS
        url = "https://www.eonline.com/rss"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_content = response.read().decode('utf-8')
            root = ET.fromstring(xml_content)
            
            gossip = []
            for item in root.findall('.//item')[:3]:
                title = item.find('title')
                desc = item.find('description')
                link = item.find('link')
                
                if title is not None:
                    # Clean up description - strip HTML tags and make 2-3 sentence summary
                    content = ""
                    if desc is not None and desc.text:
                        content = make_summary(desc.text, min_sentences=2, max_sentences=3)
                    else:
                        content = "Latest entertainment news from E! Online."
                    
                    gossip.append({
                        "title": strip_html_tags(title.text),
                        "content": content,
                        "link": link.text if link is not None else "https://www.eonline.com/news/"
                    })
            
            print(f"✓ E! News RSS: {len(gossip)} stories fetched")
            return gossip
            
    except Exception as e:
        print(f"⚠️  E! News fetch failed: {e}")
        return fetch_gossip_fallback()


def fetch_gossip_fallback():
    """Fallback gossip"""
    return [
        {
            "title": "Entertainment News",
            "content": "Latest Hollywood buzz and celebrity updates from E! Online.",
            "link": "https://www.eonline.com/news/"
        },
        {
            "title": "Tech Industry Buzz",
            "content": "Silicon Valley rumors and startup news making the rounds.",
            "link": "https://www.theverge.com/tech/"
        }
    ]


def fetch_google_scenic():
    """Fetch scenic spots using Google Places API, fallback to Google Maps CDP"""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        print("⚠️  Google API key not set, using Google Maps CDP fallback")
        return fetch_google_maps_scenic_fallback()
    
    try:
        # Search for tourist attractions and parks near San Jose
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        
        scenic_spots = []
        
        # Search for different types
        place_types = ["park", "tourist_attraction", "natural_feature"]
        
        for place_type in place_types[:2]:  # Limit to 2 types to save quota
            params = {
                "location": f"{CONFIG['lat']},{CONFIG['lng']}",
                "radius": "50000",  # 50km radius
                "type": place_type,
                "key": api_key
            }
            
            query_string = urllib.parse.urlencode(params)
            req = urllib.request.Request(f"{url}?{query_string}")
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                for place in data.get('results', [])[:3]:
                    name = place.get('name', 'Unknown')
                    
                    # Determine if free
                    cost = "FREE"
                    
                    scenic_spots.append({
                        "name": name,
                        "location": place.get('vicinity', 'Bay Area'),
                        "cost": cost,
                        "notes": f"Rating: {place.get('rating', 'N/A')}/5. {place.get('user_ratings_total', 0)} reviews",
                        "link": f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id', '')}"
                    })
        
        if scenic_spots:
            print(f"✓ Google Places API: {len(scenic_spots)} scenic spots fetched")
            return scenic_spots[:5]
        else:
            return fetch_google_maps_scenic_fallback()
            
    except Exception as e:
        print(f"⚠️  Google Places API failed: {e}")
        return fetch_google_maps_scenic_fallback()


def fetch_google_maps_scenic_fallback():
    """Fallback using Google Maps CDP scraper for scenic spots"""
    try:
        import subprocess
        import json
        from pathlib import Path
        
        # Run the Google Maps scraper
        script_path = Path(__file__).parent / "google_maps_scraper.py"
        result = subprocess.run(
            ["python3", str(script_path), "--type", "scenic", 
             "--location", "Bay Area", "--count", "5", "--newsletter-format"],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # Parse JSON output (skip connection lines, find the JSON array)
        output = result.stdout
        # Find the start of JSON array
        json_start = output.find('[')
        if json_start >= 0:
            spots = json.loads(output[json_start:])
            if spots:
                print(f"✓ Google Maps CDP: {len(spots)} scenic spots fetched")
                # Fill in missing fields with defaults
                for s in spots:
                    if not s.get('cost'):
                        s['cost'] = 'FREE'
                return spots[:5]
        
        # If we couldn't parse or got empty results, use static fallback
        print("⚠️  Google Maps CDP returned no scenic results, using static fallback")
        return fetch_scenic_fallback()
        
    except Exception as e:
        print(f"⚠️  Google Maps CDP scenic failed: {e}")
        return fetch_scenic_fallback()


def fetch_scenic_fallback():
    """Fallback scenic spots — South Bay and East Bay focused, no SF spots"""
    return [
        {
            "name": "Cupertino Falls",
            "location": "Cupertino (Mary Ave)",
            "cost": "FREE",
            "notes": "Hidden waterfall in residential neighborhood, best after rain",
            "link": "https://www.google.com/maps/search/?api=1&query=Cupertino+Falls"
        },
        {
            "name": "San Jose Rose Garden",
            "location": "San Jose (Almaden Valley)",
            "cost": "FREE",
            "notes": "10,000 rose bushes, peak bloom May-June, great for photos",
            "link": "https://www.google.com/maps/search/?api=1&query=San+Jose+Municipal+Rose+Garden"
        },
        {
            "name": "Shoreline Park",
            "location": "Mountain View",
            "cost": "FREE",
            "notes": "Lake views, Shoreline Amphitheatre backdrop, sunrise/sunset photos",
            "link": "https://www.google.com/maps/search/?api=1&query=Shoreline+Park+Mountain+View+CA"
        },
        {
            "name": "Alviso Marina",
            "location": "San Jose (North)",
            "cost": "FREE",
            "notes": "Hidden gem, salt ponds, boardwalk trails, urban exploration content",
            "link": "https://www.google.com/maps/search/?api=1&query=Alviso+Marina+County+Park+San+Jose"
        },
        {
            "name": "Henry Cowell Redwoods",
            "location": "Felton (Santa Cruz Mountains)",
            "cost": "$10 parking",
            "notes": "Closer than Muir Woods from South Bay, easy loop trail",
            "link": "https://www.google.com/maps/search/?api=1&query=Henry+Cowell+Redwoods+State+Park"
        }
    ]


def fetch_wikipedia_history(today_info):
    """Fetch today's history from Wikipedia API"""
    try:
        month = today_info['month_num']
        day = today_info['day_num']
        
        # Try Wikipedia On This Day API with correct endpoint
        url = f"https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/all/{month:02d}/{day:02d}"
        
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; NewsletterBot/1.0)',
            'Accept': 'application/json'
        })
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            # Get events from 'selected' list
            events = data.get('selected', [])
            if not events:
                events = data.get('events', [])
            if not events:
                events = data.get('births', []) + data.get('deaths', [])
            
            if events:
                event = events[0]  # Get top event
                year = event.get('year', '')
                text = event.get('text', '')
                
                # Get pages for link
                pages = event.get('pages', [])
                link = f"https://en.wikipedia.org/wiki/{today_info['month']}_{today_info['day']}"
                if pages and len(pages) > 0:
                    page_title = pages[0].get('normalizedtitle', pages[0].get('title', ''))
                    if page_title:
                        link = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"
                
                print(f"✓ Wikipedia API: History fetched for {month}/{day}")
                return {
                    "title": f"{today_info['month']} {today_info['day']}, {year}: {strip_html_tags(text)[:60]}...",
                    "summary": make_summary(text, min_sentences=2, max_sentences=3, max_chars=400),
                    "fun_fact": f"This happened {datetime.datetime.now().year - int(year)} years ago." if str(year).isdigit() else "",
                    "link": link
                }
            else:
                return fetch_history_fallback(today_info)
                
    except Exception as e:
        print(f"⚠️  Wikipedia API failed: {e}")
        return fetch_history_fallback(today_info)


def fetch_history_fallback(today_info):
    """Enhanced fallback with curated historical events by date"""
    import random
    
    month = today_info.get('month_num', 1)
    day = today_info.get('day_num', 1)
    month_name = today_info.get('month', 'January')
    
    # Curated historical events organized by month/day
    historical_events = {
        # January
        (1, 1): {"year": "1901", "event": "The Commonwealth of Australia is formed.", "fact": "Australia was the first continent to usher in the 20th century as a unified nation."},
        (1, 15): {"year": "1929", "event": "Martin Luther King Jr. is born in Atlanta, Georgia.", "fact": "King's 'I Have a Dream' speech is one of the most famous in American history."},
        (1, 28): {"year": "1986", "event": "The Space Shuttle Challenger breaks apart 73 seconds after launch.", "fact": "All seven crew members perished in the disaster."},
        
        # February
        (2, 4): {"year": "2004", "event": "Facebook is launched by Mark Zuckerberg from his Harvard dorm.", "fact": "Facebook now has over 3 billion monthly active users worldwide."},
        (2, 14): {"year": "1929", "event": "The St. Valentine's Day Massacre occurs in Chicago.", "fact": "Seven rivals of Al Capone were killed in the infamous Prohibition-era crime."},
        (2, 20): {"year": "1962", "event": "John Glenn becomes the first American to orbit Earth.", "fact": "Glenn circled the planet three times in just under five hours."},
        
        # March
        (3, 5): {"year": "1970", "event": "The Nuclear Non-Proliferation Treaty goes into effect.", "fact": "189 countries are now parties to this landmark arms control treaty."},
        (3, 14): {"year": "2018", "event": "Stephen Hawking, renowned physicist, passes away.", "fact": "Hawking was diagnosed with ALS at 21 and given just two years to live."},
        (3, 20): {"year": "1969", "event": "John Lennon and Yoko Ono marry in Gibraltar.", "fact": "Their honeymoon became famous for its 'Bed-In for Peace' protests."},
        (3, 26): {"year": "1979", "event": "Anwar Sadat and Menachem Begin sign the Egypt-Israel Peace Treaty.", "fact": "This was the first peace treaty between Israel and an Arab nation."},
        
        # April
        (4, 1): {"year": "1976", "event": "Steve Jobs and Steve Wozniak found Apple Computer.", "fact": "They started in Jobs' parents' garage with $1,300."},
        (4, 12): {"year": "1961", "event": "Yuri Gagarin becomes the first human in space.", "fact": "The Soviet cosmonaut completed one orbit of Earth in 108 minutes."},
        (4, 26): {"year": "1986", "event": "The Chernobyl disaster occurs in Ukraine.", "fact": "It remains the worst nuclear power plant accident in history."},
        
        # May
        (5, 5): {"year": "1961", "event": "Alan Shepard becomes the first American in space.", "fact": "His 15-minute suborbital flight made him a national hero."},
        (5, 22): {"year": "1849", "event": "Abraham Lincoln receives patent for buoying vessels.", "fact": "He's the only US president to hold a patent."},
        (5, 29): {"year": "1953", "event": "Sir Edmund Hillary and Tenzing Norgay reach Everest's summit.", "fact": "The mountain had defeated all previous attempts for decades."},
        
        # June
        (6, 6): {"year": "1944", "event": "D-Day: Allied forces land in Normandy, France.", "fact": "Over 150,000 troops participated in the largest seaborne invasion in history."},
        (6, 18): {"year": "1983", "event": "Sally Ride becomes the first American woman in space.", "fact": "Ride was only 32, making her the youngest American astronaut at the time."},
        (6, 28): {"year": "1919", "event": "The Treaty of Versailles is signed, ending WWI.", "fact": "The treaty redrew the map of Europe and imposed heavy reparations on Germany."},
        
        # July
        (7, 4): {"year": "1776", "event": "The United States Declaration of Independence is adopted.", "fact": "Most delegates actually signed the document on August 2, not July 4."},
        (7, 20): {"year": "1969", "event": "Neil Armstrong becomes the first human to walk on the moon.", "fact": "Armstrong's famous 'one small step' quote was slightly misquoted for years."},
        (7, 27): {"year": "1953", "event": "The Korean War armistice is signed.", "fact": "Technically, North and South Korea are still at war — no peace treaty was ever signed."},
        
        # August
        (8, 6): {"year": "1945", "event": "The first atomic bomb is dropped on Hiroshima, Japan.", "fact": "The bomb, codenamed 'Little Boy,' killed an estimated 140,000 people."},
        (8, 18): {"year": "1920", "event": "The 19th Amendment is ratified, granting women the right to vote.", "fact": "Tennessee's vote was the deciding one — by a margin of just one vote!"},
        (8, 28): {"year": "1963", "event": "Martin Luther King Jr. delivers his 'I Have a Dream' speech.", "fact": "The speech was partly improvised, including the famous dream sequence."},
        
        # September
        (9, 2): {"year": "1945", "event": "WWII officially ends with Japan's formal surrender.", "fact": "The ceremony took place aboard the USS Missouri in Tokyo Bay."},
        (9, 11): {"year": "2001", "event": "Terrorist attacks devastate the World Trade Center and Pentagon.", "fact": "Nearly 3,000 people from over 90 countries lost their lives."},
        (9, 22): {"year": "1862", "event": "Lincoln issues the preliminary Emancipation Proclamation.", "fact": "It declared that all slaves in Confederate states would be free."},
        (9, 26): {"year": "1960", "event": "The first televised presidential debate: Kennedy vs. Nixon.", "fact": "Many believe Kennedy's telegenic appearance won him the presidency."},
        
        # October
        (10, 1): {"year": "1971", "event": "Walt Disney World opens in Florida.", "fact": "The resort is twice the size of Manhattan."},
        (10, 4): {"year": "1957", "event": "Sputnik 1 becomes the first artificial satellite to orbit Earth.", "fact": "This Soviet achievement launched the Space Age."},
        (10, 29): {"year": "1929", "event": "Black Tuesday: Stock market crash begins the Great Depression.", "fact": "The market lost $14 billion in value in a single day."},
        
        # November
        (11, 9): {"year": "1989", "event": "The Berlin Wall falls, reuniting East and West Berlin.", "fact": "The wall had divided the city for 28 years."},
        (11, 11): {"year": "1918", "event": "WWI ends with the armistice taking effect.", "fact": "The war claimed over 16 million lives in four years."},
        (11, 22): {"year": "1963", "event": "President John F. Kennedy is assassinated in Dallas.", "fact": "Lee Harvey Oswald was arrested but was killed two days later before trial."},
        
        # December
        (12, 7): {"year": "1941", "event": "Japan attacks Pearl Harbor, bringing the US into WWII.", "fact": "2,403 Americans died in the surprise attack on the Hawaiian naval base."},
        (12, 17): {"year": "1903", "event": "The Wright Brothers make the first powered flight.", "fact": "The first flight lasted just 12 seconds and covered 120 feet."},
        (12, 25): {"year": "1776", "event": "Washington crosses the Delaware in a daring Christmas raid.", "fact": "The surprise attack captured 1,000 Hessian soldiers."},
    }
    
    # Try to match exact date, otherwise pick a notable event
    event = historical_events.get((month, day))
    if not event:
        # Pick a rotating event based on day of month
        all_events = list(historical_events.values())
        event = all_events[day % len(all_events)]
    
    return {
        "title": f"{month_name} {day}, {event['year']}: {event['event']}",
        "summary": event['event'],
        "fun_fact": event['fact'],
        "link": f"https://en.wikipedia.org/wiki/{month_name}_{day}"
    }


# ========== EXISTING FUNCTIONS ==========

def fetch_world_news_newsapi():
    """Fetch top world news from NewsAPI"""
    api_key = os.getenv("NEWSAPI_KEY", "")
    if not api_key:
        return []
    
    url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize=5&apiKey={api_key}"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if data.get('status') != 'ok':
                return []
            
            articles = []
            for article in data.get('articles', [])[:3]:
                source = article.get('source', {}).get('name', 'News')
                raw_desc = article.get('description', '')
                # Combine title + description for richer summary
                summary_text = f"{article.get('title', '')}. {raw_desc}" if raw_desc else article.get('title', '')
                articles.append({
                    "title": strip_html_tags(article.get('title', 'No title')),
                    "summary": make_summary(summary_text, min_sentences=2, max_sentences=3),
                    "link": article.get('url', '#'),
                    "source": source
                })
            return articles
    except Exception as e:
        return []


def fetch_world_news_rss():
    """Fetch news from Google News RSS as backup"""
    import xml.etree.ElementTree as ET
    
    search_terms = [
        "us politics today",
        "world news"
    ]
    
    all_articles = []
    
    for term in search_terms:
        try:
            encoded_term = urllib.parse.quote(term)
            url = f"https://news.google.com/rss/search?q={encoded_term}&hl=en-US&gl=US"
            
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_content = response.read().decode('utf-8')
                root = ET.fromstring(xml_content)
                
                for item in root.findall('.//item')[:2]:
                    title = item.find('title')
                    desc = item.find('description')
                    link = item.find('link')
                    source_elem = item.find('source')
                    
                    if title is not None and link is not None:
                        title_text = title.text.split(' - ')[0] if ' - ' in title.text else title.text
                        source = source_elem.text if source_elem is not None else 'News'
                        # Combine title + description for richer summary
                        raw_text = desc.text if desc is not None else title_text
                        all_articles.append({
                            "title": strip_html_tags(title_text),
                            "summary": make_summary(raw_text, min_sentences=2, max_sentences=3),
                            "link": link.text,
                            "source": source
                        })
        except Exception as e:
            continue
    
    seen = set()
    unique = []
    for article in all_articles:
        if article['title'] not in seen:
            seen.add(article['title'])
            unique.append(article)
    
    return unique[:3]


def fetch_world_news():
    """Fetch world news from both sources"""
    print("📰 Fetching world news...")
    
    newsapi_articles = fetch_world_news_newsapi()
    rss_articles = fetch_world_news_rss()
    
    combined = newsapi_articles[:2] if newsapi_articles else []
    
    newsapi_titles = {a['title'].lower() for a in combined}
    for article in rss_articles:
        if article['title'].lower() not in newsapi_titles and len(combined) < 3:
            combined.append(article)
    
    if not combined:
        return [
            {"title": "US News Update", "summary": "Latest news from across the United States.", "link": "https://news.google.com/"},
            {"title": "World News", "summary": "International news and global updates.", "link": "https://news.google.com/"}
        ]
    
    return combined


def fetch_bay_area_news_rss():
    """Fetch Bay Area news from RSS feeds with South Bay/East Bay prioritization.
    
    Scoring strategy:
    - South Bay feeds: +8 bonus (primary target audience location)
    - East Bay feeds: +6 bonus 
    - Bay Area feeds (KQED): +3 bonus
    - SF feed: -10 penalty (de-prioritize unless major/regional story)
    - Keyword matches in South Bay/East Bay: additional +5 boost
    - SF-only keywords: -5 if from SF feed (further de-prioritize SF-centric stories)
    
    Articles are filtered if:
    - SF article has no South Bay/East Bay keywords AND score is low
    - OR South Bay/East Bay articles exist and SF article is not clearly major
    """
    import xml.etree.ElementTree as ET
    
    rss_feeds = [
        {"name": "Mercury News", "url": "https://www.mercurynews.com/feed/", "region": "South Bay"},
        {"name": "East Bay Times", "url": "https://www.eastbaytimes.com/feed/", "region": "East Bay"},
        {"name": "KQED", "url": "https://www.kqed.org/news/rss", "region": "Bay Area"},
        {"name": "SF Chronicle", "url": "https://www.sfchronicle.com/rss/feed/Top-Stories-1515.php", "region": "SF"},
    ]
    
    # Keywords to skip (unimportant/repetitive stories)
    skip_keywords = ['sniper', 'shooting', 'arrested', 'crime', 'police', 'homicide', 'murder']
    
    # South Bay/East Bay keywords to prioritize
    south_bay_keywords = ['san jose', 'palo alto', 'mountain view', 'cupertino', 'sunnyvale', 
                          'santa clara', 'campbell', 'los gatos', ' Saratoga ', 'milpitas', 
                          'sunnyvale', 'los altos', 'menlo park']
    east_bay_keywords = ['oakland', 'berkeley', 'fremont', 'newark', 'alameda', 'emeryville', 
                         'richmond', 'el cerrito', 'albany', 'piedmont', 'walnut creek', 
                         'contra costa', 'tri valley']
    peninsula_keywords = ['peninsula', 'san mateo', 'redwood city', 'burlingame', 'hillsborough',
                         'san carlos', 'foster city', 'belmont', 'san bruno', 'daly city']
    
    # SF-only keywords that indicate a story is SF-centric (negative signal)
    sf_only_keywords = ['soma', 'mission district', 'haight', 'castro', 'marina district',
                       'nob hill', 'tenderloin', 'richmond district', 'sunset district',
                       'north beach', 'chinatown sf', 'fisherman', 'presidio', 'golden gate park',
                       'sf only', 'san francisco only']
    
    all_articles = []
    south_bay_articles = []
    east_bay_articles = []
    other_articles = []
    seen_titles = set()
    
    for feed in rss_feeds:
        try:
            req = urllib.request.Request(feed['url'], headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_content = response.read().decode('utf-8')
                root = ET.fromstring(xml_content)
                
                for item in root.findall('.//item')[:5]:  # Check more items for filtering
                    title = item.find('title')
                    desc = item.find('description')
                    link = item.find('link')
                    
                    if title is None:
                        continue
                    
                    title_text = title.text.split(' - ')[0] if ' - ' in title.text else title.text
                    title_lower = title_text.lower()
                    
                    # Skip duplicates
                    if title_text in seen_titles:
                        continue
                    
                    # Skip unimportant stories
                    if any(keyword in title_lower for keyword in skip_keywords):
                        continue
                    
                    # Calculate score based on multiple factors
                    score = 0
                    is_sf_article = feed['region'] == 'SF'
                    has_south_bay_keyword = any(kw in title_lower for kw in south_bay_keywords)
                    has_east_bay_keyword = any(kw in title_lower for kw in east_bay_keywords)
                    has_peninsula_keyword = any(kw in title_lower for kw in peninsula_keywords)
                    has_sf_only_keyword = any(kw in title_lower for kw in sf_only_keywords)
                    
                    # Region-based scoring
                    if feed['region'] == 'South Bay':
                        score += 8
                    elif feed['region'] == 'East Bay':
                        score += 6
                    elif feed['region'] == 'Bay Area':
                        score += 3
                    elif is_sf_article:
                        score -= 10  # Heavy penalty for SF-only feeds
                    
                    # Keyword-based scoring boosts
                    if has_south_bay_keyword:
                        score += 5
                    if has_east_bay_keyword:
                        score += 4
                    if has_peninsula_keyword:
                        score += 2
                    
                    # SF-only keyword penalty (further de-prioritize SF-centric stories)
                    if is_sf_article and has_sf_only_keyword:
                        score -= 5
                    
                    # Skip SF articles that have no South Bay/East Bay relevance
                    # UNLESS they mention California-wide or Bay Area-wide topics
                    if is_sf_article and not (has_south_bay_keyword or has_east_bay_keyword or has_peninsula_keyword):
                        # Only allow SF articles that are clearly major (score still decent after penalty)
                        # or that mention "bay area", "california", "silicon valley", "tech" broadly
                        bay_area_broad = any(kw in title_lower for kw in ['bay area', 'california', 'silicon valley', 'tech industry', 'west coast'])
                        if score < 3 and not bay_area_broad:
                            continue  # Skip purely SF-centric low-relevance articles
                    
                    seen_titles.add(title_text)
                    article = {
                        "title": title_text,
                        "summary": make_summary(desc.text, min_sentences=2, max_sentences=3) if desc is not None and desc.text else f"Latest from {feed['name']}.",
                        "link": link.text if link is not None else '#',
                        "source": feed['name'],
                        "region": feed['region'],
                        "score": score
                    }
                    
                    # Categorize for balanced selection
                    if feed['region'] == 'South Bay' or has_south_bay_keyword:
                        south_bay_articles.append(article)
                    elif feed['region'] == 'East Bay' or has_east_bay_keyword:
                        east_bay_articles.append(article)
                    else:
                        other_articles.append(article)
                        
        except Exception as e:
            continue
    
    # Prioritize South Bay then East Bay, fill remaining slots with others
    result = []
    used_regions = set()
    
    # Add top South Bay articles first (up to 2)
    south_bay_articles.sort(key=lambda x: x['score'], reverse=True)
    for art in south_bay_articles[:2]:
        result.append(art)
    
    # Add top East Bay articles (up to 2)
    east_bay_articles.sort(key=lambda x: x['score'], reverse=True)
    for art in east_bay_articles[:2]:
        result.append(art)
    
    # Add other articles only if we need more (up to 2)
    other_articles.sort(key=lambda x: x['score'], reverse=True)
    for art in other_articles[:2]:
        if len(result) < 4:  # Max 4 articles
            result.append(art)
    
    return result[:3] if result else []


def fetch_bay_area_news():
    """Fetch Bay Area specific news"""
    print("📰 Fetching Bay Area news...")
    articles = fetch_bay_area_news_rss()
    
    if articles:
        return articles
    
    return [
        {"title": "Bay Area News", "summary": "Latest updates from the San Francisco Bay Area.", "link": "https://www.mercurynews.com/"}
    ]


def generate_html_email(today_info, world_news, bay_news, finance, gossip, restaurants, scenic, events, history, bart_info=None, newsletter_id=None):
    """Generate HTML email content
    
    Args:
        today_info: Dictionary with date information
        world_news, bay_news, finance, gossip, restaurants, scenic, events, history: Content data
        bart_info: Optional BART transit info
        newsletter_id: Optional newsletter tracking ID for feedback attribution
    """
    
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lily's Daily Brief</title>
<style>
/* === BASE RESET & RESPONSIVE CONTAINER === */
body {{ font-family: Arial, Helvetica, sans-serif; line-height: 1.6; color: #333; background: #ffffff; margin: 0; padding: 0; }}
.email-wrapper {{ max-width: 600px; margin: 0 auto; width: 100%; }}

/* === RESPONSIVE TYPOGRAPHY === */
body {{ font-size: 16px; }}
h2 {{ color: #2c5aa0; border-bottom: 2px solid #2c5aa0; padding-bottom: 5px; margin-top: 30px; font-size: 20px; }}
h3 {{ color: #555; margin-bottom: 8px; font-size: 16px; }}
p {{ margin: 10px 0; }}

/* === SECTIONS === */
.section {{ margin-bottom: 25px; background: #ffffff; padding: 0 5px; }}
.event {{ margin: 8px 0; line-height: 1.5; }}
.restaurant {{ margin: 15px 0; padding: 12px 10px; background: #f5f5f5; border-radius: 8px; }}

/* === LINKS & TOUCH TARGETS === */
a {{ color: #2c5aa0; text-decoration: underline; display: inline-block; min-height: 44px; min-width: 44px; line-height: 44px; }}
p > a, li > a {{ min-height: 0; min-width: 0; line-height: 1.4; }}
.live-badge {{ background: #28a745; color: white; font-size: 10px; padding: 3px 8px; border-radius: 3px; margin-left: 5px; vertical-align: middle; }}
.curated-badge {{ background: #6c757d; color: white; font-size: 10px; padding: 3px 8px; border-radius: 3px; margin-left: 5px; vertical-align: middle; }}
.daily-badge {{ background: #17a2b8; color: white; font-size: 10px; padding: 3px 8px; border-radius: 3px; margin-left: 5px; vertical-align: middle; }}

/* === PRICES & BADGES === */
.price {{ color: #28a745; font-weight: bold; }}
.cost-free {{ color: #28a745; font-weight: bold; }}

/* === FEEDBACK BUTTONS === */
.feedback-btn {{ display: inline-block; padding: 8px 16px; margin: 4px 2px; border-radius: 6px; font-size: 14px; font-weight: bold; text-decoration: none; min-height: 44px; min-width: 80px; text-align: center; line-height: 28px; }}
.feedback-btn.loved {{ background: #28a745; color: white; }}
.feedback-btn.skip {{ background: #dc3545; color: white; }}
.feedback-btn:hover {{ opacity: 0.85; }}

/* === CONDITIONS BANNER === */
.conditions-banner {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 15px; border-radius: 10px; margin-bottom: 25px; }}
.conditions-banner h2 {{ color: white; border-bottom: 1px solid rgba(255,255,255,0.3); margin-top: 0; }}
.conditions-banner a {{ color: white; min-height: 0; min-width: 0; line-height: 1.4; }}

/* === RESPONSIVE MOBILE === */
@media (max-width: 480px) {{
  body {{ font-size: 15px; padding: 10px; }}
  h2 {{ font-size: 18px; }}
  h3 {{ font-size: 15px; }}
  .section {{ padding: 0; }}
  .restaurant {{ padding: 10px 8px; }}
  .conditions-banner {{ padding: 15px 12px; }}
  a {{ min-height: 44px; min-width: 44px; line-height: 44px; }}
  p > a, li > a {{ min-height: 44px; min-width: 44px; }}
  .feedback-btn {{ padding: 10px 14px; font-size: 15px; }}
  pre {{ font-size: 13px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }}
}}

/* === DARK MODE === */
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a1a; color: #e0e0e0; }}
  h2 {{ color: #6ab0ff; border-bottom-color: #6ab0ff; }}
  h3 {{ color: #b0b0b0; }}
  a {{ color: #7ec8ff; }}
  .section {{ background: #1a1a1a; }}
  .restaurant {{ background: #2a2a2a; color: #e0e0e0; }}
  .price {{ color: #5cb85c; }}
  .cost-free {{ color: #5cb85c; }}
  .live-badge {{ background: #5cb85c; }}
  .curated-badge {{ background: #495057; }}
  .daily-badge {{ background: #138496; }}
  .conditions-banner {{ background: linear-gradient(135deg, #4a5568 0%, #2d3748 100%); }}
  .conditions-banner h2 {{ color: white; }}
  .feedback-btn.loved {{ background: #5cb85c; }}
  .feedback-btn.skip {{ background: #e53e3e; }}
}}

/* === OUTLOOK MSO CONDITIONALS === */
/* Force 600px width in Outlook */
{{email-wrapper: max-width: 600px;}}
</style>
</head>
<body>
<!--[if mso]>
<table role="presentation" border="0" cellspacing="0" cellpadding="0" width="600" style="width:600px;"><tr><td>
<![endif]-->
<div class="email-wrapper">

<!-- Email preheader (hidden in most clients) -->
<div style="display:none;font-size:1px;color:#ffffff;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
🌅 Today's Brief: Bay Area news, markets, weather, restaurants, events &amp; more — {today_info['display_date']}
</div>

<p>Hi Lily,</p>

<p>Here's your daily brief for <strong>{today_info['display_date']}</strong>.</p>

{fetch_sunny_conditions_html()}

<div class="section">
<h2>🌉 BAY AREA NEWS <span class="live-badge">LIVE</span></h2>
<p><em>Live headlines from South Bay, East Bay, and Bay Area sources</em></p>
"""
    
    for item in bay_news:
        source_label = get_source_label(item.get('source', 'News'), 'article')
        html += f"""
<h3>{item['title']}</h3>
<p>{item['summary']} <a href="{item['link']}">{source_label}</a></p>
"""
    
    html += """
</div>

<div class="section">
<h2>💰 FINANCE NOTES <span class="live-badge">LIVE</span></h2>
<p><em>Live market data from Yahoo Finance, with curated talking points</em></p>
"""
    html += f"""
<h3>Markets This Week</h3>
<p>{finance['market_summary']}</p>
<p><strong>Talking Points:</strong></p>
"""
    for point in finance['talking_points']:
        html += f"<p>• {point}</p>\n"
    html += f"""<p><a href="{finance['link']}">Full article on Yahoo Finance →</a></p>
</div>
"""
    
    html += """
<div class="section">
<h2>🎭 POP CULTURE HIGHLIGHTS <span style="background: #6c757d; color: white; font-size: 10px; padding: 3px 8px; border-radius: 3px; margin-left: 5px; vertical-align: middle;">CURATED</span></h2>
<p><em>Lily's curated picks from the entertainment world — refreshed weekly</em></p>
"""
    for item in gossip:
        gossip_label = get_source_label('E! Online', 'article')
        html += f"""
<h3>{item['title']}</h3>
<p>{item['content']} <a href="{item['link']}">{gossip_label}</a></p>
"""
    html += """
</div>
"""
    
    html += """
<div class="section">
<h2>🌍 WORLD NEWS <span class="live-badge">LIVE</span></h2>
<p><em>Breaking headlines from US and global sources</em></p>
"""
    for item in world_news:
        source = item.get('source', 'News')
        source_label = get_source_label(source, 'article')
        html += f"""
<h3>{item['title']}</h3>
<p>{item['summary']} <a href="{item['link']}">{source_label}</a></p>
"""
    html += """
</div>
"""
    
    html += """
<div class="section">
<h2>🍽️ LILY'S FAVORITE RESTAURANTS — South Bay & Peninsula <span style="background: #6c757d; color: white; font-size: 10px; padding: 3px 8px; border-radius: 3px; margin-left: 5px; vertical-align: middle;">CURATED</span></h2>
<p><em>Handpicked spots worth trying — updated monthly</em></p>
"""
    for r in restaurants:
        score = get_item_score(r['name'])
        score_tag = f" <span style='color: #888; font-size: 12px;'>(score: {score})</span>" if score != 0 else ""
        yelp_label = get_source_label('Yelp', 'menu')
        # Add tracking URL for restaurant
        tracking_url = get_tracking_url(r['link'], 'restaurant', r['name'])
        html += f"""
<div class="restaurant">
<h3>{r['name']} — {r['location']}{score_tag}</h3>
<p><span class="price">{r['price']}</span> • {r['type']}</p>
<p>{r['notes']}</p>
<p><a href="{tracking_url}">{yelp_label}</a>{add_feedback_buttons(r['name'], 'restaurant', newsletter_id)}</p>
</div>
"""
    html += """
</div>
"""
    
    html += """
<div class="section">
<!--
  ROOT CAUSE: "photo isn't loading" complaint.
  The 📸 emoji and title "Photo Gold!" set an expectation of embedded <img> tags.
  However, this section only generates text listings with links—no actual images.
  This is a CONTENT EXPECTATION MISMATCH, not a broken image resource.
  Future fix: fetch photos from Google Places API or use curated static image URLs.
-->
<h2>📸 LILY'S SCENIC SPOT PICKS — Photo Gold! <span style="background: #6c757d; color: white; font-size: 10px; padding: 3px 8px; border-radius: 3px; margin-left: 5px; vertical-align: middle;">CURATED</span></h2>
<p><em>Handpicked local gems worth exploring — updated seasonally</em></p>
"""
    for spot in scenic:
        maps_label = get_source_label('Google Maps', 'directions')
        # Add tracking URL for scenic spot
        tracking_url = get_tracking_url(spot['link'], 'scenic', spot['name'])
        html += f"""
<h3>{spot['name']}</h3>
<p><span class="cost-free">{spot['cost']}</span> • {spot['location']}</p>
<p>{spot['notes']}</p>
<p><a href="{tracking_url}">{maps_label}</a>{add_feedback_buttons(spot['name'], 'scenic', newsletter_id)}</p>
"""
    html += """
</div>
"""
    
    html += f"""
<div class="section">
<h2>🎉 LILY'S WEEKLY EVENT PICKS — {today_info['weekday'].upper()}, {today_info['month']} {today_info['day']} <span class="live-badge">LIVE</span></h2>
<p><em>Today's best options from FuncheapSF — curated for South Bay accessibility</em></p>
"""
    if events:
        for event in events:
            score = get_item_score(event['name'])
            score_tag = f" <span style='color: #888; font-size: 12px;'>(score: {score})</span>" if score != 0 else ""
            event_label = get_source_label('FuncheapSF', 'event')
            # Add tracking URL for event
            tracking_url = get_tracking_url(event['link'], 'event', event['name'])
            html += f"""
<div class="event">
<p><strong>{event['name']}</strong>{score_tag} — {event['time']} @ {event['location']} <span class="cost-free">{event['cost']}</span></p>
<p><a href="{tracking_url}">{event_label}</a>{add_feedback_buttons(event['name'], 'event', newsletter_id)}</p>
</div>
"""
    else:
        html += "<p>No major events found for today. Check the full calendar!</p>\n"
    
    html += """<p>Full calendar: <a href="https://sf.funcheap.com/">sf.funcheap.com →</a></p>
</div>
"""
    
    # Oakland Commute Section (BART + Traffic)
    html += """
<div class="section">
<h2>🚇 OAKLAND COMMUTE — Live BART <span class="live-badge">LIVE</span></h2>
<p><em>Real-time transit data from BART and 511.org</em></p>
"""
    if bart_info:
        # BART Departures to Oakland corridor
        oakland_text = bart_info.get('oakland_corridor_text', '') or bart_info.get('departures_text', '')
        if oakland_text:
            html += f"<p><strong>Berryessa → Oakland:</strong> {oakland_text}</p>\n"
        else:
            html += "<p><em>BART service info temporarily unavailable.</em></p>\n"
        
        # Service alerts (only if meaningful - skip "No significant delays")
        alerts_text = bart_info.get('alerts_text', '')
        if alerts_text and "no significant" not in alerts_text.lower():
            html += f"<p>🚨 {alerts_text}</p>\n"
        
        # Traffic (I-880)
        traffic_text = bart_info.get('traffic_text', '')
        if traffic_text:
            html += f"<p>{traffic_text}</p>\n"
    else:
        # Graceful degradation
        html += "<p><em>Commute data temporarily unavailable. Check <a href='https://www.bart.gov/'>BART.gov</a> and <a href='https://511.org/'>511.org</a> directly.</em></p>\n"
    
    html += """
<p><a href="https://www.bart.gov/schedules/">BART Schedule →</a> | <a href="https://511.org/">511 Traffic →</a></p>
</div>
"""
    
    history_label = get_source_label('Wikipedia', 'article')
    html += f"""
<div class="section">
<h2>📚 ON THIS DAY IN HISTORY <span style="background: #17a2b8; color: white; font-size: 10px; padding: 3px 8px; border-radius: 3px; margin-left: 5px; vertical-align: middle;">DAILY FACT</span></h2>
<p><em>Historical highlights from Wikipedia's "On This Day" — one fact per day</em></p>
<h3>{history['title']}</h3>
<p>{history['summary']}</p>
<p><em>Fun fact: {history['fun_fact']}</em></p>
<p><a href="{history['link']}">{history_label}</a></p>
</div>
"""
    
    html += """
<p>— LilyBot 🌸<br>
Alex's Digital Assistant</p>

<p style="font-size: 12px; color: #666; margin-top: 30px;">
<em>
<strong style="color: #28a745;">LIVE:</strong> Yahoo Finance, NewsAPI, RSS feeds, Wikipedia On This Day, BART API<br>
<strong style="color: #6c757d;">CURATED:</strong> Lily's picks (restaurants, scenic spots, events, pop culture) updated weekly/monthly
</em>
</p>

</body>
</html>
"""
    
    # Close email-wrapper and Outlook conditional
    html += """
</div>
<!--[if mso]></td></tr></table><![endif]-->
"""
    
    return html


def send_email(subject, html_body):
    """Send email using gog CLI to each recipient."""
    gog_path = "/opt/homebrew/bin/gog"
    if not os.path.exists(gog_path):
        gog_path = "gog"
    
    recipients = get_newsletter_recipients()
    if not recipients:
        print("✗ No recipients configured for the daily newsletter.")
        return False
    
    success = True
    for recipient in recipients:
        cmd = [
            gog_path, "gmail", "send",
            "--account", CONFIG['from_account'],
            "--to", recipient,
            "--subject", subject,
            "--body-html", html_body,
            "--body", "HTML version attached - please view in a modern email client"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✓ Email sent successfully: {subject} → {recipient}")
            else:
                print(f"✗ Failed to send to {recipient}: {result.stderr}")
                success = False
        except Exception as e:
            print(f"✗ Error sending email to {recipient}: {e}")
            success = False
    return success


def log_send(today_info, api_status):
    """Log the send with API status"""
    log_file = Path.home() / ".openclaw/workspace/logs/daily-brief.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] Sent daily brief for {today_info['display_date']}\n")
        f.write(f"  API Status: {json.dumps(api_status)}\n")


def review_feedback(days=7):
    """Review recent feedback and show analytics."""
    data = load_feedback()
    today = datetime.datetime.now()
    
    print("\n📊 NEWSLETTER FEEDBACK ANALYSIS")
    print("=" * 50)
    
    # Filter recent feedback
    recent = []
    for f in data.get("feedbacks", []):
        try:
            fb_date = datetime.datetime.strptime(f["date"], "%Y-%m-%d")
            if (today - fb_date).days <= days:
                recent.append(f)
        except:
            pass
    
    print(f"\n📅 Last {days} days: {len(recent)} feedback entries")
    
    # Count by action
    actions = {}
    for f in recent:
        actions[f["action"]] = actions.get(f["action"], 0) + 1
    
    print("\n📈 By action:")
    for action, count in sorted(actions.items(), key=lambda x: -x[1]):
        print(f"  {action}: {count}")
    
    # Top items by score
    scores = data.get("scores", {})
    top_liked = sorted(scores.items(), key=lambda x: -x[1])[:10]
    top_skipped = sorted(scores.items(), key=lambda x: x[1])[:5]
    
    print("\n👍 Top liked items:")
    for item, score in top_liked:
        if score > 0:
            print(f"  +{score}: {item[:50]}")
    
    print("\n👎 Most skipped items:")
    for item, score in top_skipped:
        if score < 0:
            print(f"  {score}: {item[:50]}")
    
    # Section breakdown
    sections = {}
    for f in recent:
        sec = f.get("section", "unknown")
        sections[sec] = sections.get(sec, 0) + 1
    
    print("\n📂 Feedback by section:")
    for sec, count in sorted(sections.items(), key=lambda x: -x[1]):
        print(f"  {sec}: {count}")
    
    print()
    return data


def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description="Lily's Daily Newsletter")
    parser.add_argument("--dry-run", action="store_true", help="Generate without sending")
    parser.add_argument("--review-feedback", action="store_true", help="Review feedback analytics")
    parser.add_argument("--days", type=int, default=7, help="Days to review for --review-feedback")
    args = parser.parse_args()
    
    if args.review_feedback:
        review_feedback(args.days)
        return 0
    
    dry_run = "--dry-run" in sys.argv or "--dry" in sys.argv
    
    print("🌸 Generating Daily Brief for Lily (v2 with Live Data)...")
    
    today_info = get_today_info()
    print(f"📅 Date: {today_info['display_date']}")
    
    # Initialize newsletter tracking for feedback loop (Phase 1)
    # Creates a newsletter entry in the database for click/feedback attribution
    newsletter_id = init_tracking_for_newsletter(today_info['date_str'])
    
    # Track which APIs are working
    api_status = {
        "yelp": False,
        "yahoo_finance": False,
        "enews": False,
        "google_places": False,
        "wikipedia": False,
        "funcheep": False,
        "bart": False
    }
    
    # Fetch all content
    print("\n📰 Fetching news (existing)...")
    world_news = fetch_world_news()
    bay_news = fetch_bay_area_news()
    
    print("\n💰 Fetching finance data...")
    finance = fetch_yahoo_finance()
    api_status["yahoo_finance"] = "Markets update" in finance.get("market_summary", "")
    
    print("\n🎭 Fetching entertainment news...")
    gossip = fetch_entertainment_news()
    api_status["enews"] = len(gossip) > 0 and "content" in gossip[0]
    
    print("\n🍽️ Fetching restaurant recommendations...")
    restaurants = fetch_yelp_restaurants()
    api_status["yelp"] = "Rating:" in str(restaurants[0].get("notes", "")) if restaurants else False
    
    print("\n📸 Fetching scenic spots...")
    scenic = fetch_google_scenic()
    api_status["google_places"] = "reviews" in str(scenic[0].get("notes", "")) if scenic else False
    
    print("\n🎉 Fetching events...")
    events = fetch_funcheep_events()
    api_status["funcheep"] = len(events) > 0
    
    # Apply feedback-driven content selection (Phase 4)
    # Score and rank items based on historical feedback
    import random
    random.seed()  # Ensure randomness for variety in shuffling
    
    print("\n🎯 Applying feedback-driven content selection...")
    
    # Restaurants: prefer high-scoring, exclude score < -2
    print("  [Restaurants] Applying feedback scores...")
    restaurants = select_with_feedback(restaurants, "restaurant", max_items=5, min_score=-2.0)
    
    # Scenic spots: similar logic
    print("  [Scenic Spots] Applying feedback scores...")
    scenic = select_with_feedback(scenic, "scenic", max_items=5, min_score=-2.0)
    
    # Events: similar logic
    print("  [Events] Applying feedback scores...")
    events = select_with_feedback(events, "event", max_items=5, min_score=-2.0)
    
    print("\n📚 Fetching historical facts...")
    history = fetch_wikipedia_history(today_info)
    api_status["wikipedia"] = "Wikipedia API" not in history.get("summary", "")
    
    print("\n🚇 Fetching BART realtime data...")
    bart_info = fetch_bart_realtime()
    api_status["bart"] = bool(bart_info.get("departures_text"))
    
    # Generate HTML
    print("\n📧 Generating HTML email...")
    html = generate_html_email(today_info, world_news, bay_news, finance, gossip, restaurants, scenic, events, history, bart_info, NEWSLETTER_ID)
    
    # Save HTML for debugging
    debug_file = Path.home() / ".openclaw/workspace/logs/last-brief.html"
    debug_file.parent.mkdir(parents=True, exist_ok=True)
    with open(debug_file, "w") as f:
        f.write(html)
    print(f"💾 Debug HTML saved to: {debug_file}")
    
    # Print API status summary
    print("\n📊 Live Data Sources Status:")
    for api, working in api_status.items():
        status = "✓" if working else "✗ (using fallback)"
        print(f"  {api}: {status}")
    
    if dry_run:
        print("\n🏃 DRY RUN: Email not sent (use --dry-run to preview without sending)")
        return 0
    
    # Send email
    subject = f"Your Daily Brief — {today_info['display_date']}"
    print(f"\n📤 Sending: {subject}")
    if send_email(subject, html):
        log_send(today_info, api_status)
        print("✅ Daily brief sent successfully!")
        return 0
    else:
        print("❌ Failed to send daily brief")
        return 1


if __name__ == "__main__":
    sys.exit(main())

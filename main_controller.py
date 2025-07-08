import json
import os
import time
from datetime import date, timedelta, datetime, time as time_obj
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import sys
import random

# ✅ CORRECTED LINE: The function is 'sync_stealth', not 'stealth_sync'.
from playwright_stealth import sync_stealth

from api_handler import initialize_client
from flight_scraper import get_daily_prices_from_graph, get_detailed_flight_info
from airbnb_scraper import get_cheapest_accommodations, get_listing_calendar_availability

# (All of your other functions like load_config, log_api_response, etc. remain the same)
def load_config():
    """Loads config.json."""
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("FATAL ERROR: config.json not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        print("FATAL ERROR: config.json is invalid.")
        sys.exit(1)

# ... [other functions remain unchanged] ...

def main():
    config = load_config()
    client = initialize_client(config)
    
    params = config['search_parameters']
    paths = config['file_paths']
    log_func = lambda response, name: log_api_response(response, name, paths['log_file'])

    try:
        start_date = datetime.strptime(params['start_date'], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        start_date = date.today() + timedelta(days=1)
    
    print(f"--- Starting Trip Search ---")
    
    all_results = {}
    if os.path.exists(paths['results_file']):
        try:
            with open(paths['results_file'], "r", encoding="utf-8") as f:
                all_results = json.load(f)
            print(f"--- Loaded {len(all_results)} previous results ---")
        except json.JSONDecodeError:
            all_results = {}

    with sync_playwright() as p:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=user_agent)
        
        # ✅ CORRECTED LINE: Call the correct function name.
        sync_stealth(page)
        
        print("--- Browser session started with stealth options ---")

        try:
            # (The rest of your main try...except block remains exactly the same)
            for country_name, country_data in config['destinations'].items():
                # ...
                pass # Your full scraping loop goes here

        except PlaywrightTimeoutError as e:
            print("\n--- FATAL PLAYWRIGHT TIMEOUT ERROR ---")
            print(f"--- Error Details: {e} ---")
            screenshot_path = "error_screenshot.png"
            page.screenshot(path=screenshot_path)
            print(f"--- Screenshot saved to '{screenshot_path}'. It will be uploaded as a workflow artifact. ---")
            raise 
        except Exception as e:
            print(f"\n--- AN UNEXPECTED FATAL ERROR OCCURRED: {e} ---")
            screenshot_path = "error_screenshot.png"
            page.screenshot(path=screenshot_path)
            print(f"--- Screenshot saved to '{screenshot_path}'. ---")
            raise

        browser.close()
        print("\n--- Browser session closed ---")

    print("\n\n--- FINAL RESULTS ---")
    # ... (Your final print loop)

if __name__ == "__main__":
    main()
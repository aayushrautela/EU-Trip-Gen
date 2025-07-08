import json
import os
import time
from datetime import date, timedelta, datetime, time as time_obj
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import sys
import random

# ✅ MODIFICATION: Import the stealth plugin
from playwright_stealth import stealth_sync

from api_handler import initialize_client
from flight_scraper import get_daily_prices_from_graph, get_detailed_flight_info
from airbnb_scraper import get_cheapest_accommodations, get_listing_calendar_availability

# (All of your functions like load_config, log_api_response, etc. remain the same)
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

def log_api_response(response_data, function_name, file_path):
    """Logs AI responses."""
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"--- Log from {function_name} at {time.ctime()} ---\n")
            if isinstance(response_data, dict):
                f.write(json.dumps(response_data, indent=2))
            else:
                f.write(str(response_data))
            f.write("\n---\n\n")
    except Exception as e:
        print(f" - Warning: Could not write log. Error: {e}")

def calculate_exploration_hours(outbound_arrival_str, return_departure_str, num_nights, config):
    """Calculates usable exploration hours."""
    day_starts = time_obj(config['search_parameters'].get('day_starts_at_hour', 8), 0)
    day_ends = time_obj(config['search_parameters'].get('day_ends_at_hour', 21), 0)
    buffer = config['search_parameters'].get('airport_buffer_hours', 2)
    try:
        def parse_time(time_str):
            if "+1" in time_str: return datetime.strptime(time_str.split('+')[0], "%H:%M").time(), True
            return datetime.strptime(time_str, "%H:%M").time(), False

        outbound_arrival, _ = parse_time(outbound_arrival_str)
        return_departure, _ = parse_time(return_departure_str)
        
        outbound_arrival_hours = outbound_arrival.hour + outbound_arrival.minute / 60.0
        return_departure_hours = return_departure.hour + return_departure.minute / 60.0
        day_starts_hours, day_ends_hours = day_starts.hour, day_ends.hour
        
        explore_starts = max(day_starts_hours, outbound_arrival_hours + buffer)
        explore_ends = min(day_ends_hours, return_departure_hours - buffer)

        if num_nights == 0:
            total_hours = max(0, explore_ends - explore_starts)
        else:
            arrival_day_hours = max(0, day_ends_hours - explore_starts)
            departure_day_hours = max(0, explore_ends - day_starts_hours)
            full_day_count = max(0, num_nights - 1)
            full_day_hours = full_day_count * (day_ends_hours - day_starts_hours)
            total_hours = arrival_day_hours + departure_day_hours + full_day_hours

        return round(total_hours, 2)
    except (ValueError, IndexError, TypeError):
        return 0.0

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
        # ✅ MODIFICATION: Define a realistic User-Agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        
        browser = p.chromium.launch(headless=True)
        # ✅ MODIFICATION: Apply the User-Agent when creating the page
        page = browser.new_page(user_agent=user_agent)
        
        # ✅ MODIFICATION: Apply stealth settings to the page
        stealth_sync(page)
        
        print("--- Browser session started with stealth options ---")

        try:
            for country_name, country_data in config['destinations'].items():
                if not country_data.get("enabled", False):
                    continue

                for dest_id, dest_name in country_data.get("cities", {}).items():
                    if dest_name in all_results:
                        print(f"\n--- Skipping: {dest_name} ---")
                        continue
                    
                    # The rest of your main loop logic remains unchanged...
                    print(f"\n--- Processing: {dest_name} ---")
                    # ...
                    all_outbound_prices = get_daily_prices_from_graph(page, params['origin_city_id'], dest_id, start_date, config, log_func)
                    # ... [and so on]
            # ... [The rest of your main loop from the previous version] ...

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

    # (Your final print loop remains the same)
    print("\n\n--- FINAL RESULTS ---")
    # ...

if __name__ == "__main__":
    main()
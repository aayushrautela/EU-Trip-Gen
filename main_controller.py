import json
import os
import time
from datetime import date, timedelta, datetime, time as time_obj
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import sys
import random

# Correct import for playwright-stealth version 1.0.6
from playwright_stealth import stealth_sync

from api_handler import initialize_client
from flight_scraper import get_daily_prices_from_graph, get_detailed_flight_info
from airbnb_scraper import get_cheapest_accommodations, get_listing_calendar_availability

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
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=user_agent)
        
        # Apply stealth settings to the page
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

                    print(f"\n--- Processing: {dest_name} ---")
                
                    # Phase 1: Get flight prices
                    all_outbound_prices = get_daily_prices_from_graph(page, params['origin_city_id'], dest_id, start_date, config, log_func)
                    all_return_prices = get_daily_prices_from_graph(page, dest_id, params['origin_city_id'], start_date, config, log_func)
                    
                    if not all_outbound_prices or not all_return_prices:
                        print(f" - No flight data for {dest_name}.")
                        continue
                    
                    # Phase 2: Generate trip combinations
                    potential_trips_raw = []
                    max_trip_duration_days = params.get('max_trip_duration_days', 7) 
                    max_num_nights = max(0, max_trip_duration_days - 1)

                    for ob in all_outbound_prices:
                        for ret in all_return_prices:
                            try:
                                ob_date = datetime.strptime(ob['full_date'], "%Y-%m-%d").date()
                                ret_date = datetime.strptime(ret['full_date'], "%Y-%m-%d").date()
                                num_nights = (ret_date - ob_date).days

                                if 0 <= num_nights <= max_num_nights:
                                    potential_trips_raw.append({
                                        "outbound_date": ob_date.strftime("%Y-%m-%d"),
                                        "return_date": ret_date.strftime("%Y-%m-%d"),
                                        "estimated_flight_cost": ob['price'] + ret['price'],
                                        "num_nights": num_nights
                                    })
                            except (ValueError, TypeError):
                                continue
                    
                    if not potential_trips_raw:
                        print(" - No valid flight combinations.")
                        continue

                    # Phase 3: Search Airbnb
                    all_sample_durations = [1, 2, 3, 5, 7, 10, 14]
                    common_airbnb_durations = [d for d in all_sample_durations if d <= max_num_nights]
                    
                    top_initial_airbnb_listings_by_duration = {} 
                    sample_airbnb_checkin = start_date.strftime("%Y-%m-%d")

                    for duration in common_airbnb_durations:
                        sample_airbnb_checkout = (datetime.strptime(sample_airbnb_checkin, "%Y-%m-%d").date() + timedelta(days=duration)).strftime("%Y-%m-%d")
                        accommodations = get_cheapest_accommodations(
                            page=page, destination_city=dest_name, specific_location_query=dest_name, 
                            checkin=sample_airbnb_checkin, checkout=sample_airbnb_checkout,
                            config=config, log_func=log_func
                        )
                        if accommodations:
                            top_initial_airbnb_listings_by_duration[duration] = accommodations
                    
                    if not top_initial_airbnb_listings_by_duration:
                        print(" - No Airbnb listings found.")
                        continue

                    # Phase 4: Scan Airbnb calendars
                    airbnb_calendar_cache = {}
                    search_calendar_months = params.get('airbnb_calendar_months_to_scan', 6)
                    all_unique_listing_links = set()
                    for duration_listings in top_initial_airbnb_listings_by_duration.values():
                        for listing in duration_listings:
                            all_unique_listing_links.add(listing['link'])
                    
                    for listing_link in all_unique_listing_links:
                        calendar_data = get_listing_calendar_availability(page, listing_link, search_calendar_months)
                        if calendar_data:
                            airbnb_calendar_cache[listing_link] = calendar_data
                        else:
                            airbnb_calendar_cache[listing_link] = {}
                    
                    # Phase 5: Estimate total costs
                    potential_trips_with_estimates = []
                    min_exploration_hours = params.get('min_exploration_hours', 10)

                    for trip in potential_trips_raw:
                        num_nights = trip['num_nights']
                        
                        rough_exploration_hours = calculate_exploration_hours("12:00", "12:00", num_nights, config)
                        if rough_exploration_hours < min_exploration_hours:
                            continue

                        chosen_airbnb_for_estimation = None
                        if num_nights > 0:
                            if not top_initial_airbnb_listings_by_duration: continue
                            best_duration_match = min(top_initial_airbnb_listings_by_duration.keys(), key=lambda d: abs(d - num_nights))
                            
                            for cached_listing in top_initial_airbnb_listings_by_duration[best_duration_match]:
                                listing_calendar = airbnb_calendar_cache.get(cached_listing['link'])
                                if listing_calendar:
                                    all_dates_available = True
                                    current_date = datetime.strptime(trip['outbound_date'], "%Y-%m-%d").date()
                                    while current_date < datetime.strptime(trip['return_date'], "%Y-%m-%d").date():
                                        if not listing_calendar.get(current_date.strftime("%Y-%m-%d"), False):
                                            all_dates_available = False
                                            break
                                        current_date += timedelta(days=1)
                                    if all_dates_available:
                                        chosen_airbnb_for_estimation = cached_listing
                                        break
                            if not chosen_airbnb_for_estimation:
                                continue
                        else:
                            chosen_airbnb_for_estimation = {"name": "N/A (Day Trip)", "total_accommodation_cost": 0, "link": "N/A", "rating": "N/A"}

                        estimated_total_accommodation_cost = chosen_airbnb_for_estimation.get('total_accommodation_cost', 0)
                        estimated_total_cost = trip['estimated_flight_cost'] + estimated_total_accommodation_cost
                        estimated_cost_per_hour = estimated_total_cost / rough_exploration_hours if rough_exploration_hours > 0 else float('inf')

                        if estimated_cost_per_hour != float('inf'):
                            potential_trips_with_estimates.append({**trip, 
                                "estimated_total_cost": estimated_total_cost, 
                                "estimated_cost_per_hour": estimated_cost_per_hour, 
                                "matched_airbnb_listing": chosen_airbnb_for_estimation})

                    potential_trips_with_estimates.sort(key=lambda x: x['estimated_cost_per_hour'])

                    # Phase 6: Detailed validation
                    final_results_for_dest = []
                    best_cost_per_hour_overall = float('inf')
                    num_candidates_to_validate = params.get('num_candidates_to_validate', 5)
                    top_candidates = potential_trips_with_estimates[:num_candidates_to_validate]

                    for trip_candidate in top_candidates:
                        if trip_candidate['estimated_cost_per_hour'] >= best_cost_per_hour_overall:
                            break

                        outbound_flights = get_detailed_flight_info(page, params['origin_city_id'], dest_id, trip_candidate['outbound_date'], client, config, log_func)
                        if not outbound_flights: continue
                        return_flights = get_detailed_flight_info(page, dest_id, params['origin_city_id'], trip_candidate['return_date'], client, config, log_func)
                        if not return_flights: continue
                        
                        cheapest_outbound, cheapest_return = outbound_flights[0], return_flights[0]
                        actual_flight_cost = cheapest_outbound.get('price', 0) + cheapest_return.get('price', 0)
                        
                        exploration_hours = calculate_exploration_hours(cheapest_outbound.get('arrival_time', '00:00'), cheapest_return.get('departure_time', '00:00'), trip_candidate['num_nights'], config)
                        
                        if exploration_hours < min_exploration_hours:
                            continue
                        
                        actual_accommodation_details = trip_candidate['matched_airbnb_listing']
                        actual_total_accommodation_cost = actual_accommodation_details.get('total_accommodation_cost', 0) if actual_accommodation_details else 0
                        
                        total_cost = actual_flight_cost + actual_total_accommodation_cost
                        cost_per_hour = total_cost / exploration_hours if exploration_hours > 0 else float('inf')

                        if cost_per_hour == float('inf'): continue
                        
                        print(f" - ✅ Valid trip found!")
                        final_results_for_dest.append({
                            "destination": dest_name, "outbound_date": trip_candidate['outbound_date'], "return_date": trip_candidate['return_date'],
                            "total_cost": round(total_cost, 2), "cost_per_hour_of_exploration": round(cost_per_hour, 2), "exploration_hours": exploration_hours,
                            "flights": {"total_price": actual_flight_cost, "outbound": cheapest_outbound, "return": cheapest_return},
                            "accommodation": actual_accommodation_details})
                        best_cost_per_hour_overall = min(best_cost_per_hour_overall, cost_per_hour)
                    
                    if final_results_for_dest:
                        final_results_for_dest.sort(key=lambda x: x.get('cost_per_hour_of_exploration', float('inf')))
                        all_results[dest_name] = final_results_for_dest[:params.get('num_final_results_to_store', 3)]
                        with open(paths['results_file'], "w", encoding="utf-8") as f:
                            json.dump(all_results, f, indent=2, ensure_ascii=False)
                            print(f"\n--- Saved results for {dest_name} ---")
                    else:
                        print(f"\n--- No valid trips for {dest_name} ---")

        except (PlaywrightTimeoutError, Exception) as e:
            # Catch any Playwright timeout or other unexpected error
            error_type = type(e).__name__
            print(f"\n--- A FATAL {error_type.upper()} OCCURRED ---")
            print(f"--- Error Details: {e} ---")
            screenshot_path = "error_screenshot.png"
            page.screenshot(path=screenshot_path)
            print(f"--- Screenshot saved to '{screenshot_path}'. It will be uploaded as a workflow artifact. ---")
            raise # Re-raise the exception to fail the workflow

        browser.close()
        print("\n--- Browser session closed ---")

    print("\n\n--- FINAL RESULTS ---")
    for dest_name, results in all_results.items():
        print(f"\n--- {dest_name} ---")
        for i, result in enumerate(results, 1):
            print(f" Option {i}:")
            print(f"   - Dates: {result['outbound_date']} to {result['return_date']}")
            print(f"   - Total Cost: PLN{result['total_cost']}")
            print(f"   - Exploration Hours: {result['exploration_hours']}")
            print(f"   - Cost per Hour: PLN{result['cost_per_hour_of_exploration']}")

if __name__ == "__main__":
    main()
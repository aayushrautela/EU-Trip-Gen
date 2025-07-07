import json
import os
import time
from datetime import date, timedelta, datetime, time as time_obj
from playwright.sync_api import sync_playwright
import sys
import random

# Import our modular functions
from api_handler import initialize_client
from flight_scraper import get_daily_prices_from_graph, get_detailed_flight_info
from airbnb_scraper import get_cheapest_accommodations, get_listing_calendar_availability

# --- Utility Functions ---
def load_config():
    """Loads the configuration from config.json."""
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("FATAL ERROR: config.json not found. Please create it.")
        sys.exit(1)
    except json.JSONDecodeError:
        print("FATAL ERROR: config.json is not a valid JSON file.")
        sys.exit(1)

def log_api_response(response_data, function_name, file_path):
    """Logs the AI's response to a file for debugging."""
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"--- Log from {function_name} at {time.ctime()} ---\n")
            if isinstance(response_data, dict):
                f.write(json.dumps(response_data, indent=2))
            else:
                f.write(str(response_data))
            f.write("\n---\n\n")
    except Exception as e:
        print(f"  - Warning: Could not write to log file. Error: {e}")

# --- Exploration Time Calculator (FIXED) ---
def calculate_exploration_hours(outbound_arrival_str, return_departure_str, num_nights, config):
    """
    Calculates the 'usable' exploration hours based on config.
    This version contains the corrected logic for same-day trips.
    """
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
        
        # Determine the effective start and end points of the usable time window
        explore_starts = max(day_starts_hours, outbound_arrival_hours + buffer)
        explore_ends = min(day_ends_hours, return_departure_hours - buffer)

        # --- THIS IS THE FIX ---
        # Correctly calculate total hours based on trip type
        if num_nights == 0:
            # For a DAY-TRIP, calculate the simple interval on that single day.
            # If explore_starts is after explore_ends, the result is 0.
            total_hours = max(0, explore_ends - explore_starts)
        else:
            # For a MULTI-DAY trip, calculate hours for each part of the trip
            # 1. Hours on arrival day
            arrival_day_hours = max(0, day_ends_hours - explore_starts)
            # 2. Hours on departure day
            departure_day_hours = max(0, explore_ends - day_starts_hours)
            # 3. Hours for full days in between
            full_day_count = max(0, num_nights - 1)
            full_day_hours = full_day_count * (day_ends_hours - day_starts_hours)
            total_hours = arrival_day_hours + departure_day_hours + full_day_hours

        return round(total_hours, 2)
    except (ValueError, IndexError, TypeError):
        return 0.0

# --- Main Engine ---
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
    
    print(f"--- Starting Trip Search for {params['days_to_search']} days from {start_date} ---")
    
    all_results = {}
    if os.path.exists(paths['results_file']):
        try:
            with open(paths['results_file'], "r", encoding="utf-8") as f:
                all_results = json.load(f)
            print(f"--- Loaded {len(all_results)} previous results from '{paths['results_file']}' ---")
        except json.JSONDecodeError:
            all_results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print("--- Browser session started. ---")

        for country_name, country_data in config['destinations'].items():
            if not country_data.get("enabled", False):
                continue

            for dest_id, dest_name in country_data.get("cities", {}).items():
                if dest_name in all_results:
                    print(f"\n--- Skipping already processed destination: {dest_name} ---")
                    continue

                print(f"\n--- Processing Destination: {dest_name}, {country_name.title()} ---")
            
                print("\n--- Phase 1: Collecting all estimated flight prices (Kiwi Calendar) ---")
                all_outbound_prices = get_daily_prices_from_graph(page, params['origin_city_id'], dest_id, start_date, config, log_func)
                all_return_prices = get_daily_prices_from_graph(page, dest_id, params['origin_city_id'], start_date, config, log_func)
                
                if not all_outbound_prices or not all_return_prices:
                    print(f"  - ❌ Could not retrieve initial flight price data for {dest_name}. Skipping.")
                    continue
                
                print("\n--- Phase 2: Generating potential trip combinations (flight-only, for date ranges) ---")
                potential_trips_raw = []
                max_trip_duration_days = params.get('max_trip_duration_days', 7) 
                max_num_nights = max(0, max_trip_duration_days - 1)
                print(f"  - Filtering for trips up to {max_trip_duration_days} days long (max {max_num_nights} nights).")

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
                    print("  - No potential flight date combinations found in the specified date range. Continuing.")
                    continue

                print("\n--- Phase 3: Initial Airbnb search for cheapest listings (by common duration) ---")
                all_sample_durations = [1, 2, 3, 5, 7, 10, 14]
                common_airbnb_durations = [d for d in all_sample_durations if d <= max_num_nights]
                print(f"  - Will perform sample Airbnb searches for durations up to {max_num_nights} nights: {common_airbnb_durations}")

                top_initial_airbnb_listings_by_duration = {} 
                sample_airbnb_checkin = start_date.strftime("%Y-%m-%d")

                for duration in common_airbnb_durations:
                    sample_airbnb_checkout = (datetime.strptime(sample_airbnb_checkin, "%Y-%m-%d").date() + timedelta(days=duration)).strftime("%Y-%m-%d")
                    print(f"    - Searching Airbnb for {dest_name}, {duration} nights from {sample_airbnb_checkin}...")
                    accommodations = get_cheapest_accommodations(
                        page=page, destination_city=dest_name, specific_location_query=dest_name, 
                        checkin=sample_airbnb_checkin, checkout=sample_airbnb_checkout,
                        config=config, log_func=log_func
                    )
                    if accommodations:
                        top_initial_airbnb_listings_by_duration[duration] = accommodations
                        print(f"      - Found {len(accommodations)} cheapest listings for {duration} nights.")
                    else:
                        print(f"      - No listings found for {duration} nights from {sample_airbnb_checkin}.")
                
                if not top_initial_airbnb_listings_by_duration:
                    print("  - ❌ No initial cheapest Airbnb listings found for any common duration. Skipping.")
                    continue

                print("\n--- Phase 4: Broad Airbnb calendar availability scan for cached listings ---")
                airbnb_calendar_cache = {}
                search_calendar_months = params.get('airbnb_calendar_months_to_scan', 6)
                all_unique_listing_links = set()
                for duration_listings in top_initial_airbnb_listings_by_duration.values():
                    for listing in duration_listings:
                        all_unique_listing_links.add(listing['link'])
                
                print(f"    - Identified {len(all_unique_listing_links)} unique Airbnb listing calendars to scan.")
                for listing_link in all_unique_listing_links:
                    calendar_data = get_listing_calendar_availability(page, listing_link, search_calendar_months)
                    if calendar_data:
                        airbnb_calendar_cache[listing_link] = calendar_data
                    else:
                        airbnb_calendar_cache[listing_link] = {}
                
                print(f"    - Populated calendar cache for {len(airbnb_calendar_cache)} listings.")

                print("\n--- Phase 5: Calculating estimated total costs & sorting all potential trips ---")
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
                print(f"    - Sorted {len(potential_trips_with_estimates)} potential trips by estimated cost per hour.")

                print("\n--- Phase 6: Detailed validation for top candidates ---")
                final_results_for_dest = []
                best_cost_per_hour_overall = float('inf')
                num_candidates_to_validate = params.get('num_candidates_to_validate', 5)
                top_candidates = potential_trips_with_estimates[:num_candidates_to_validate]

                for trip_candidate in top_candidates:
                    print(f"\n  - Validating candidate trip: {trip_candidate['outbound_date']} to {trip_candidate['return_date']} (Est. CPH: PLN{trip_candidate['estimated_cost_per_hour']:.2f})")
                    if trip_candidate['estimated_cost_per_hour'] >= best_cost_per_hour_overall:
                        print("    - Skipping: Estimated CPH is worse than current best actual CPH.")
                        break

                    outbound_flights = get_detailed_flight_info(page, params['origin_city_id'], dest_id, trip_candidate['outbound_date'], client, config, log_func)
                    if not outbound_flights: continue
                    return_flights = get_detailed_flight_info(page, dest_id, params['origin_city_id'], trip_candidate['return_date'], client, config, log_func)
                    if not return_flights: continue
                    
                    cheapest_outbound, cheapest_return = outbound_flights[0], return_flights[0]
                    actual_flight_cost = cheapest_outbound.get('price', 0) + cheapest_return.get('price', 0)
                    
                    exploration_hours = calculate_exploration_hours(cheapest_outbound.get('arrival_time', '00:00'), cheapest_return.get('departure_time', '00:00'), trip_candidate['num_nights'], config)
                    
                    if exploration_hours < min_exploration_hours:
                        print(f"    - Skipping: Insufficient actual exploration time ({exploration_hours} hours).")
                        continue
                    
                    actual_accommodation_details = trip_candidate['matched_airbnb_listing']
                    actual_total_accommodation_cost = actual_accommodation_details.get('total_accommodation_cost', 0) if actual_accommodation_details else 0
                    
                    total_cost = actual_flight_cost + actual_total_accommodation_cost
                    cost_per_hour = total_cost / exploration_hours if exploration_hours > 0 else float('inf')

                    if cost_per_hour == float('inf'): continue
                    
                    print(f"    - ✅ SUCCESS: Found valid trip package! Total cost: PLN{total_cost:.2f}, PerHour: PLN{cost_per_hour:.2f}")
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
                        print(f"\n--- Saved {len(all_results[dest_name])} best results for {dest_name} to '{paths['results_file']}' ---")
                else:
                    print(f"\n--- No valid trip packages found for {dest_name} after detailed validation. ---")

        browser.close()
        print("\n--- Browser session closed. ---")

    print("\n\n--- FINAL RESULTS ---")
    for dest_name, results in all_results.items():
        print(f"\n--- {dest_name} ---")
        for i, result in enumerate(results, 1):
            print(f"  Option {i}:")
            print(f"    - Dates: {result['outbound_date']} to {result['return_date']}")
            print(f"    - Total Cost: PLN{result['total_cost']}")
            print(f"    - Exploration Hours: {result['exploration_hours']}")
            print(f"    - Cost per Hour: PLN{result['cost_per_hour_of_exploration']}")

if __name__ == "__main__":
    main()
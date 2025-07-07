import json
import time
from playwright.sync_api import Page, Error
import random
import re
from datetime import datetime, timedelta

# --- Directly extracts prices from the calendar view ---
def extract_prices_from_calendar(page: Page) -> list:
    """
    Directly scrapes the full date and price from the calendar view using
    stable data-test attributes.
    """
    print("      - Directly parsing price data from calendar HTML...")
    daily_prices = []
    # Find all calendar day elements that are not disabled
    day_elements = page.locator('[data-test="CalendarDay"]').all()
    
    if not day_elements:
        print("      - ❌ No active calendar day elements found.")
        return []

    for day_element in day_elements:
        try:
            full_date = day_element.get_attribute('data-value')
            price_element = day_element.locator('[data-test="NewDatepickerPrice"]')
            price_text = price_element.inner_text(timeout=1000)
            
            # Use regex to get only the digits from the price string (e.g., "123 zł")
            price_match = re.search(r'(\d[\d,]*)', price_text)
            if not price_match:
                continue

            price = int(price_match.group(1).replace(',', ''))
            
            if full_date and price:
                daily_prices.append({
                    "full_date": full_date,
                    "price": price
                })
        except (Error, ValueError, AttributeError):
            # Skip if an element is missing data or fails to parse
            continue
            
    # Sort the results by price in Python
    if daily_prices:
        daily_prices.sort(key=lambda x: x.get('price', float('inf')))

    return daily_prices

def get_daily_prices_from_graph(page: Page, origin: str, destination: str, start_date: datetime.date, config: dict, log_func):
    """
    Scrapes the price calendar, clicking "next month" if needed to cover the
    full search period, and logs the result. This no longer uses the AI.
    """
    days_to_search = config['search_parameters']['days_to_search']
    search_end_date = start_date + timedelta(days=days_to_search)
    
    initial_url = f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{start_date.strftime('%Y-%m-%d')}/no-return"
    print(f"    - Scraping all monthly price data from: {initial_url}")

    all_prices = {} # Use a dictionary to automatically handle duplicates

    for attempt in range(3):
        try:
            page.goto(initial_url, timeout=90000)
            cookie_wait = config['search_parameters']['cookie_wait_seconds']
            
            if not page.context.storage_state().get("ran_once"):
                try:
                    page.get_by_role('button', name='Accept', exact=True).click(timeout=7000)
                    time.sleep(cookie_wait)
                    page.evaluate("() => window.localStorage.setItem('ran_once', 'true')")
                except Error: pass
            
            print("      - Clicking date input to reveal price calendar...")
            page.locator('[data-test="SearchFieldDateInput"]').click()

            # --- SIMPLIFIED LOGIC ---
            # Wait for 5 seconds for prices to load.
            print("      - Waiting 5 seconds for prices to load...")
            time.sleep(5)
            
            # Loop to click "Next Month" if needed
            while True:
                print("      - Parsing currently visible month(s)...")
                current_prices = extract_prices_from_calendar(page)
                for price_data in current_prices:
                    all_prices[price_data['full_date']] = price_data

                print(f"      - Found {len(current_prices)} prices in current view. Total unique prices so far: {len(all_prices)}")

                # Get the last date from the calendar to see if we need to continue
                last_day_in_calendar_str = page.locator('[data-test="CalendarDay"]').last.get_attribute('data-value')
                last_day_in_calendar = datetime.strptime(last_day_in_calendar_str, '%Y-%m-%d').date()

                if last_day_in_calendar >= search_end_date:
                    print("      - Calendar now shows all required dates. Finalizing price list.")
                    break
                else:
                    print("      - Required search period extends beyond visible calendar. Clicking next month...")
                    page.locator('[data-test="CalendarMoveNext"]').click()
                    # Wait another 5 seconds for the next month to load
                    time.sleep(5)

            # Convert the dictionary back to a list
            final_price_list = list(all_prices.values())
            
            if final_price_list:
                final_price_list.sort(key=lambda x: x.get('price', float('inf')))
            
            log_func(final_price_list, f"direct_scrape_{origin}_to_{destination}")
            print(f"    - Successfully parsed a total of {len(final_price_list)} unique daily prices.")
            return final_price_list

        except Exception as e:
            print(f"--- Attempt {attempt + 1} FAILED for price graph. Error: {e}")
            if attempt < 2: time.sleep(10)

    print(f"--- All scraping attempts for price graph failed. ---")
    return []

# This function still requires the AI as the flight card text is less structured.
def get_detailed_flight_info(page, origin, destination, departure_date, client, config, log_func):
    """
    Scrapes detailed flight info, with retries and robust JSON parsing.
    """
    url = f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{departure_date}/no-return"
    print(f"      - Scraping detailed flight info for: {departure_date}")

    try:
        page.goto(url, timeout=90000, wait_until="domcontentloaded")
        try: page.get_by_role('button', name='Accept', exact=True).click(timeout=5000)
        except Error: pass

        first_card_selector = '[data-test="ResultCardWrapper"]'
        no_results_selector = '[data-test="NoResults"]'
        page.wait_for_selector(f"{first_card_selector}, {no_results_selector}", timeout=60000)

        if page.locator(no_results_selector).is_visible(): return []

        time.sleep(random.randint(5, 10))
        flight_cards = page.locator(first_card_selector).all()
        if not flight_cards: return []

        text_snippets = [card.inner_text() for card in flight_cards[:5]]
        combined_text = "\n\n---\n\n".join(text_snippets)
        if not combined_text: return []

        model_name = config['api_settings']['models']['openrouter']['default'] # Example
        print(f"        - Using model: {model_name}")

        prompt = f"""
        Analyze the provided plain text (separated by '---') and return a clean JSON object. Do not include any other text.
        For each flight, extract the following details:
        - departure_time, arrival_time, duration, airline_names (list), price (number), stops (string)
        Return a single key 'flights', which is a list of these objects.
        EXAMPLE JSON OUTPUT:
        {{
            "flights": [
                {{"departure_time": "20:25", "arrival_time": "09:35+1", "duration": "13h 10m", "airline_names": ["Ryanair"], "price": 403, "stops": "1 stop · Naples"}}
            ]
        }}
        TEXT:
        {combined_text}
        """

        log_func({"prompt_sent_to_api": prompt}, f"prompt_for_details_{departure_date}")

        for attempt in range(3):
            raw_content = ""
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "system", "content": "You are a data extraction expert that responds only in JSON."}, {"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    max_tokens=4096
                )
                raw_content = response.choices[0].message.content
                
                json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)

                if json_match:
                    json_string = json_match.group(0)
                    result = json.loads(json_string)
                    flights = result.get("flights", [])

                    if flights: flights.sort(key=lambda x: x.get('price', float('inf')))
                    
                    log_func(result, f"detailed_flights_{origin}_to_{destination}_{departure_date}")
                    return flights
                else:
                    raise ValueError("No valid JSON object could be extracted from the model's response.")

            except Exception as e:
                print(f"      - ❌ Attempt {attempt + 1} failed. Error: {e}")
                log_func({"error": str(e), "raw_response": raw_content}, f"detailed_flights_parsing_error_{origin}_{destination}")
                if attempt < 2: time.sleep(3)
        return []
    except Exception as e:
        print(f"      - ❌ ERROR: Could not get detailed flight info for {departure_date}. Error: {e}")
        return []
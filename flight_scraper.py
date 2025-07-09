import json
import time
import random
from playwright.sync_api import Page, Error, TimeoutError as PlaywrightTimeoutError
import re
from datetime import datetime, timedelta

# This function is unchanged from your original.
def extract_prices_from_calendar(page: Page) -> list:
    """
    Directly scrapes the full date and price from the calendar view using
    stable data-test attributes.
    """
    print("        - Directly parsing price data from calendar HTML...")
    daily_prices = []
    day_elements = page.locator('[data-test="CalendarDay"]').all()
    
    if not day_elements:
        print("        - ❌ No active calendar day elements found.")
        return []

    for day_element in day_elements:
        try:
            full_date = day_element.get_attribute('data-value')
            price_element = day_element.locator('[data-test="NewDatepickerPrice"]')
            price_text = price_element.inner_text(timeout=10000)
            
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
            continue
            
    if daily_prices:
        daily_prices.sort(key=lambda x: x.get('price', float('inf')))

    return daily_prices

def get_daily_prices_from_graph(page: Page, origin: str, destination: str, start_date: datetime.date, config: dict, log_func):
    days_to_search = config['search_parameters']['days_to_search']
    search_end_date = start_date + timedelta(days=days_to_search)
    initial_url = f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{start_date.strftime('%Y-%m-%d')}/no-return"
    print(f"    - Scraping all monthly price data from: {initial_url}")

    # --- NECESSARY CHANGE 1: Block unnecessary resources to speed up loading ---
    # This must be defined before page.goto() is called.
    def block_unnecessary_resources(route):
        if route.request.resource_type in ["image", "stylesheet", "font", "media"]:
            route.abort()
        else:
            route.continue_()
    page.route("**/*", block_unnecessary_resources)
    
    all_prices = {}
    last_exception = None

    try:
        for attempt in range(3):
            try:
                page.goto(initial_url, wait_until="domcontentloaded", timeout=90000)
                
                try:
                    page.get_by_role('button', name='Accept', exact=True).click(timeout=7000)
                    print("      - Cookie banner accepted.")
                except Error: pass
                
                # --- NECESSARY CHANGE 2: Wait for page to be ready, not for fixed time ---
                print("      - Waiting for initial results to load...")
                page.locator('[data-test="ResultCardWrapper-loading"]').first.wait_for(state='hidden', timeout=60000)
                print("      - Page is ready.")

                print("      - Clicking date input to reveal price calendar...")
                page.locator('[data-test="SearchFieldDateInput"]').click()

                print("      - Waiting for price calendar to be visible...")
                page.locator('[data-test="CalendarDay"]').first.wait_for(state='visible', timeout=45000)
                
                while True:
                    current_prices = extract_prices_from_calendar(page)
                    for price_data in current_prices:
                        all_prices[price_data['full_date']] = price_data

                    last_day_in_calendar_str = page.locator('[data-test="CalendarDay"]').last.get_attribute('data-value')
                    last_day_in_calendar = datetime.strptime(last_day_in_calendar_str, '%Y-%m-%d').date()

                    if last_day_in_calendar >= search_end_date:
                        break
                    else:
                        page.locator('[data-test="CalendarMoveNext"]').click()
                        time.sleep(2) # Small fixed wait for next month animation

                final_price_list = list(all_prices.values())
                
                if final_price_list:
                    final_price_list.sort(key=lambda x: x.get('price', float('inf')))
                
                log_func(final_price_list, f"direct_scrape_{origin}_to_{destination}")
                page.unroute("**/*", block_unnecessary_resources) # Cleanup
                return final_price_list

            except Exception as e:
                print(f"--- Attempt {attempt + 1} FAILED for price graph. Error: {e}")
                last_exception = e
                if attempt < 2: time.sleep(10)

        # --- NECESSARY CHANGE 3: Ensure error is raised if all retries fail ---
        print(f"--- All scraping attempts for price graph failed. ---")
        page.unroute("**/*", block_unnecessary_resources) # Cleanup
        if last_exception:
            raise last_exception
        return []

    finally:
        # Failsafe to ensure unrouting happens even if an unexpected error occurs
        # This prevents the routing from affecting other scraping functions
        page.unroute("**/*", block_unnecessary_resources)


# This function is unchanged from your original.
def get_detailed_flight_info(page, origin, destination, departure_date, client, config, log_func):
    url = f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{departure_date}/no-return"
    print(f"        - Scraping detailed flight info for: {departure_date}")

    try:
        page.goto(url, timeout=90000, wait_until="domcontentloaded")
        time.sleep(random.uniform(2, 4))

        try: 
            page.get_by_role('button', name='Accept', exact=True).click(timeout=15000)
            time.sleep(random.uniform(1, 2))
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

        model_name = config['api_settings']['models']['openrouter']['default']
        print(f"          - Using model: {model_name}")

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
                print(f"        - ❌ Attempt {attempt + 1} failed. Error: {e}")
                log_func({"error": str(e), "raw_response": raw_content}, f"detailed_flights_parsing_error_{origin}_{destination}")
                if attempt < 2: time.sleep(3)
        return []
    except Exception as e:
        print(f"        - ❌ ERROR: Could not get detailed flight info for {departure_date}. Error: {e}")
        raise e
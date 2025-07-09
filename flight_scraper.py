import json
import time
import random # ✅ MODIFICATION: Import random for delays
from playwright.sync_api import Page, Error, TimeoutError as PlaywrightTimeoutError
import re
from datetime import datetime, timedelta

# (The extract_prices_from_calendar function remains the same)
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

    all_prices = {}
    last_exception = None

    for attempt in range(3):
        try:
            page.goto(initial_url, timeout=90000)
            time.sleep(random.uniform(2, 4)) # ✅ MODIFICATION: Wait after page load

            try:
                page.get_by_role('button', name='Accept', exact=True).click(timeout=7000)
                print("      - Cookie banner accepted.")
                time.sleep(random.uniform(1, 2.5)) # ✅ MODIFICATION: Wait after click
            except Error: pass
            
            print("      - Clicking date input to reveal price calendar...")
            date_input = page.locator('[data-test="SearchFieldDateInput"]')
            date_input.wait_for(state='visible', timeout=30000)
            date_input.click()
            time.sleep(random.uniform(2, 3)) # ✅ MODIFICATION: Wait for calendar to render

            page.locator('[data-test="CalendarDay"]').first.wait_for(state='visible', timeout=30000)
            
            while True:
                # ... (rest of the logic is the same)
                current_prices = extract_prices_from_calendar(page)
                # ...
                if last_day_in_calendar >= search_end_date:
                    break
                else:
                    page.locator('[data-test="CalendarMoveNext"]').click()
                    time.sleep(random.uniform(2, 4)) # ✅ MODIFICATION: Wait for next month to load

            final_price_list = list(all_prices.values())
            # ...
            return final_price_list

        except Exception as e:
            print(f"--- Attempt {attempt + 1} FAILED for price graph. Error: {e}")
            last_exception = e
            if attempt < 2: time.sleep(10)

    print(f"--- All scraping attempts for price graph failed. ---")
    if last_exception:
        raise last_exception
    return []

# (The get_detailed_flight_info function would have similar random delays added)
def get_detailed_flight_info(page, origin, destination, departure_date, client, config, log_func):
    url = f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{departure_date}/no-return"
    print(f"        - Scraping detailed flight info for: {departure_date}")

    try:
        page.goto(url, timeout=90000, wait_until="domcontentloaded")
        time.sleep(random.uniform(2, 4)) # ✅ MODIFICATION: Wait after page load

        try: 
            page.get_by_role('button', name='Accept', exact=True).click(timeout=15000)
            time.sleep(random.uniform(1, 2)) # ✅ MODIFICATION: Wait after click
        except Error: pass

        # ... (rest of the function remains the same, including the error raising)

    except Exception as e:
        print(f"        - ❌ ERROR: Could not get detailed flight info for {departure_date}. Error: {e}")
        raise e
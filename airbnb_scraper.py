import json
import time
from playwright.sync_api import Page, Error
from urllib.parse import quote
import re
from datetime import datetime, timedelta
import random
import sys

# Seed the random number generator
random.seed(time.time())

def get_cheapest_accommodations(page, destination_city, specific_location_query, checkin, checkout, config, log_func):
    """
    Scrapes Airbnb using direct data extraction.
    This version includes debugging logic to pause on an error.
    """
    encoded_query = quote(specific_location_query)
    search_url = f"https://www.airbnb.com/s/homes?query={encoded_query}&checkin={checkin}&checkout={checkout}&adults=2&room_types%5B%5D=Private%20room"
    
    print(f"    - Navigating to Airbnb search: {specific_location_query} for dates {checkin} to {checkout}")

    try:
        page.goto(search_url, timeout=90000)

        # Handle potential translation pop-up
        translation_close_button = page.locator('button[aria-label="Close"]')
        try:
            translation_close_button.wait_for(state='visible', timeout=5000)
            print("    - Translation pop-up detected. Closing it...")
            translation_close_button.click()
            time.sleep(random.uniform(1, 2))
        except Error:
            print("    - No translation pop-up found, continuing.")

        page.wait_for_selector('[data-testid="listing-card-title"]', timeout=60000)
        time.sleep(random.uniform(2, 4))

    except Exception as e:
        print(f"      - ❌ ERROR: An exception occurred while loading the Airbnb search page. Error: {e}")
        return []

    listing_cards = page.locator('[data-testid="card-container"]').all()
    if not listing_cards:
        print("      - ❌ No listing cards found on the page.")
        return []

    print(f"    - Found {len(listing_cards)} listings. Extracting details directly.")
    scraped_accommodations = []
    
    try:
        num_nights_for_booking = (datetime.strptime(checkout, "%Y-%m-%d") - datetime.strptime(checkin, "%Y-%m-%d")).days
    except ValueError:
        num_nights_for_booking = 0

    for i, card in enumerate(listing_cards):
        title = "Unknown Listing" # Define title with a default value
        try:
            # --- ACTION --- Announce what we're doing
            title = card.locator('[data-testid="listing-card-name"]').inner_text(timeout=5000)
            print(f"--> Processing card {i+1}: '{title}'")

            try:
                link_suffix = card.locator('a').first.get_attribute('href')
                full_link = f"https://www.airbnb.com{link_suffix.split('?')[0]}"
            except Error:
                full_link = "N/A"

            total_accommodation_cost = 0
            
            # This selector is robust enough to handle regular and discounted price formats
            price_summary_element = card.locator('span:has-text("for"):has-text("night")').first
            price_summary_text = price_summary_element.inner_text(timeout=2000)
            
            price_match = re.search(r'(\d[\d,.]*)', price_summary_text)
            if price_match:
                total_accommodation_cost = int(float(price_match.group(1).replace(',', '')))
            else:
                raise ValueError("Price text found, but no number could be extracted.")

            # --- RATING EXTRACTION (CORRECTED) ---
            rating_text = "N/A"
            try:
                # Use a more specific container for the rating to be safe
                rating_element_container = card.locator('div.t1a9j9y7').first
                # The 'timeout' argument has been removed from is_visible()
                if rating_element_container.is_visible():
                    rating_text_full = rating_element_container.inner_text(timeout=500)
                    rating_match = re.search(r'([\d.]+)', rating_text_full)
                    if rating_match:
                        rating_text = rating_match.group(1)
            except Error:
                pass # It's okay if rating isn't found

            scraped_accommodations.append({
                "name": title, "total_accommodation_cost": total_accommodation_cost, "rating": rating_text,
                "link": full_link, "checkin": checkin, "checkout": checkout})

        except Exception as e:
            # --- ERROR HANDLING --- This block runs when something in the 'try' block fails
            print("\n----------------- ❌ ERROR ❌ -----------------")
            print(f"The script failed while trying to extract data for: '{title}'")
            print(f"Error Type: {type(e).__name__}, Message: {e}")
            print("\n--- HTML of the failing card ---")
            print(card.evaluate("node => node.outerHTML"))
            print("-------------------------------------------------")
            
            # --- PAUSE --- This keeps the script and browser open until you press Enter
            input("The browser is still open for inspection. Press Enter in this terminal to close the script.")
            
            # --- EXIT --- This stops the program
            sys.exit(1)
            
        time.sleep(random.uniform(0.5, 1.5))

    scraped_accommodations.sort(key=lambda x: x.get('total_accommodation_cost', float('inf')))
    print(f"    - Successfully extracted and sorted {len(scraped_accommodations)} listings.")
    return scraped_accommodations[:3]


def get_listing_calendar_availability(page: Page, listing_url: str, search_months: int = 6):
    """
    Navigates to a specific Airbnb listing page and scrapes its calendar for availability.
    """
    print(f"    - Scraping calendar for listing: {listing_url}")
    availability_data = {}
    
    try:
        page.goto(listing_url, timeout=90000)
        
        # Handle potential translation pop-up
        translation_close_button = page.locator('button[aria-label="Close"]')
        try:
            translation_close_button.wait_for(state='visible', timeout=5000)
            print("    - Translation pop-up detected. Closing it...")
            translation_close_button.click()
            time.sleep(random.uniform(1, 2))
        except Error:
            pass

        time.sleep(random.uniform(2, 4))

        # Try to open the calendar
        try:
            page.locator('[data-testid="change-dates-checkIn"]').click(timeout=3000)
            print("    - Clicked date input to ensure calendar is open.")
        except Error:
            try:
                page.locator('button:has-text("Check availability")').click(timeout=3000)
                print("    - Clicked 'Check availability' button to ensure calendar is open.")
            except Error:
                print("    - No specific button to open calendar found, assuming it's visible.")
        
        time.sleep(random.uniform(1, 2))

        # Scrape calendar data
        all_scraped_dates = set()
        for _ in range(search_months + 1):
            current_page_dates = set()
            
            visible_month_containers = page.locator('div[data-visible="true"]').all()
            if not visible_month_containers:
                visible_month_containers = [page]

            day_elements = []
            for container in visible_month_containers:
                day_elements.extend(container.locator('div[data-testid^="calendar-day-"]').all())
            
            if not day_elements:
                print("      - No calendar day elements found in visible months.")
                break

            for day_div in day_elements:
                try:
                    full_date_str = day_div.get_attribute('data-testid')
                    if not full_date_str: continue
                    
                    date_part = full_date_str.replace('calendar-day-', '')
                    date_obj = datetime.strptime(date_part, '%m/%d/%Y').strftime('%Y-%m-%d')
                    current_page_dates.add(date_obj)

                    is_blocked = day_div.get_attribute('data-is-day-blocked') == 'true'
                    parent_td = day_div.locator('xpath=..')
                    aria_disabled = parent_td.get_attribute('aria-disabled') == 'true'
                    is_available = not (is_blocked or aria_disabled)
                    
                    availability_data[date_obj] = is_available
                except (ValueError, Error):
                    continue
            
            if current_page_dates.issubset(all_scraped_dates):
                print("      - No new dates found on page. Ending calendar scan.")
                break
            
            all_scraped_dates.update(current_page_dates)

            # --- "NEXT MONTH" BUTTON (CORRECTED) ---
            try:
                next_button_selector = 'button[aria-label="Move forward to switch to the next month."]'
                next_button = page.locator(next_button_selector)

                # The 'timeout' argument is removed from is_visible()
                if next_button.is_visible():
                    next_button.click()
                    time.sleep(random.uniform(1, 2))
                else:
                    print("      - 'Next Month' button not visible. All visible months have been scraped.")
                    break
            except Error:
                print("      - Could not find or click 'Next Month' button. All visible months have been scraped.")
                break

    except Exception as e:
        print(f"    - ❌ ERROR scraping calendar for {listing_url}. Error: {type(e).__name__}, {e}")
        return {}

    print(f"    - Finished calendar scan for {listing_url}. Found {len(availability_data)} dates.")
    return availability_data
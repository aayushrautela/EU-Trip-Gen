import json
import time
from playwright.sync_api import Page, Error
from urllib.parse import quote
import re
from datetime import datetime, timedelta
import random

random.seed(time.time())

def get_cheapest_accommodations(page, destination_city, specific_location_query, checkin, checkout, config, log_func):
    """
    Scrapes Airbnb using direct data extraction.
    Tries to extract the TOTAL price and falls back to per-night calculation if needed.
    Includes robust pop-up handling.
    """
    encoded_query = quote(specific_location_query)
    search_url = f"https://www.airbnb.com/s/homes?query={encoded_query}&checkin={checkin}&checkout={checkout}&adults=2&room_types%5B%5D=Private%20room"
    
    print(f"    - Navigating to Airbnb search: {specific_location_query} for dates {checkin} to {checkout}")

    try:
        page.goto(search_url, timeout=90000)

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
        try:
            try:
                title = card.locator('[data-testid="listing-card-name"]').inner_text(timeout=5000)
            except Error:
                title = "Unknown Listing"

            try:
                link_suffix = card.locator('a').first.get_attribute('href')
                full_link = f"https://www.airbnb.com{link_suffix.split('?')[0]}"
            except Error:
                full_link = "N/A"

            total_accommodation_cost = 0
            try:
                total_price_element = card.locator('xpath=//button//span[contains(text(), "total")]').first
                total_price_text = total_price_element.inner_text(timeout=5000)
                price_match = re.search(r'(\d[\d,.]*)', total_price_text)
                if not price_match: raise ValueError("Total price text did not contain a number.")
                total_accommodation_cost = int(float(price_match.group(1).replace(',', '')))
            except (Error, ValueError):
                try:
                    price_element = card.locator("//span[contains(text(), 'night')]/preceding-sibling::span[last()]")
                    price_text = price_element.inner_text(timeout=1000)
                    price_match_fallback = re.search(r'(\d[\d,.]*)', price_text)
                    if price_match_fallback:
                        price_per_night_fallback = int(float(price_match_fallback.group(1).replace(',', '')))
                        total_accommodation_cost = price_per_night_fallback * num_nights_for_booking if num_nights_for_booking > 0 else price_per_night_fallback
                except Error:
                    pass 
            
            if total_accommodation_cost == 0:
                print(f"      - Could not determine a valid total accommodation cost for '{title}'. Skipping this card.")
                continue

            rating_text = "N/A"
            try:
                rating_element = card.locator('div.g1qv1ctd > div.t1a9j9y7')
                if rating_element.is_visible(timeout=500):
                    rating_span = rating_element.locator('span[aria-hidden="true"]')
                    rating_text = rating_span.inner_text(timeout=500)
            except Error:
                pass

            scraped_accommodations.append({
                "name": title, "total_accommodation_cost": total_accommodation_cost, "rating": rating_text,
                "link": full_link, "checkin": checkin, "checkout": checkout})
        except Exception as e:
            print(f"      - Could not process a listing card ({i+1}) due to unexpected error, skipping. Error: {e}")
            continue
        
        time.sleep(random.uniform(0.5, 1.5))

    scraped_accommodations.sort(key=lambda x: x.get('total_accommodation_cost', float('inf')))
    print(f"    - Successfully extracted and sorted {len(scraped_accommodations)} listings.")
    return scraped_accommodations[:3]


def get_listing_calendar_availability(page: Page, listing_url: str, search_months: int = 6):
    """
    Navigates to a specific Airbnb listing page and scrapes its calendar for availability.
    This version correctly scrapes only VISIBLE months to get an accurate date count.
    """
    print(f"    - Scraping calendar for listing: {listing_url}")
    availability_data = {}
    
    try: 
        page.goto(listing_url, timeout=90000)
        
        translation_close_button = page.locator('button[aria-label="Close"]')
        try:
            translation_close_button.wait_for(state='visible', timeout=5000)
            print("    - Translation pop-up detected. Closing it...")
            translation_close_button.click()
            time.sleep(random.uniform(1, 2))
        except Error:
            pass

        time.sleep(random.uniform(2, 4)) 

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

        # --- CORRECTED CALENDAR SCRAPING LOGIC ---
        all_scraped_dates = set()
        for _ in range(search_months + 1):
            current_page_dates = set()
            
            # THIS IS THE FIX: Only find day elements within VISIBLE month containers.
            visible_month_containers = page.locator('div[data-visible="true"]').all()
            if not visible_month_containers:
                # Fallback to the whole page if the specific visible container isn't found
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

            try:
                # This selector is based on the new HTML provided by the user.
                next_button_selector = 'button[aria-label="Move forward to switch to the next month."]'
                next_button = page.locator(next_button_selector)

                if next_button.is_visible(timeout=1000):
                    next_button.click()
                    time.sleep(random.uniform(1, 2)) 
                else:
                    print("      - 'Next Month' button not visible. All visible months have been scraped.")
                    break 
            except Error:
                print("      - Could not find or click 'Next Month' button. All visible months have been scraped.")
                break

    except Exception as e: 
        print(f"    - ❌ ERROR scraping calendar for {listing_url}. Error: {e}")
        return {} 

    print(f"    - Finished calendar scan for {listing_url}. Found {len(availability_data)} dates.")
    return availability_data
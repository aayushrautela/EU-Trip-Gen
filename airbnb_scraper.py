import json
import time
from playwright.sync_api import Page, Error
from urllib.parse import quote
import re
from datetime import datetime, timedelta
import random
import sys

# Seed random generator
random.seed(time.time())

def get_cheapest_accommodations(page, destination_city, specific_location_query, checkin, checkout, config, log_func):
    """Scrapes Airbnb for cheapest listings."""
    encoded_query = quote(specific_location_query)
    search_url = f"https://www.airbnb.com/s/homes?query={encoded_query}&checkin={checkin}&checkout={checkout}&adults=2&room_types%5B%5D=Private%20room"
    
    print(f" - Navigating to Airbnb: {specific_location_query}")

    try:
        page.goto(search_url, timeout=90000)

        # Close translation pop-up
        translation_close_button = page.locator('button[aria-label="Close"]')
        try:
            translation_close_button.wait_for(state='visible', timeout=5000)
            translation_close_button.click()
            time.sleep(random.uniform(1, 2))
        except Error:
            pass # No pop-up

        page.wait_for_selector('[data-testid="listing-card-title"]', timeout=60000)
        time.sleep(random.uniform(2, 4))

    except Exception as e:
        print(f" - ❌ ERROR: Loading Airbnb search page failed. {e}")
        return []

    listing_cards = page.locator('[data-testid="card-container"]').all()
    if not listing_cards:
        print(" - ❌ No listings found.")
        return []

    print(f" - Found {len(listing_cards)} listings.")
    scraped_accommodations = []

    for i, card in enumerate(listing_cards):
        title = "Unknown Listing"
        try:
            # Announce processing
            title = card.locator('[data-testid="listing-card-name"]').inner_text(timeout=5000)
            print(f"--> Processing: '{title}'")

            try:
                link_suffix = card.locator('a').first.get_attribute('href')
                full_link = f"https://www.airbnb.com{link_suffix.split('?')[0]}"
            except Error:
                full_link = "N/A"

            total_accommodation_cost = 0
            
            # Get price from summary
            price_summary_element = card.locator('span:has-text("for"):has-text("night")').first
            price_summary_text = price_summary_element.inner_text(timeout=2000)
            
            price_match = re.search(r'(\d[\d,.]*)', price_summary_text)
            if price_match:
                total_accommodation_cost = int(float(price_match.group(1).replace(',', '')))
            else:
                raise ValueError("Could not extract price.")

            # Get rating
            rating_text = "N/A"
            try:
                rating_element_container = card.locator('div.t1a9j9y7').first
                if rating_element_container.is_visible():
                    rating_text_full = rating_element_container.inner_text(timeout=500)
                    rating_match = re.search(r'([\d.]+)', rating_text_full)
                    if rating_match:
                        rating_text = rating_match.group(1)
            except Error:
                pass # No rating found

            scraped_accommodations.append({
                "name": title, "total_accommodation_cost": total_accommodation_cost, "rating": rating_text,
                "link": full_link, "checkin": checkin, "checkout": checkout})

        except Exception as e:
            # Error handling
            print("\n----------------- ❌ ERROR ❌ -----------------")
            print(f"Failed on: '{title}'")
            print(f"Error: {type(e).__name__}, {e}")
            print("\n--- Failing Card HTML ---")
            print(card.evaluate("node => node.outerHTML"))
            print("-------------------------------------------------")
            
            # Pause for inspection
            input("Browser is open for inspection. Press Enter to exit.")
            
            # Stop program
            sys.exit(1)
            
        time.sleep(random.uniform(0.5, 1.5))

    scraped_accommodations.sort(key=lambda x: x.get('total_accommodation_cost', float('inf')))
    print(f" - Extracted and sorted {len(scraped_accommodations)} listings.")
    return scraped_accommodations[:3]


def get_listing_calendar_availability(page: Page, listing_url: str, search_months: int = 6):
    """Scrapes Airbnb calendar availability."""
    print(f" - Scraping calendar: {listing_url}")
    availability_data = {}
    
    try:
        page.goto(listing_url, timeout=90000)
        
        # Close translation pop-up
        translation_close_button = page.locator('button[aria-label="Close"]')
        try:
            translation_close_button.wait_for(state='visible', timeout=5000)
            translation_close_button.click()
            time.sleep(random.uniform(1, 2))
        except Error:
            pass

        time.sleep(random.uniform(2, 4))

        # Open calendar view
        try:
            page.locator('[data-testid="change-dates-checkIn"]').click(timeout=3000)
        except Error:
            try:
                page.locator('button:has-text("Check availability")').click(timeout=3000)
            except Error:
                pass # Calendar likely visible
        
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
                break # No new dates
            
            all_scraped_dates.update(current_page_dates)

            # Click "Next month"
            try:
                next_button_selector = 'button[aria-label="Move forward to switch to the next month."]'
                next_button = page.locator(next_button_selector)

                if next_button.is_visible():
                    next_button.click()
                    time.sleep(random.uniform(1, 2))
                else:
                    break # No next button
            except Error:
                break

    except Exception as e:
        print(f" - ❌ ERROR scraping calendar. {type(e).__name__}, {e}")
        return {}

    print(f" - Finished calendar scan for {listing_url}.")
    return availability_data
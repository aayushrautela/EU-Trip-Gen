# In flight_scraper.py

def get_daily_prices_from_graph(page: Page, origin: str, destination: str, start_date: datetime.date, config: dict, log_func):
    """
    Scrapes the price calendar with a more robust waiting strategy.
    """
    days_to_search = config['search_parameters']['days_to_search']
    search_end_date = start_date + timedelta(days=days_to_search)
    
    initial_url = f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{start_date.strftime('%Y-%m-%d')}/no-return"
    print(f"    - Scraping all monthly price data from: {initial_url}")

    all_prices = {}
    last_exception = None

    for attempt in range(3):
        try:
            page.goto(initial_url, timeout=90000)
            
            # Try to accept cookies if the banner appears
            try:
                page.get_by_role('button', name='Accept', exact=True).click(timeout=7000)
                print("      - Cookie banner accepted.")
                time.sleep(random.uniform(1, 2))
            except Error:
                print("      - Cookie banner did not appear.")

            # ✅ MODIFICATION: Wait for the main flight results loading skeletons to disappear
            print("      - Waiting for initial flight results to load...")
            loading_skeleton = page.locator('[data-test="ResultCardWrapper-loading"]').first
            loading_skeleton.wait_for(state='hidden', timeout=60000)
            print("      - Loading complete. Page is ready.")
            
            print("      - Clicking date input to reveal price calendar...")
            date_input = page.locator('[data-test="SearchFieldDateInput"]')
            date_input.click()

            # ✅ MODIFICATION: Wait longer for the calendar itself to appear after the click
            print("      - Waiting for price calendar to be visible...")
            page.locator('[data-test="CalendarDay"]').first.wait_for(state='visible', timeout=45000)
            print("      - Price calendar is visible.")
            
            # Loop to click "Next Month" if needed
            while True:
                print("      - Parsing currently visible month(s)...")
                current_prices = extract_prices_from_calendar(page)
                for price_data in current_prices:
                    all_prices[price_data['full_date']] = price_data

                print(f"      - Found {len(current_prices)} prices in current view. Total unique prices so far: {len(all_prices)}")

                last_day_in_calendar_str = page.locator('[data-test="CalendarDay"]').last.get_attribute('data-value')
                last_day_in_calendar = datetime.strptime(last_day_in_calendar_str, '%Y-%m-%d').date()

                if last_day_in_calendar >= search_end_date:
                    print("      - Calendar now shows all required dates. Finalizing price list.")
                    break
                else:
                    print("      - Required search period extends beyond visible calendar. Clicking next month...")
                    page.locator('[data-test="CalendarMoveNext"]').click()
                    time.sleep(random.uniform(2, 4))

            final_price_list = list(all_prices.values())
            
            if final_price_list:
                final_price_list.sort(key=lambda x: x.get('price', float('inf')))
            
            log_func(final_price_list, f"direct_scrape_{origin}_to_{destination}")
            print(f"    - Successfully parsed a total of {len(final_price_list)} unique daily prices.")
            return final_price_list

        except Exception as e:
            print(f"--- Attempt {attempt + 1} FAILED for price graph. Error: {e}")
            last_exception = e
            if attempt < 2: 
                time.sleep(5) # Shorter sleep between retries

    print(f"--- All scraping attempts for price graph failed. ---")
    if last_exception:
        raise last_exception
    return []
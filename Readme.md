# Trip Explorer Optimizer
###[Deprecated] This project is no longer maintained due to Kiwi.com's enhanced anti-bot protections, which prevent reliable automated scraping.
EU-Trip-Gen is an AI-assisted automated travel optimization system designed to scrape and aggregate flight data from Kiwi.com and accommodation listings from Airbnb. It employs Large Language Models to parse unstructured data into structured formats and uses Python-based scalable automation for efficient data collection and processing. The system ranks potential trips by cost-effectiveness and exploration hours, delivering optimized travel itineraries based on configurable search parameters.
## Features

* Scrapes **flight price calendars** and **detailed flight options** from Kiwi.com
* Scrapes **Airbnb listings** and their **calendar availability**
* Estimates **exploration hours**, **trip cost**, and **cost-effectiveness**
* Uses **LLM-based data parsing** via OpenRouter or DeepSeek API
* Saves top results in `final_trips.json`

## Project Structure

```
.
├── main_controller.py           # Entry point and core logic
├── config.json                  # Configuration file (API, cities, search params)
├── api_handler.py              # Rotating API client for OpenAI-compatible models
├── flight_scraper.py           # Flight price scraping from Kiwi.com
├── airbnb_scraper.py           # Airbnb listing scraping and calendar parsing
├── run_log.txt                  # Optional: log file for AI responses
└── final_trips.json             # Stores best trips found
```

## Setup

### 1. Install Dependencies

```bash
pip install playwright openai
playwright install
```

### 2. Configuration

Edit the `config.json` file to control:

* **API Settings**:

  * `provider`: Choose between `openrouter` or `deepseek`
  * `keys`: Comma-separated list of API keys
  * `models`: Set default and task-specific model names per provider

* **Search Parameters**:

  * `origin_city_id`: City code for trip origin (e.g., `warsaw-poland`)
  * `start_date`: Search start date (format: `YYYY-MM-DD`)
  * `days_to_search`: Number of days to scan after `start_date`
  * `max_trip_duration_days`: Maximum allowed length of a trip
  * `num_adults`: Number of travelers
  * `min_exploration_hours`: Minimum required hours for exploration at destination
  * `cookie_wait_seconds`: Wait time after accepting cookies
  * `day_starts_at_hour` / `day_ends_at_hour`: Hours of the day for usable time
  * `airport_buffer_hours`: Buffer hours for arrival/departure flight time

* **Destination Control**:

  * Enable or disable countries and cities
  * Example:

    ```json
    "italy": {
      "enabled": true,
      "cities": {
        "rome-italy": "Rome",
        "venice-italy": "Venice"
      }
    }
    ```

* **Paths**:

  * `log_file`: File to log AI outputs and errors
  * `results_file`: File where results will be saved

### 3. Run the Script

```bash
python main_controller.py
```

The browser runs in **headless mode** by default. If you want to **observe scraping in a visible browser**, you can change this in `main_controller.py`:

```python
browser = p.chromium.launch(headless=False)
```

## Output

* Printed best trip results per destination
* Final data stored in `final_trips.json`

Each entry contains:

* Travel dates
* Cost per hour
* Flight and Airbnb details

## Notes

* Browser must stay open if running in non-headless mode
* Tool depends on UI structure of Kiwi.com and Airbnb — major site updates may require adjustments
* The AI is only used for parsing unstructured flight text into structured JSON

## License

MIT

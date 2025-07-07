# api_client.py
import requests
import json
import re

def call_openrouter(api_key: str, prompt: str) -> dict:
    """
    Calls the OpenRouter API with the single free model, extracts the JSON from
    the response, and returns it as a Python dictionary.
    """
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps({
                "model": "deepseek/deepseek-r1:free", # Using the one free model for all calls
                "messages": [
                    {"role": "system", "content": "You are a highly accurate data extraction assistant that responds ONLY in valid JSON format. Do not include any other text, explanations, or conversational filler in your response."},
                    {"role": "user", "content": prompt}
                ]
            })
        )
        response.raise_for_status()

        response_text = response.json()['choices'][0]['message']['content']

        # --- ROBUST JSON EXTRACTION ---
        # Find the JSON block using a regular expression
        # This looks for a string starting with { and ending with }
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)

        if json_match:
            json_string = json_match.group(0)
            return json.loads(json_string)
        else:
            print(f"  - ❌ ERROR: No JSON object found in the model's response.")
            print(f"  - Raw Response Text: {response_text}")
            return {}

    except requests.exceptions.RequestException as e:
        print(f"  - ❌ ERROR: API request to OpenRouter failed. Error: {e}")
        return {}
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"  - ❌ ERROR: Failed to parse response from OpenRouter. Error: {e}")
        return {}
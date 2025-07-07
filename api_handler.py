# api_handler.py

from openai import OpenAI, RateLimitError
import sys
import time

# --- Corrected Wrapper Classes ---

# This class represents the '.completions' level
class _CompletionsWrapper:
    def __init__(self, owner):
        """
        Initializes the wrapper for the 'completions' object.
        Args:
            owner: The instance of the main RotatingClient.
        """
        self._owner = owner

    def create(self, **kwargs):
        """
        Forwards the 'create' call to the owner's execution method.
        This is the final step in the chain: client.chat.completions.create()
        """
        return self._owner._execute_completion_with_rotation(**kwargs)

# This class represents the '.chat' level
class _ChatWrapper:
    def __init__(self, owner):
        """
        Initializes the wrapper for the 'chat' object. It holds the
        'completions' object.
        Args:
            owner: The instance of the main RotatingClient.
        """
        self.completions = _CompletionsWrapper(owner)


class RotatingClient:
    """
    A wrapper for the OpenAI client that handles multiple API keys and rotates
    them automatically when a rate limit error is encountered.
    This version correctly mimics the 'client.chat.completions.create()' structure.
    """
    def __init__(self, config):
        """
        Initializes the rotating client from the configuration.
        """
        provider = config['api_settings'].get('provider')
        api_key_name = f'{provider}_key'
        
        if provider == 'openrouter':
            self.base_url = "https://openrouter.ai/api/v1"
            print("--- Initializing RotatingClient for OpenRouter ---")
        elif provider == 'deepseek':
            self.base_url = "https://api.deepseek.com/v1"
            print("--- Initializing RotatingClient for DeepSeek ---")
        else:
            print(f"FATAL ERROR: Unknown API provider '{provider}' in config.json. Please use 'openrouter' or 'deepseek'.")
            sys.exit(1)

        key_string = config['api_settings']['keys'].get(api_key_name)
        
        if not key_string or "YOUR_API_KEY_HERE" in key_string:
            print(f"FATAL ERROR: API key(s) for '{provider}' are missing or not set in config.json under '{api_key_name}'.")
            print("Please provide keys as a comma-separated string: \"key1,key2,key3\"")
            sys.exit(1)

        self.keys = [key.strip() for key in key_string.split(',')]
        self.current_key_index = 0
        
        # This now correctly creates the client.chat.completions structure
        self.chat = _ChatWrapper(self)
        
        print(f"--- Loaded {len(self.keys)} API key(s). ---")

    def _get_current_client(self):
        """
        Initializes an OpenAI client with the current key.
        """
        key = self.keys[self.current_key_index]
        return OpenAI(base_url=self.base_url, api_key=key)

    def _rotate_key(self):
        """
        Moves to the next key in the list.
        """
        self.current_key_index = (self.current_key_index + 1) % len(self.keys)
        print(f"      - Rotated to key #{self.current_key_index + 1}")

    def _execute_completion_with_rotation(self, **kwargs):
        """
        Executes the API call, attempting with each key until one succeeds
        or all have been rate-limited.
        """
        start_index = self.current_key_index
        
        for i in range(len(self.keys)):
            client = self._get_current_client()
            try:
                print(f"    - Attempting API call with key #{self.current_key_index + 1}...")
                response = client.chat.completions.create(**kwargs)
                return response
            
            except RateLimitError as e:
                print(f"      - ❌ Key #{self.current_key_index + 1} is rate-limited.")
                self._rotate_key()
                if self.current_key_index == start_index:
                    print("      - ❌ All available API keys are currently rate-limited. Stopping attempt.")
                    raise e
            
            except Exception as e:
                print(f"      - ❌ An unexpected API error occurred with key #{self.current_key_index + 1}: {e}")
                self._rotate_key()
                if self.current_key_index == start_index:
                   print("      - ❌ All available API keys failed with errors. Stopping attempt.")
                   raise e

        raise Exception("Failed to get a response from the API after trying all available keys.")


def initialize_client(config):
    """
    This function acts as a factory, returning an instance of our new
    RotatingClient, which will be used throughout the application.
    """
    return RotatingClient(config)
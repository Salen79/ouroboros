# utils.py (for shared security functions if any)
import os

# Example: Load API keys from environment variables
# For production, use more robust secrets management
API_KEY = os.getenv("API_KEY")

def verify_api_key(key: str) -> bool:
    # In a real application, this would involve checking against a database or secure store
    return key == API_KEY

# Add other security-related functions as needed

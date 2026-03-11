import os

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Database configuration (example)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./prism.db")

# Other configurations
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1")
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key") # Use a strong, unique key in production


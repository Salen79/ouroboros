import logging
import sys

def setup_logging():
    log_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) # Default level, can be overridden by specific handlers

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    # Add more handlers if needed (e.g., file handler for production logs)
    # In production, you may want different levels and handlers

# Call setup_logging() when the application starts

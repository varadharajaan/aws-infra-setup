#!/usr/bin/env python3

import logging
import os
import sys
from datetime import datetime

from colorama import Fore, Style, init

# Initialize colorama for cross-platform colored output
init(autoreset=True)


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""

    COLORS = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, Fore.WHITE)
        record.levelname = f"{log_color}{record.levelname}{Style.RESET_ALL}"
        return super().format(record)


class IAMLogger:
    """Enhanced logger for IAM user management operations"""

    def __init__(self, name: str, operation: str = "general"):
        self.name = name
        self.operation = operation
        self.logger = self._setup_logger()
        self.start_time = datetime.now()

    def _setup_logger(self) -> logging.Logger:
        """Setup logger with file and console handlers"""
        logger = logging.getLogger(self.name)

        # Clear existing handlers to avoid duplicates
        if logger.handlers:
            logger.handlers.clear()

        logger.setLevel(logging.DEBUG)

        # Create logs directory if not exists
        os.makedirs("logs", exist_ok=True)

        # Create timestamped log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"logs/{timestamp}_{self.operation}_{self.name}.log"

        # File handler - stores all levels
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)

        # Console handler - shows INFO and above with colors
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = ColoredFormatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
        )
        console_handler.setFormatter(console_formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        # Log the start of the operation
        logger.info(f"Starting {self.operation} operation - Log file: {log_file}")

        return logger

    def info(self, message: str):
        """Log info message"""
        self.logger.info(message)

    def debug(self, message: str):
        """Log debug message"""
        self.logger.debug(message)

    def warning(self, message: str):
        """Log warning message"""
        self.logger.warning(message)

    def error(self, message: str):
        """Log error message"""
        self.logger.error(message)

    def critical(self, message: str):
        """Log critical message"""
        self.logger.critical(message)

    def log_user_action(
        self, username: str, action: str, status: str, details: str = ""
    ):
        """Log specific user actions with structured format"""
        message = f"USER:{username} | ACTION:{action} | STATUS:{status}"
        if details:
            message += f" | DETAILS:{details}"

        if status.upper() in ["SUCCESS", "COMPLETED", "CREATED"]:
            self.info(message)
        elif status.upper() in ["FAILED", "ERROR"]:
            self.error(message)
        elif status.upper() in ["SKIPPED", "WARNING"]:
            self.warning(message)
        else:
            self.info(message)

    def log_account_action(
        self, account_name: str, action: str, status: str, details: str = ""
    ):
        """Log account-level actions"""
        message = f"ACCOUNT:{account_name} | ACTION:{action} | STATUS:{status}"
        if details:
            message += f" | DETAILS:{details}"

        if status.upper() in ["SUCCESS", "CONNECTED"]:
            self.info(message)
        elif status.upper() in ["FAILED", "ERROR"]:
            self.error(message)
        else:
            self.info(message)

    def log_summary(
        self, total_processed: int, successful: int, failed: int, skipped: int = 0
    ):
        """Log operation summary"""
        self.info("=" * 50)
        self.info("OPERATION SUMMARY")
        self.info("=" * 50)
        self.info(f"Total processed: {total_processed}")
        self.info(f"Successful: {successful}")
        self.info(f"Failed: {failed}")
        if skipped > 0:
            self.info(f"Skipped: {skipped}")

        # Calculate duration
        duration = datetime.now() - self.start_time
        self.info(f"Operation duration: {duration}")
        self.info("=" * 50)

    def log_credentials_saved(self, filepath: str, count: int):
        """Log when credentials are saved"""
        self.info(f"Credentials saved to: {filepath}")
        self.info(f"Total credentials saved: {count}")

    def log_resource_cleanup(
        self, username: str, resource_type: str, resource_id: str, status: str
    ):
        """Log resource cleanup actions"""
        message = f"USER:{username} | RESOURCE:{resource_type} | ID:{resource_id} | STATUS:{status}"

        if status.upper() in ["DELETED", "REMOVED", "DEACTIVATED"]:
            self.info(message)
        elif status.upper() in ["FAILED", "ERROR"]:
            self.error(message)
        else:
            self.debug(message)


def setup_logger(name: str, operation: str = "general") -> IAMLogger:
    """Factory function to create logger instances"""
    return IAMLogger(name, operation)


# Example usage and testing
if __name__ == "__main__":
    # Test the logger
    logger = setup_logger("test", "testing")

    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.debug("This is a debug message (only in file)")

    logger.log_user_action(
        "test_user01", "CREATE", "SUCCESS", "User created with all permissions"
    )
    logger.log_account_action(
        "account01", "CONNECT", "SUCCESS", "Connected to AWS account"
    )
    logger.log_resource_cleanup("test_user01", "ACCESS_KEY", "AKIA123456", "DELETED")

    logger.log_summary(5, 4, 1, 0)

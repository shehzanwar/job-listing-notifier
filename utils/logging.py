import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(settings: dict, logger_name: str = None) -> logging.Logger:
    """Configure console + rotating file logging from settings.yaml's `logging` section."""
    log_cfg = settings.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO"))
    log_file = log_cfg.get("file", "logs/notifier.log")
    max_bytes = log_cfg.get("max_size_mb", 10) * 1024 * 1024
    backup_count = log_cfg.get("backup_count", 5)

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )

    root = logging.getLogger(logger_name)
    root.setLevel(level)

    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return root

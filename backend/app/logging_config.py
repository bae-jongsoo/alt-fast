"""로깅 설정 — trade_decision, order_history 전용 로그 파일."""

import logging.config

LOG_DIR = "/var/log/alt-fast"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        "plain": {
            "format": "%(message)s",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "stderr": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
            "level": "ERROR",
        },
        "trade_decision_file": {
            "class": "logging.FileHandler",
            "formatter": "plain",
            "filename": f"{LOG_DIR}/trade_decision.log",
        },
        "order_history_file": {
            "class": "logging.FileHandler",
            "formatter": "plain",
            "filename": f"{LOG_DIR}/order_history.log",
        },
    },
    "loggers": {
        "trade_decision": {
            "handlers": ["trade_decision_file"],
            "level": "INFO",
            "propagate": False,
        },
        "order_history": {
            "handlers": ["order_history_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["stdout", "stderr"],
        "level": "INFO",
    },
}


def configure_logging() -> None:
    logging.config.dictConfig(LOGGING)

from opentelemetry import trace

import logging


def info(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.INFO, msg=msg)


def debug(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.DEBUG, msg=msg)


def warning(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.WARNING, msg=msg)


def error(logger: logging.Logger, msg: str):
    log(logger=logger, level=logging.ERROR, msg=msg)


def log(logger: logging.Logger, level: int, msg: str):
    if logger.isEnabledFor(level):
        span = trace.get_current_span()
        if span:
            span.add_event("log", {"level": level, "msg": msg})

        logger.log(level=level, msg=msg)

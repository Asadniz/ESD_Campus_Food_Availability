"""JSON logging to stdout.

Docker captures stdout, Filebeat reads Docker's log files, so the app never
touches files or the network for logging. One log line = one JSON object with
time, service, severity, message and (when inside a request) request_id.
"""
import contextvars
import datetime
import json
import logging
import sys

from .. import config

# Set by the middleware for every request; read by the formatter on every log call.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        when = datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
        doc = {
            "time": when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z",
            "service": config.SERVICE_NAME,
            "severity": record.levelname,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            doc["request_id"] = request_id
        doc.update(getattr(record, "fields", {}))
        if record.exc_info:
            doc["error_type"] = record.exc_info[0].__name__
            doc["stack"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def log_event(logger: logging.Logger, level: int, event: str, message: str, **fields) -> None:
    """Log a message plus structured fields. `event` is a short stable name to search on."""
    logger.log(level, message, extra={"fields": {"event": event, **fields}})

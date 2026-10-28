"""
The progress lines and the log file of upload_filings.py.
"""

from datetime import datetime, timedelta


def format_duration(seconds):
    """
    A length of time as "8.4s", "2m 05s" or "1h 02m".
    """
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes, rest = divmod(int(seconds), 60)

    if minutes < 60:
        return f"{minutes}m {rest:02d}s"

    return f"{minutes // 60}h {minutes % 60:02d}m"


RECENT = 20  # the estimate averages the last 20 filings, so it follows how hard the scans are
MIN_FOR_ESTIMATE = 3  # no estimate before this many filings: the first one includes the start-up


def estimate_remaining(gaps, remaining):
    """
    Seconds left, from the recent time per filing.  None if there is not enough to go on yet.
    """
    if len(gaps) < MIN_FOR_ESTIMATE or remaining <= 0:
        return None

    return sum(gaps) / len(gaps) * remaining


def progress_line(done, total, filing_id, error, since_last, elapsed, dry_run=False, left=None, now=None):
    """
    The line printed when a filing finishes, for example
    "[12/50] saved filing 172  (took 8.4s, 1m 42s so far, about 5m 20s left, done around 14:06)".
    Filings overlap (the next is OCRed while the last uploads), so "took" is the time since the
    previous filing finished.
    """
    done_word = "checked" if dry_run else "saved"
    result = f"FAILED filing {filing_id}: {error}" if error else f"{done_word} filing {filing_id}"
    line = f"[{done}/{total}] {result}  (took {format_duration(since_last)}, {format_duration(elapsed)} so far"

    if left is not None:
        finish = (now or datetime.now()) + timedelta(seconds=left)
        line += f", about {format_duration(left)} left, done around {finish:%H:%M}"

    return line + ")"


class Tee:
    """
    Sends what is written to several streams, so a run prints to the screen and to the log file.
    """

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def log_name(started, done=None, failed=0):
    """
    The log file's name: when the run started and how many filings it handled, for example
    2026-10-28_14-05-33_50-filings.txt, or ..._50-filings_2-failed.txt.  While the run is going
    the name ends in _running.txt.
    """
    name = f"{started:%Y-%m-%d_%H-%M-%S}_" + ("running" if done is None else f"{done}-filings")
    return name + (f"_{failed}-failed" if failed else "") + ".txt"

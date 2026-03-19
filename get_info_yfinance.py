import os
import sys


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_report.sources.yfinance import extract_yfinance_info  # noqa: E402,F401
from b3_report.sources.yfinance import format_yfinance_data as format_yfinace_data  # noqa: E402,F401
from b3_report.sources.yfinance import get_yfinance_data  # noqa: E402,F401

import os
import sys


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_report.sources.fundamentus import StockInfo  # noqa: E402,F401
from b3_report.sources.fundamentus import extract_stock_info  # noqa: E402,F401
from b3_report.sources.fundamentus import format_complementary_stock_info  # noqa: E402,F401
from b3_report.sources.fundamentus import get_complementary_data  # noqa: E402,F401

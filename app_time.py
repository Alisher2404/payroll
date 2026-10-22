"""Business dates are always in Dushanbe, including on UTC servers."""
from datetime import datetime
from zoneinfo import ZoneInfo

DUSHANBE = ZoneInfo('Asia/Dushanbe')


def now():
    return datetime.now(DUSHANBE)


def today():
    return now().date()

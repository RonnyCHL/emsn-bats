"""Zonsopgang/ondergang berekening voor nacht-modus.

Gebruikt een vereenvoudigd algoritme (geen externe dependencies).
Nauwkeurigheid: ~2 minuten, ruim voldoende voor vleermuismonitoring.
"""

import math
from datetime import date, datetime, timedelta, timezone


def _sun_times(
    lat: float, lon: float, dt: date
) -> tuple[datetime, datetime]:
    """Bereken zonsopgang en zonsondergang voor een locatie en datum.

    Returns:
        Tuple van (zonsopgang, zonsondergang) als UTC datetime.
    """
    # Dag van het jaar
    n = dt.timetuple().tm_yday

    # Zonsdeclinatie (graden)
    declination = -23.44 * math.cos(math.radians(360 / 365 * (n + 10)))

    # Uurhoek bij zonsopgang (graden)
    lat_rad = math.radians(lat)
    decl_rad = math.radians(declination)

    cos_hour = -math.tan(lat_rad) * math.tan(decl_rad)
    cos_hour = max(-1.0, min(1.0, cos_hour))  # Clamp voor poolgebieden

    hour_angle = math.degrees(math.acos(cos_hour))

    # Equation of time (minuten) - correctie voor elliptische baan
    b = math.radians(360 / 365 * (n - 81))
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)

    # Zonne-noon in UTC (minuten na middernacht)
    solar_noon_min = 720 - 4 * lon - eot

    # Zonsopgang en -ondergang
    sunrise_min = solar_noon_min - 4 * hour_angle
    sunset_min = solar_noon_min + 4 * hour_angle

    base = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    sunrise = base + timedelta(minutes=sunrise_min)
    sunset = base + timedelta(minutes=sunset_min)

    return sunrise, sunset


def get_sun_times(
    lat: float = 52.360179, lon: float = 6.472626, dt: date | None = None
) -> tuple[datetime, datetime]:
    """Zonsopgang en -ondergang voor Nijverdal (of andere locatie).

    Returns:
        Tuple van (zonsopgang, zonsondergang) als lokale datetime.
    """
    if dt is None:
        dt = date.today()

    sunrise_utc, sunset_utc = _sun_times(lat, lon, dt)

    # Converteer naar lokale tijd (CET/CEST)
    # Python 3.9+ zoneinfo
    try:
        from zoneinfo import ZoneInfo

        local_tz = ZoneInfo("Europe/Amsterdam")
        sunrise = sunrise_utc.astimezone(local_tz)
        sunset = sunset_utc.astimezone(local_tz)
    except ImportError:
        # Fallback: UTC+1 (CET) of UTC+2 (CEST)
        # Simpele check: CEST van laatste zondag maart tot laatste zondag oktober
        month = dt.month
        offset = 2 if 4 <= month <= 9 else 1
        local_tz = timezone(timedelta(hours=offset))
        sunrise = sunrise_utc.astimezone(local_tz)
        sunset = sunset_utc.astimezone(local_tz)

    return sunrise, sunset


def is_night(
    lat: float = 52.360179, lon: float = 6.472626, margin_minutes: int = 30
) -> bool:
    """Is het nu nacht (na zonsondergang, voor zonsopgang)?

    Args:
        lat: Breedtegraad
        lon: Lengtegraad
        margin_minutes: Extra marge na zonsondergang / voor zonsopgang

    Returns:
        True als het donker genoeg is voor vleermuizen.
    """
    now = datetime.now().astimezone()
    today = date.today()

    sunrise_today, sunset_today = get_sun_times(lat, lon, today)

    margin = timedelta(minutes=margin_minutes)

    # Na zonsondergang (minus marge = eerder starten)
    if now >= (sunset_today - margin):
        return True

    # Voor zonsopgang (plus marge = langer doorgaan)
    if now <= (sunrise_today + margin):
        return True

    return False

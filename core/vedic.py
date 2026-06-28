"""Vedic (sidereal) astrology — deterministic computation via Swiss Ephemeris.

A real chart needs date + exact time + place, so this computes the ascendant,
Moon sign + nakshatra + pada, Sun sign, and the current Vimshottari
Mahādashā/Antardashā. Birth-local time is converted to UTC using the place's
timezone. Falls back to a date-only approximation only when precise data or the
ephemeris is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    import swisseph as swe  # type: ignore
    _HAS_SWE = True
except Exception:  # noqa: BLE001
    _HAS_SWE = False

RASHIS = [
    ("Mesha (Aries)", "bold, impatient, a natural starter ruled by Mars"),
    ("Vrishabha (Taurus)", "steady, sensual, security-loving, ruled by Venus"),
    ("Mithuna (Gemini)", "curious, quick-witted, communicative, ruled by Mercury"),
    ("Karka (Cancer)", "nurturing, moody, deeply intuitive, ruled by the Moon"),
    ("Simha (Leo)", "proud, generous, born to lead, ruled by the Sun"),
    ("Kanya (Virgo)", "precise, analytical, service-minded, ruled by Mercury"),
    ("Tula (Libra)", "harmonious, fair, relationship-driven, ruled by Venus"),
    ("Vrishchika (Scorpio)", "intense, secretive, transformative, ruled by Mars/Ketu"),
    ("Dhanu (Sagittarius)", "philosophical, free, truth-seeking, ruled by Jupiter"),
    ("Makara (Capricorn)", "disciplined, ambitious, patient, ruled by Saturn"),
    ("Kumbha (Aquarius)", "inventive, humanitarian, unconventional, ruled by Saturn"),
    ("Meena (Pisces)", "compassionate, dreamy, spiritual, ruled by Jupiter"),
]

NAKSHATRAS = [
    ("Ashwini", "Ketu"), ("Bharani", "Venus"), ("Krittika", "Sun"), ("Rohini", "Moon"),
    ("Mrigashira", "Mars"), ("Ardra", "Rahu"), ("Punarvasu", "Jupiter"), ("Pushya", "Saturn"),
    ("Ashlesha", "Mercury"), ("Magha", "Ketu"), ("Purva Phalguni", "Venus"),
    ("Uttara Phalguni", "Sun"), ("Hasta", "Moon"), ("Chitra", "Mars"), ("Swati", "Rahu"),
    ("Vishakha", "Jupiter"), ("Anuradha", "Saturn"), ("Jyeshtha", "Mercury"), ("Mula", "Ketu"),
    ("Purva Ashadha", "Venus"), ("Uttara Ashadha", "Sun"), ("Shravana", "Moon"),
    ("Dhanishta", "Mars"), ("Shatabhisha", "Rahu"), ("Purva Bhadrapada", "Jupiter"),
    ("Uttara Bhadrapada", "Saturn"), ("Revati", "Mercury"),
]

# Vimshottari dasha system.
DASHA_SEQ = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
DASHA_YEARS = {"Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
               "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17}
NAK_DEG = 360 / 27
YEAR_DAYS = 365.25


@dataclass
class VedicChart:
    moon_sign: str
    moon_sign_traits: str
    sun_sign: str | None
    nakshatra: str
    nakshatra_planet: str
    pada: int | None
    ascendant: str | None
    ascendant_traits: str | None
    mahadasha: str | None
    antardasha: str | None
    maha_end: date | None
    precise: bool


def compute_dashas(moon_lon: float, birth: date, on: date) -> tuple[str, str, date]:
    """Current Mahādashā lord, Antardashā lord, and Mahādashā end date."""
    nak_index = int(moon_lon // NAK_DEG)
    start_idx = nak_index % 9
    frac = (moon_lon % NAK_DEG) / NAK_DEG
    first = DASHA_SEQ[start_idx]
    balance = (1 - frac) * DASHA_YEARS[first]

    periods: list[tuple[str, date, date]] = []
    start = birth
    end = birth + timedelta(days=balance * YEAR_DAYS)
    periods.append((first, start, end))
    idx = start_idx
    while end <= on and len(periods) < 25:
        idx = (idx + 1) % 9
        lord = DASHA_SEQ[idx]
        start = end
        end = start + timedelta(days=DASHA_YEARS[lord] * YEAR_DAYS)
        periods.append((lord, start, end))

    maha = next((p for p in periods if p[1] <= on < p[2]), periods[-1])
    maha_lord, ms, me = maha

    order = DASHA_SEQ[DASHA_SEQ.index(maha_lord):] + DASHA_SEQ[:DASHA_SEQ.index(maha_lord)]
    total = (me - ms).days
    a_start = ms
    antar = maha_lord
    for lord in order:
        a_end = a_start + timedelta(days=total * DASHA_YEARS[lord] / 120)
        if a_start <= on < a_end:
            antar = lord
            break
        a_start = a_end
    return maha_lord, antar, me


def compute_precise(birth: date, hour: int, minute: int, lat: float, lon: float,
                    tz_name: str | None) -> VedicChart:
    """Full chart from date + local time + location. Requires Swiss Ephemeris."""
    if not _HAS_SWE:
        return compute_approx(birth)

    if tz_name:
        local = datetime(birth.year, birth.month, birth.day, hour, minute, tzinfo=ZoneInfo(tz_name))
        utc = local.astimezone(timezone.utc)
    else:  # crude fallback: estimate offset from longitude
        offset = round(lon / 15)
        utc = datetime(birth.year, birth.month, birth.day, hour, minute,
                       tzinfo=timezone.utc) - timedelta(hours=offset)

    jd = swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60 + utc.second / 3600)
    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    flags = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

    moon_lon = swe.calc_ut(jd, swe.MOON, flags)[0][0] % 360
    sun_lon = swe.calc_ut(jd, swe.SUN, flags)[0][0] % 360
    moon_name, moon_traits = RASHIS[int(moon_lon // 30)]
    sun_name = RASHIS[int(sun_lon // 30)][0]
    nak_idx = int(moon_lon // NAK_DEG)
    nak_name, nak_planet = NAKSHATRAS[nak_idx]
    pada = int((moon_lon % NAK_DEG) // (NAK_DEG / 4)) + 1

    asc_name = asc_traits = None
    try:
        ascmc = swe.houses_ex(jd, lat, lon, b"A", flags)[1]
        asc_name, asc_traits = RASHIS[int((ascmc[0] % 360) // 30)]
    except Exception:  # noqa: BLE001
        pass

    maha, antar, maha_end = compute_dashas(moon_lon, birth, date.today())
    return VedicChart(
        moon_sign=moon_name, moon_sign_traits=moon_traits, sun_sign=sun_name,
        nakshatra=nak_name, nakshatra_planet=nak_planet, pada=pada,
        ascendant=asc_name, ascendant_traits=asc_traits,
        mahadasha=maha, antardasha=antar, maha_end=maha_end, precise=True,
    )


def _approx_sidereal_sun_sign(birth: date) -> int:
    boundaries = [(1, 14), (2, 13), (3, 14), (4, 14), (5, 15), (6, 15),
                  (7, 16), (8, 17), (9, 17), (10, 17), (11, 16), (12, 16)]
    idx = 0
    for i, (m, d) in enumerate(boundaries):
        if (birth.month, birth.day) >= (m, d):
            idx = i
    return (9 + idx) % 12


def compute_approx(birth: date) -> VedicChart:
    name, traits = RASHIS[_approx_sidereal_sun_sign(birth)]
    nak_name, nak_planet = NAKSHATRAS[(birth.timetuple().tm_yday - 1) % 27]
    return VedicChart(
        moon_sign=name, moon_sign_traits=traits, sun_sign=None,
        nakshatra=nak_name, nakshatra_planet=nak_planet, pada=None,
        ascendant=None, ascendant_traits=None,
        mahadasha=None, antardasha=None, maha_end=None, precise=False,
    )


def parse_time(value: str) -> tuple[int, int]:
    value = value.strip().lower().replace(" ", "")
    ampm = None
    if value.endswith("am"):
        ampm, value = "am", value[:-2]
    elif value.endswith("pm"):
        ampm, value = "pm", value[:-2]
    parts = value.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return hour % 24, minute % 60

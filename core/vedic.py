"""Vedic (sidereal) astrology — deterministic computation via Swiss Ephemeris.

Uses the Lahiri ayanamsa when pyswisseph is installed and a birth time + location
are supplied; otherwise falls back to a date-only sidereal approximation. The LLM
narrates these values; it never computes them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

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
    ("Ashwini", "Ketu", "swift healers and pioneers"),
    ("Bharani", "Venus", "intense bearers of creative force"),
    ("Krittika", "Sun", "sharp, purifying, no-nonsense"),
    ("Rohini", "Moon", "magnetic, fertile, artistic"),
    ("Mrigashira", "Mars", "searching, curious wanderers"),
    ("Ardra", "Rahu", "stormy, transformative thinkers"),
    ("Punarvasu", "Jupiter", "renewing, optimistic returners"),
    ("Pushya", "Saturn", "nourishing, protective, wise"),
    ("Ashlesha", "Mercury", "hypnotic, insightful, coiled energy"),
    ("Magha", "Ketu", "regal, ancestral, authoritative"),
    ("Purva Phalguni", "Venus", "playful, romantic, generous"),
    ("Uttara Phalguni", "Sun", "reliable partners and patrons"),
    ("Hasta", "Moon", "skillful, clever, hands-on"),
    ("Chitra", "Mars", "brilliant builders of beauty"),
    ("Swati", "Rahu", "independent, flexible, diplomatic"),
    ("Vishakha", "Jupiter", "goal-driven, determined achievers"),
    ("Anuradha", "Saturn", "devoted, friendly, disciplined"),
    ("Jyeshtha", "Mercury", "protective, senior, responsible"),
    ("Mula", "Ketu", "root-seekers, radical truth-diggers"),
    ("Purva Ashadha", "Venus", "invincible, persuasive, proud"),
    ("Uttara Ashadha", "Sun", "ethical, enduring victors"),
    ("Shravana", "Moon", "listeners, learners, connectors"),
    ("Dhanishta", "Mars", "rhythmic, wealthy, musical"),
    ("Shatabhisha", "Rahu", "secretive healers and mystics"),
    ("Purva Bhadrapada", "Jupiter", "fiery idealists with a dual nature"),
    ("Uttara Bhadrapada", "Saturn", "deep, calm, wise counselors"),
    ("Revati", "Mercury", "gentle, nourishing, protective guides"),
]


@dataclass
class VedicChart:
    moon_sign: str
    moon_sign_traits: str
    nakshatra: str
    nakshatra_planet: str
    nakshatra_keyword: str
    ascendant: str | None
    ascendant_traits: str | None
    precise: bool


def _approx_sidereal_sun_sign(birth: date) -> int:
    boundaries = [
        (1, 14), (2, 13), (3, 14), (4, 14), (5, 15), (6, 15),
        (7, 16), (8, 17), (9, 17), (10, 17), (11, 16), (12, 16),
    ]
    start_index = 9
    idx = 0
    for i, (m, d) in enumerate(boundaries):
        if (birth.month, birth.day) >= (m, d):
            idx = i
    return (start_index + idx) % 12


def compute_chart(birth: date, birth_time: str | None = None,
                  lat: float | None = None, lon: float | None = None) -> VedicChart:
    if _HAS_SWE and birth_time and lat is not None and lon is not None:
        return _compute_precise(birth, birth_time, lat, lon)
    return _compute_approx(birth)


def _compute_approx(birth: date) -> VedicChart:
    name, traits = RASHIS[_approx_sidereal_sun_sign(birth)]
    nak_name, nak_planet, nak_kw = NAKSHATRAS[(birth.timetuple().tm_yday - 1) % 27]
    return VedicChart(name, traits, nak_name, nak_planet, nak_kw, None, None, False)


def _compute_precise(birth: date, birth_time: str, lat: float, lon: float) -> VedicChart:
    hour, minute = _parse_time(birth_time)
    dt = datetime(birth.year, birth.month, birth.day, hour, minute, tzinfo=timezone.utc)
    jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0)
    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    flags = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

    moon_lon = swe.calc_ut(jd, swe.MOON, flags)[0][0] % 360
    moon_name, moon_traits = RASHIS[int(moon_lon // 30)]
    nak_name, nak_planet, nak_kw = NAKSHATRAS[int(moon_lon // (360 / 27))]

    asc_name = asc_traits = None
    try:
        ascmc = swe.houses_ex(jd, lat, lon, b"A", flags)[1]
        asc_name, asc_traits = RASHIS[int((ascmc[0] % 360) // 30)]
    except Exception:  # noqa: BLE001
        pass

    return VedicChart(moon_name, moon_traits, nak_name, nak_planet, nak_kw,
                      asc_name, asc_traits, True)


def _parse_time(value: str) -> tuple[int, int]:
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

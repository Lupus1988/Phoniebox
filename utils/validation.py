HOTSPOT_SECURITY_CHOICES = {"open", "wpa-psk"}


def to_int(value, fallback, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def to_float(value, fallback, minimum=None, maximum=None):
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        number = float(fallback)
    if minimum is not None:
        number = max(float(minimum), number)
    if maximum is not None:
        number = min(float(maximum), number)
    return number


def normalize_hotspot_security(value):
    security = (value or "open").strip().lower()
    if security == "wpa2":
        return "wpa-psk"
    if security not in HOTSPOT_SECURITY_CHOICES:
        return "open"
    return security


def format_mmss(total_seconds):
    minutes = max(total_seconds, 0) // 60
    seconds = max(total_seconds, 0) % 60
    return f"{minutes:02d}:{seconds:02d}"


def progress_percent(position, duration):
    if duration <= 0:
        return 0
    return round((position / duration) * 100, 1)

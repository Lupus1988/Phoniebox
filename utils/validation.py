import ipaddress

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


def normalize_hotspot_address(value, fallback="10.42.0.1"):
    candidate = str(value or "").strip()
    if not candidate:
        candidate = str(fallback or "").strip()
    if not candidate:
        return "10.42.0.1" if fallback is None else fallback

    try:
        if "/" in candidate:
            address = ipaddress.ip_interface(candidate).ip
        else:
            address = ipaddress.ip_address(candidate)
    except ValueError:
        return normalize_hotspot_address(fallback, "10.42.0.1") if fallback is not None else None

    if address.version != 4 or not address.is_private:
        return normalize_hotspot_address(fallback, "10.42.0.1") if fallback is not None else None

    octets = str(address).split(".")
    if len(octets) != 4 or octets[-1] in {"0", "255"}:
        return normalize_hotspot_address(fallback, "10.42.0.1") if fallback is not None else None

    return str(address)


def format_mmss(total_seconds):
    minutes = max(total_seconds, 0) // 60
    seconds = max(total_seconds, 0) % 60
    return f"{minutes:02d}:{seconds:02d}"


def progress_percent(position, duration):
    if duration <= 0:
        return 0
    return round((position / duration) * 100, 1)

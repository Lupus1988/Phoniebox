def reserved_reader_pins(reader_type):
    reader_type = (reader_type or "").strip().upper()
    if reader_type in {"RC522", "PN532_SPI"}:
        return {"GPIO8", "GPIO9", "GPIO10", "GPIO11", "GPIO25"}
    return set()


def reserved_audio_pins(output_mode):
    return set()


def reserved_system_pins(setup_data):
    setup_data = setup_data or {}
    reader = setup_data.get("reader", {})
    reader_type = reader.get("target_type") or reader.get("type", "")
    return reserved_reader_pins(reader_type)


def potential_reader_pins():
    return {
        "GPIO8",
        "GPIO9",
        "GPIO10",
        "GPIO11",
        "GPIO25",
    }


def potential_audio_pins():
    return set()


def potential_system_pins():
    return potential_reader_pins() | potential_audio_pins()


def filter_reserved_gpio_names(gpio_names, setup_data):
    reserved = reserved_system_pins(setup_data)
    return [gpio_name for gpio_name in gpio_names if gpio_name and gpio_name not in reserved]

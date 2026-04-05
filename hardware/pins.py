def reserved_reader_pins(reader_type):
    reader_type = (reader_type or "").strip().upper()
    if reader_type == "RC522":
        return {"GPIO8", "GPIO9", "GPIO10", "GPIO11", "GPIO18", "GPIO22"}
    if reader_type == "PN532_I2C":
        return {"GPIO2", "GPIO3"}
    if reader_type == "PN532_SPI":
        return {"GPIO8", "GPIO9", "GPIO10", "GPIO11"}
    if reader_type == "PN532_UART":
        return {"GPIO14", "GPIO15"}
    return set()


def reserved_audio_pins(output_mode):
    if (output_mode or "").strip() == "i2s_dac":
        return {"GPIO18", "GPIO19", "GPIO20", "GPIO21"}
    return set()


def reserved_system_pins(setup_data):
    setup_data = setup_data or {}
    reader_type = setup_data.get("reader", {}).get("type", "")
    output_mode = setup_data.get("audio", {}).get("output_mode", "")
    return reserved_reader_pins(reader_type) | reserved_audio_pins(output_mode)


def potential_reader_pins():
    return {
        "GPIO2",
        "GPIO3",
        "GPIO8",
        "GPIO9",
        "GPIO10",
        "GPIO11",
        "GPIO14",
        "GPIO15",
        "GPIO18",
        "GPIO22",
        "GPIO25",
    }


def potential_audio_pins():
    return {"GPIO18", "GPIO19", "GPIO20", "GPIO21"}


def potential_system_pins():
    return potential_reader_pins() | potential_audio_pins()


def filter_reserved_gpio_names(gpio_names, setup_data):
    reserved = reserved_system_pins(setup_data)
    return [gpio_name for gpio_name in gpio_names if gpio_name and gpio_name not in reserved]

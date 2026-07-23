from src.ingest.classify import classify_text, extract_numeric_value


def test_dimension_patterns():
    assert classify_text("R0.50") == "dimension"
    assert classify_text("12'-6\"") == "dimension"
    assert classify_text("Ø2.25") == "dimension"
    assert classify_text("±0.010") == "dimension"
    assert classify_text("45°") == "dimension"


def test_note_patterns():
    assert classify_text("NOTE 1: ALL DIMENSIONS IN INCHES UNLESS NOTED") == "note"
    assert classify_text("This is a fairly long sentence about something") == "note"


def test_plain_text():
    assert classify_text("VALVE V-12") == "text"
    assert classify_text("") == "text"


def test_extract_numeric_value():
    assert extract_numeric_value("R0.50") == 0.5
    assert extract_numeric_value("TORQUE SPEC: 45 FT-LB") == 45.0
    assert extract_numeric_value("no numbers here") is None

"""Scratch test for backend/engine.py (run: python -m pytest tests/test_sensor.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine import Sensor


def test_sensor_reads_and_goes_online():
    sensor = Sensor("temp-1", unit="C", base_value=20.0, step=0.5)
    assert sensor.is_online() is False

    first = sensor.read()
    assert first == 20.0
    assert sensor.is_online() is True

    assert sensor.read() == 20.5

"""Scratch vertical slice: a minimal sensor model with deterministic readings.

Standalone on purpose (no imports from backend.app) so the Card UI demo and
the deploy/Dockerfile entrypoint can run this engine in isolation.
"""

from __future__ import annotations


class Sensor:
    """A calibrated sensor emitting a deterministic, monotonic reading."""

    def __init__(
        self,
        sensor_id: str,
        unit: str = "C",
        base_value: float = 20.0,
        step: float = 0.5,
    ) -> None:
        self.sensor_id = sensor_id
        self.unit = unit
        self._base = base_value
        self._step = step
        self._samples = 0

    def read(self) -> float:
        """Emit the next reading: the first call returns the base value."""
        reading = round(self._base + self._samples * self._step, 2)
        self._samples += 1
        return reading

    def is_online(self) -> bool:
        """A sensor is online once it has produced at least one sample."""
        return self._samples > 0


def main() -> None:
    """Demo entrypoint referenced by deploy/Dockerfile: emit a few readings."""
    sensor = Sensor("demo-temp-1")
    for _ in range(3):
        print(f"{sensor.sensor_id}: {sensor.read()} {sensor.unit}")


if __name__ == "__main__":
    main()

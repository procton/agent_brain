// Scratch component test (same toolchain as the observatory frontend: vitest
// + RTL). Not runnable standalone yet — wire src/ui into the frontend vitest
// root or move it under frontend/src to collect it.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Card from "./Card";

describe("Card", () => {
  it("shows the sensor id and its reading with unit", () => {
    render(
      <Card sensor={{ sensor_id: "temp-1", reading: 20.5, unit: "C", online: true }} />
    );
    expect(screen.getByTestId("sensor-card")).toBeInTheDocument();
    expect(screen.getByText("temp-1")).toBeInTheDocument();
    expect(screen.getByText("20.5 C")).toBeInTheDocument();
  });
});

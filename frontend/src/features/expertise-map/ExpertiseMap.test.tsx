// Expertise-map feature behavior: honest states, evidence, accessibility,
// and the polling contract of useExpertise (last snapshot survives failures).

import { cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import type { ExpertiseRegion, ExpertiseSnapshot } from "../../api/types";
import ExpertiseMap from "./ExpertiseMap";
import EvidencePanel from "./EvidencePanel";
import SkillBadges from "./SkillBadges";
import { blobOpacity, STATE_WORDS } from "./descriptions";
import { useExpertise } from "./useExpertise";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const REGION_KEYS = [
  "code_exploration",
  "frontend",
  "backend",
  "testing",
  "database",
  "infrastructure",
  "debugging",
];

function makeRegion(key: string, overrides: Partial<ExpertiseRegion> = {}): ExpertiseRegion {
  return {
    key,
    label: key.replace(/_/g, " "),
    state: "inactive",
    intensity: 0,
    evidence: [],
    evidence_count: 0,
    ...overrides,
  };
}

function makeRegions(): ExpertiseRegion[] {
  return [
    makeRegion("infrastructure", {
      state: "active",
      intensity: 1.5,
      evidence: [evidenceRow()],
      evidence_count: 1,
    }),
    makeRegion("frontend", { state: "fading", intensity: 0.4 }),
    ...REGION_KEYS.filter((k) => k !== "infrastructure" && k !== "frontend").map((key) =>
      makeRegion(key)
    ),
  ];
}

function evidenceRow() {
  return {
    event_id: "evt-10",
    cursor: 10,
    kind: "tool.completed",
    ts: "2026-10-29T10:00:00.000Z",
    tool: "Shell",
    target: "infra/Dockerfile",
    command: null,
    basis: "inferred",
    rule_id: "target-infra-name",
    confidence: "high",
  };
}

// ---------------------------------------------------------------------------
// ExpertiseMap
// ---------------------------------------------------------------------------

describe("ExpertiseMap", () => {
  it("renders every region with its state word as text (not color-only)", () => {
    render(<ExpertiseMap regions={makeRegions()} selectedKey={null} onSelect={() => {}} />);

    for (const key of REGION_KEYS) {
      expect(document.querySelector(`[data-region="${key}"]`)).not.toBeNull();
    }
    expect(
      screen.getByRole("button", { name: `infrastructure: active (1 evidence item)` })
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("fading")).toBeInTheDocument();
    expect(screen.getAllByText(STATE_WORDS.inactive).length).toBe(5);
  });

  it("click and keyboard Enter both fire onSelect; pressing again deselects", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ExpertiseMap regions={makeRegions()} selectedKey={"infrastructure"} onSelect={onSelect} />);

    const region = screen.getByRole("button", { name: /infrastructure/ });
    expect(region).toHaveAttribute("aria-pressed", "true");
    await user.click(region);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(null); // already selected → toggle off

    await user.type(screen.getByRole("button", { name: /frontend/ }), "{Enter}");
    expect(onSelect).toHaveBeenLastCalledWith("frontend");
  });

  it("fading regions visibly dim their blob while text stays readable", () => {
    render(<ExpertiseMap regions={makeRegions()} selectedKey={null} onSelect={() => {}} />);
    const activeBlob = document.querySelector<SVGEllipseElement>(
      '[data-region="infrastructure"] .region-blob'
    );
    const inactiveBlob = document.querySelector<SVGEllipseElement>(
      '[data-region="backend"] .region-blob'
    );
    const active = Number(activeBlob?.style.opacity ?? 0);
    const inactive = Number(inactiveBlob?.style.opacity ?? 0);
    expect(active).toBeGreaterThan(inactive);
    expect(inactive).toBeGreaterThanOrEqual(0.05);
  });
});

// ---------------------------------------------------------------------------
// EvidencePanel
// ---------------------------------------------------------------------------

describe("EvidencePanel", () => {
  it("asks to select a region when none is selected", () => {
    render(<EvidencePanel region={null} />);
    const panel = screen.getByTestId("evidence-panel");
    expect(panel).toHaveTextContent("Select a region in the map");
    expect(panel).toHaveTextContent("Intensity is recent observed activity, not model effort");
  });

  it("explains rule, basis, and cursor of each evidence row; disclosure of inference", () => {
    render(
      <EvidencePanel
        region={makeRegion("infrastructure", {
          state: "active",
          intensity: 1.5,
          evidence: [evidenceRow()],
        })}
      />
    );
    const text = screen.getByTestId("evidence-panel").textContent ?? "";
    expect(text).toContain("target-infra-name");
    expect(text).toContain("inferred");
    expect(text).toContain("cursor 10");
    expect(text).toContain("rule-based inference");
  });

  it("shows an honest empty row when evidence left the activity window", () => {
    render(<EvidencePanel region={makeRegion("backend")} />);
    expect(screen.getByTestId("evidence-panel")).toHaveTextContent(
      "No evidence rows inside the current activity window"
    );
  });
});

// ---------------------------------------------------------------------------
// SkillBadges — explicit, verified activations only
// ---------------------------------------------------------------------------

describe("SkillBadges", () => {
  it("renders nothing fabricated when no verified activation exists", () => {
    render(<SkillBadges skills={[]} />);
    const row = screen.getByTestId("skill-row");
    expect(row).toHaveTextContent("No explicit skill activations observed");
    expect(row).toHaveTextContent("rule-based inference only");
  });

  it("marks verified recent skills and dims stale (non-deactivated signal) ones", () => {
    render(
      <SkillBadges
        skills={[
          {
            name: "typed-skill",
            first_activated_at: null,
            last_activated_at: null,
            activation_count: 2,
            evidence_event_ids: ["e1"],
            recent: true,
          },
          {
            name: "old-skill",
            first_activated_at: null,
            last_activated_at: null,
            activation_count: 1,
            evidence_event_ids: ["e2"],
            recent: false,
          },
        ]}
      />
    );
    const recent = screen.getByText("typed-skill").closest(".skill-chip");
    expect(recent).not.toHaveClass("skill-chip-stale");
    expect(recent?.textContent).toContain("verified · recent");
    expect(recent?.textContent).toContain("×2");
    const stale = screen.getByText("old-skill").closest(".skill-chip");
    expect(stale).toHaveClass("skill-chip-stale");
    expect(stale?.textContent).toContain("verified · stale");
  });
});

// ---------------------------------------------------------------------------
// descriptions
// ---------------------------------------------------------------------------

describe("blobOpacity", () => {
  it("stays faint at zero and saturates with intensity, never over 0.9", () => {
    expect(blobOpacity(0)).toBe(0.05);
    expect(blobOpacity(1)).toBeGreaterThan(blobOpacity(0.2));
    expect(blobOpacity(10)).toBeLessThanOrEqual(0.9);
  });
});

// ---------------------------------------------------------------------------
// useExpertise — polling + failure honesty
// ---------------------------------------------------------------------------

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useExpertise", () => {
  it("loads the snapshot, keeps prior map on failed refetch, shows errors honestly", async () => {
    const snapshot: ExpertiseSnapshot = {
      schema_version: 1,
      session_id: "sess-1",
      source: "synthetic",
      generated_at: "2026-10-29T10:00:05.000Z",
      regions: REGION_KEYS.map((key) => makeRegion(key)),
      skills: [],
      config: {},
      notes: "Intensity is recent observed activity, not effort.",
    };
    // Queue: initial load succeeds; the event-arrival refetch fails → the
    // previous snapshot must survive while the error is reported.
    const queue: Array<Response | ApiError> = [
      jsonResponse(snapshot),
      new ApiError(500, "request failed: 500"),
    ];
    const fetchMock = vi.fn(async (): Promise<Response> => {
      const next = queue.shift();
      if (next === undefined) throw new ApiError(500, "request failed: 500");
      if (next instanceof ApiError) throw next;
      return next;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(
      ({ eventsKey }: { eventsKey: number }) => useExpertise("sess-1", eventsKey, () => {}),
      { initialProps: { eventsKey: 0 } }
    );
    await waitFor(() => {
      expect(result.current.snapshot?.regions.length).toBe(7);
    });
    expect(result.current.error).toBeNull();

    // Feed changed → immediate refetch; it fails, but prior map survives.
    rerender({ eventsKey: 3 });
    await waitFor(() => {
      expect(result.current.error).toContain("500");
    });
    expect(result.current.snapshot?.regions.length).toBe(7);
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});

// ExpertiseMap: brain-inspired SVG abstractions map of observed activity.
//
// Honesty requirements baked in (AGENTS.md §11):
// - intensity ⇒ blob transparency only; the state word is shown as text in
//   every region (status is never conveyed by color alone);
// - "inactive" regions stay faintly visible (never fabricated activity — the
//   map layout itself is the permanent scaffold);
// - every region is keyboard-focusable and selectable;
// - the explicit skill chips live ABOVE the map so activation/staleness is
//   visible at a glance (see EvidencePanel for per-region evidence).

import { Fragment } from "react";
import type { ExpertiseRegion, RegionState } from "../../api/types";
import {
  STATE_HINTS,
  STATE_WORDS,
  blobOpacity,
  regionAriaLabel,
} from "./descriptions";

// Hand-tuned organic layout (viewBox 640x360, roughly a brain side profile).
interface RegionGeometry {
  key: string;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

const GEOMETRY: RegionGeometry[] = [
  { key: "code_exploration", cx: 96, cy: 96, rx: 70, ry: 47 },
  { key: "frontend", cx: 246, cy: 68, rx: 66, ry: 42 },
  { key: "backend", cx: 408, cy: 84, rx: 72, ry: 47 },
  { key: "testing", cx: 536, cy: 168, rx: 62, ry: 45 },
  { key: "debugging", cx: 172, cy: 200, rx: 62, ry: 41 },
  { key: "database", cx: 262, cy: 268, rx: 66, ry: 42 },
  { key: "infrastructure", cx: 432, cy: 252, rx: 74, ry: 45 },
];

interface ExpertiseMapProps {
  regions: ExpertiseRegion[];
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
}

export function regionStateWord(state: RegionState): string {
  return STATE_WORDS[state] ?? state;
}

export default function ExpertiseMap({
  regions,
  selectedKey,
  onSelect,
}: ExpertiseMapProps) {
  const byKey = new Map(regions.map((region) => [region.key, region]));

  function toggle(key: string) {
    onSelect(selectedKey === key ? null : key);
  }

  return (
    <svg
      className="expertise-map"
      viewBox="0 0 640 360"
      role="group"
      aria-label="Skills and expertise map — recent observed agent activity by region"
    >
      <desc>
        Blobs light up with recently observed tool activity per region and fade
        out as evidence ages. State words are rendered as text inside each
        region; verified skill activations are listed above the map.
      </desc>
      {GEOMETRY.map((ga) => {
        const region = byKey.get(ga.key);
        if (!region) return null;
        const selected = selectedKey === region.key;
        const opacity = blobOpacity(region.intensity);
        return (
          <Fragment key={region.key}>
            <g
              className={`region region-${region.state}${selected ? " region-selected" : ""}`}
              data-region={region.key}
              data-state={region.state}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={regionAriaLabel(region)}
              onClick={() => toggle(region.key)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggle(region.key);
                }
              }}
            >
              <ellipse
                className="region-blob"
                cx={ga.cx}
                cy={ga.cy}
                rx={ga.rx}
                ry={ga.ry}
                style={{ opacity }}
              />
              <text
                className="region-label"
                x={ga.cx}
                y={ga.cy - 2}
                textAnchor="middle"
              >
                {region.label}
              </text>
              <text
                className="region-state"
                x={ga.cx}
                y={ga.cy + 16}
                textAnchor="middle"
              >
                {regionStateWord(region.state)}
              </text>
              <title>{STATE_HINTS[region.state] ?? region.state}</title>
            </g>
          </Fragment>
        );
      })}
    </svg>
  );
}

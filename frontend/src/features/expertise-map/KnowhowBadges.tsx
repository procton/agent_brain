// KnowhowBadges: the technology axis of the knowhow map.
//
// Chips appear for technologies with recent OBSERVED activity (from sanitized
// file/command metadata) or VERIFIED skill matches; inactive technologies do
// not render. Honest labeling: "observed" ≠ "verified", and neither measures
// expertise — a .py extension never claims Python proficiency.

import type { KnowhowRow } from "../../api/types";

interface KnowhowBadgesProps {
  knowhow: KnowhowRow[];
}

export default function KnowhowBadges({ knowhow }: KnowhowBadgesProps) {
  const visible = knowhow.filter((row) => row.state !== "inactive");
  if (visible.length === 0) {
    return (
      <p className="knowhow-row knowhow-row-empty" data-testid="knowhow-row" aria-label="Technologies in use">
        No specific technology observed in recent actions.
      </p>
    );
  }
  return (
    <ul className="knowhow-row" data-testid="knowhow-row" aria-label="Technologies in use">
      {visible.map((row) => (
        <li
          key={row.name}
          className={`knowhow-chip knowhow-${row.state}`}
          title={
            (row.basis === "verified"
              ? "Verified by a real skill-activation event"
              : "Observed from sanitized file/command metadata") +
            " — recent activity, not a skill-level claim"
          }
        >
          <span className="knowhow-name">{row.name}</span>
          <span className="knowhow-meta">
            {row.basis} · {row.state}
          </span>
        </li>
      ))}
    </ul>
  );
}

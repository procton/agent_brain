// Text descriptions for the expertise map: states must never be communicated
// through color alone (every region carries its state word + aria-label).

import type { ExpertiseEvidence, ExpertiseRegion, SkillActivation } from "../../api/types";

export const STATE_WORDS: Record<string, string> = {
  active: "active",
  fading: "fading",
  idle: "dim",
  inactive: "inactive",
};

export const STATE_HINTS: Record<string, string> = {
  active: "receiving recent evidence",
  fading: "decaying — recent evidence is getting older",
  idle: "very weak recent evidence still in window",
  inactive: "no evidence in the current activity window",
};

/** Faint→bright blob opacity from observed intensity (0 stays faint). */
export function blobOpacity(intensity: number): number {
  if (intensity <= 0) return 0.05;
  return Math.min(0.9, 0.12 + intensity * 0.45);
}

export function regionAriaLabel(region: ExpertiseRegion): string {
  const word = STATE_WORDS[region.state] ?? region.state;
  const count = region.evidence_count;
  return `${region.label}: ${word} (${count} evidence item${count === 1 ? "" : "s"})`;
}

export function evidenceSummary(evidence: ExpertiseEvidence): string {
  const kind = evidence.kind ?? "event";
  const bits: string[] = [];
  if (evidence.tool) bits.push(`tool ${evidence.tool}`);
  if (evidence.target) bits.push(`target ${evidence.target}`);
  if (evidence.command) bits.push(`command category ${evidence.command}`);
  return bits.length > 0 ? `${kind}: ${bits.join(", ")}` : kind;
}

export function skillTopLine(skill: SkillActivation): string {
  const verified = "verified activation";
  const suffix = skill.recent
    ? `${verified} · recent`
    : `${verified} · stale (older than the visible window)`;
  return suffix;
}

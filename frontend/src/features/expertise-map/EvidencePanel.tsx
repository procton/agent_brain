// EvidencePanel: why a region is lit. Every intensity claim must be traceable
// to persisted events; this panel shows the rule_id, confidence, basis, and
// the actual sanitized metadata of each backing event (most recent first).

import type { ExpertiseRegion } from "../../api/types";
import { STATE_HINTS, STATE_WORDS, evidenceSummary } from "./descriptions";

interface EvidencePanelProps {
  region: ExpertiseRegion | null;
}

export default function EvidencePanel({ region }: EvidencePanelProps) {
  if (region === null) {
    return (
      <aside className="evidence-panel" data-testid="evidence-panel" aria-label="Region evidence">
        <h2 className="evidence-title">Evidence</h2>
        <p className="evidence-hint">
          Select a region in the map to see the observed events behind its
          intensity. Intensity is recent observed activity, not model effort.
        </p>
      </aside>
    );
  }

  const word = STATE_WORDS[region.state] ?? region.state;
  const hint = STATE_HINTS[region.state] ?? region.state;
  const inferredOnly = region.evidence.every((item) => item.basis !== "observed");

  return (
    <aside className="evidence-panel" data-testid="evidence-panel" aria-label="Region evidence">
      <h2 className="evidence-title">
        {region.label}{" "}
        <span className={`evidence-state evidence-state-${region.state}`}>
          {word}
        </span>
      </h2>
      <p className="evidence-hint">
        {hint}. Intensity {region.intensity.toFixed(2)} over {region.evidence_count} evidence
        item{region.evidence_count === 1 ? "" : "s"}
        {region.evidence.length < region.evidence_count
          ? ` (showing ${region.evidence.length})`
          : ""}
        {inferredOnly ? " — rule-based inference from observed actions." : "."}
      </p>
      {region.evidence.length === 0 ? (
        <p className="evidence-empty">
          No evidence rows inside the current activity window.
        </p>
      ) : (
        <ul className="evidence-list">
          {region.evidence.map((item, index) => (
            <li key={`${item.event_id}-${index}`} className="evidence-item" data-basis={item.basis}>
              <div className="evidence-line">
                <span className="evidence-kind">{item.kind}</span>
                <span className={`badge badge-basis badge-basis-${item.basis}`}>
                  {item.basis}
                </span>
                <span className="evidence-rule">{item.rule_id}</span>
                <span className="evidence-confidence">{item.confidence}</span>
              </div>
              <div className="evidence-detail">{evidenceSummary(item)}</div>
              <div className="evidence-cursor">
                {item.cursor !== null ? `cursor ${item.cursor}` : ""}
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

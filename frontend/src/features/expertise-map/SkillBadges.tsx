// SkillBadges: explicitly VERIFIED skill activations only.
//
// These chips appear exclusively when the source produced a real, named
// activation event (OpenCode `session.skill.activated`). Nothing is inferred
// here, and nothing appears when there is no such event. `recent: false`
// chips render dimmed with a "stale" marker — the source provides no explicit
// deactivation signal, so honest aging is the "deactivation" representation.

import type { ExpertiseSnapshot } from "../../api/types";
import { skillTopLine } from "./descriptions";

interface SkillBadgesProps {
  skills: ExpertiseSnapshot["skills"];
}

export default function SkillBadges({ skills }: SkillBadgesProps) {
  if (skills.length === 0) {
    return (
      <p className="skill-row skill-row-empty" data-testid="skill-row">
        No explicit skill activations observed — expert regions below are
        rule-based inference only.
      </p>
    );
  }
  return (
    <ul className="skill-row" data-testid="skill-row" aria-label="Verified skill activations">
      {skills.map((skill) => (
        <li
          key={skill.name}
          className={`skill-chip${skill.recent ? "" : " skill-chip-stale"}`}
          title={skillTopLine(skill)}
        >
          <span className="skill-name">{skill.name}</span>
          <span className="skill-meta">
            {skill.recent ? "verified · recent" : "verified · stale"}
            {skill.activation_count > 1 ? ` ×${skill.activation_count}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

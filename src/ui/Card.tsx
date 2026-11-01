// Scratch vertical slice: render one sensor as a card.
// Uses two CSS-module classes only (.card, .value) per the exercise spec.

import styles from "./Card.module.css";

export type SensorView = {
  sensor_id: string;
  reading: number;
  unit: string;
  online: boolean;
};

export default function Card({ sensor }: { sensor: SensorView }) {
  return (
    <article className={styles.card} data-testid="sensor-card">
      <h2>{sensor.sensor_id}</h2>
      <p className={styles.value}>
        {sensor.online ? `${sensor.reading} ${sensor.unit}` : "offline"}
      </p>
    </article>
  );
}

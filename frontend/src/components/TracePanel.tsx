import type { TraceEvent } from "../api";

export default function TracePanel({ events }: { events: TraceEvent[] }) {
  if (!events.length) return null;
  return (
    <details className="panel">
      <summary>실행 기록 ({events.length})</summary>
      <ol className="trace">
        {events.map((e, i) => {
          const { type, t, ...rest } = e;
          return (
            <li key={i}>
              <b>{type}</b> <span className="t">{t}s</span>
              <pre>{JSON.stringify(rest, null, 1)}</pre>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

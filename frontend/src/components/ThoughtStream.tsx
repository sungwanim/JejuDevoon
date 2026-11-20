import { useEffect, useRef } from "react";
import type { Thought } from "../api";

const LABELS: Record<string, string> = {
  s1_parse: "요청 이해",
  s2_select: "데이터 고르기",
  s3_load: "데이터 불러오기",
  s4_analyze: "분석",
  s5_render: "결과 만들기",
};

/** 에이전트가 단계마다 내린 결정과 그 이유를 쉬운 말로 순서대로 보여 준다. 진행 중에는 새 줄이 생길 때마다 맨 아래로 따라간다. */
export default function ThoughtStream({ thoughts, running }: { thoughts: Thought[]; running: boolean }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (running) end.current?.scrollIntoView({ block: "nearest" });
  }, [thoughts.length, running]);
  if (!thoughts.length) return null;
  return (
    <details className="panel thoughts" open={running || undefined}>
      <summary>
        생각 과정 ({thoughts.length}){running ? " · 진행 중…" : ""}
      </summary>
      <ol>
        {thoughts.map((t, i) => (
          <li key={i}>
            <span className="tag">{LABELS[t.stage] ?? t.stage}</span> {t.text}
          </li>
        ))}
        <li ref={end} className="end" />
      </ol>
    </details>
  );
}

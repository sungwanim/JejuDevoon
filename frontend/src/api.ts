export type TraceEvent = { type: string; t: number; [k: string]: unknown };

export type RunStatus = {
  run_id: string;
  running: boolean;
  stage: string | null;
  status: string | null; // answered | partial | clarify | infeasible | failed | null(진행 중)
  reason: string;
  message: string;
  thoughts: Thought[]; // 단계별로 내린 결정과 이유(쉬운 말). 진행 중에도 쌓인다
};

export type Thought = { stage: string; text: string; t: number };

export type RunResult = RunStatus & {
  needed_data: string[];
  html: string | null;
  unanswered: { what: string; why: string }[];
  events: TraceEvent[];
};

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const startRun = (request: string, lat?: number, lon?: number, conversation_id?: string) =>
  fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request, lat, lon, conversation_id }),
  }).then((r) => json<{ run_id: string }>(r));

export const getStatus = (id: string) => fetch(`/api/runs/${id}`).then((r) => json<RunStatus>(r));
export const getResult = (id: string) => fetch(`/api/runs/${id}/result`).then((r) => json<RunResult>(r));

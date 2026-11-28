import type { TaskContractRequest } from "./api";

export interface CgpaCourseInput {
  id?: string;
  name: string;
  credits: number;
  grade: number;
}

export const DEFAULT_CGPA_COURSES: ReadonlyArray<CgpaCourseInput> = [
  { id: "1", name: "Cloud Computing & Distributed Systems", credits: 4, grade: 9.0 },
  { id: "2", name: "Algorithm Analysis & Optimization", credits: 4, grade: 8.5 },
  { id: "3", name: "Database Engineering & Storage", credits: 3, grade: 9.0 },
];

export const DEFAULT_HASH_INPUT = "cloudbalance-heavy-workload-2026";
export const DEFAULT_HASH_ITERATIONS = 150000;

export function buildLightCgpaRequest(
  clientId: string,
  courses: ReadonlyArray<CgpaCourseInput> = DEFAULT_CGPA_COURSES,
  extras?: {
    sent_at?: number;
    client_rate?: number;
    client_task_type?: "light";
  }
): TaskContractRequest {
  return {
    client_id: clientId,
    task_type: "light",
    payload: {
      courses: courses.map((c) => ({
        name: c.name,
        credits: Number(c.credits),
        grade: Number(c.grade),
      })),
    },
    ...extras,
  };
}

export function buildHeavyHashRequest(
  clientId: string,
  hashInput: string = DEFAULT_HASH_INPUT,
  iterations: number = DEFAULT_HASH_ITERATIONS,
  extras?: {
    sent_at?: number;
    client_rate?: number;
    client_task_type?: "heavy";
  }
): TaskContractRequest {
  const cleanIters = Math.trunc(iterations);
  return {
    client_id: clientId,
    task_type: "heavy",
    size: cleanIters,
    payload: {
      data: hashInput,
      iterations: cleanIters,
    },
    ...extras,
  };
}

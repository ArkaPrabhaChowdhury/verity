export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type FindingStatus = "success" | "partial" | "failed";

export type SubQuestion = {
  id: string;
  question: string;
  search_query?: string;
  rationale: string;
  round: number;
};

export type Plan = { round: number; sub_questions: SubQuestion[] };

export type SourceEvidence = {
  title: string;
  url: string;
  domain?: string;
  summary: string;
  excerpt?: string;
  source_type?: string;
  quality_score?: number;
  fetched_at?: string;
};

export type Finding = {
  sub_question_id: string;
  question: string;
  status: FindingStatus;
  sources: SourceEvidence[] | null;
  error?: string;
  duration_ms: number;
  round: number;
};

export type CoverageAssessment = {
  sub_question_id: string;
  assessment: "sufficient" | "thin" | "missing";
  reason: string;
};

export type CriticOutput = {
  coverage_assessment: CoverageAssessment[] | null;
  contradictions: Array<{ claim: string; source_urls: string[]; explanation: string }> | null;
  decision: "PROCEED" | "RE_PLAN";
  notes_for_replan?: string;
  forced_proceed?: boolean;
};

export type RunMetadata = {
  total_latency_ms: number;
  stage_latency_ms: Record<string, number>;
  total_tokens: number;
  llm_estimated_cost_usd: number;
  search_estimated_cost_usd: number;
  estimated_cost_usd: number;
  search_queries: number;
  replan_occurred: boolean;
  outcomes: Partial<Record<FindingStatus, number>> | null;
  llm_calls?: Array<{ stage: string; provider: string; model: string; prompt_tokens: number; completion_tokens: number; total_tokens: number; estimated_cost_usd: number; duration_ms: number }>;
};

export type TrustAssessment = {
  status: "verified" | "qualified" | "inconclusive" | "";
  score: number;
  summary: string;
  reasons: string[] | null;
  successful_findings: number;
  partial_findings: number;
  failed_findings: number;
  independent_domains: number;
  has_contradictions: boolean;
};

export type RunEvent = {
  seq: number;
  run_id: string;
  type: string;
  data: unknown;
  created_at: string;
};

export type Run = {
  id: string;
  question: string;
  status: RunStatus;
  plans: Plan[] | null;
  findings: Finding[] | null;
  critiques: CriticOutput[] | null;
  trust?: TrustAssessment;
  report: string;
  metadata: RunMetadata;
  error?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  options: { replan_enabled: boolean };
};

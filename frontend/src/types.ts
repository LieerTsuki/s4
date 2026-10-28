import type { components } from "./generated/openapi";
export type Role =
  "admin" | "lead" | "annotator" | "arbitrator" | "auditor" | "verifier";
export type Phase = "BLIND" | "REVIEW";
export type Answerability =
  "answerable" | "no_answer" | "expired" | "out_of_scope";
export type PointLabel = "correct" | "partial" | "wrong";
export interface User {
  id: string;
  username: string;
  display_name: string;
  person_id: string;
  roles: Role[];
  active: boolean;
}
export interface Session {
  user: User;
  csrf_token: string;
}
export interface ListResult<T> {
  items: T[];
  total: number;
}
export interface Profile {
  dataset: string;
  quota: number;
  kind: string;
  version: string;
  formal_enabled: boolean;
  blocked_reasons: string[];
  title?: string;
}
export interface ImportRecord {
  id: string;
  batch_id: string;
  mode: string;
  status: string;
  unit_count: number;
  blocked_reasons: string[];
  created_at: string;
}
export interface ContextDocument {
  doc_id: string;
  text: string;
  title?: string;
  valid_from?: unknown;
  valid_until?: unknown;
  version?: unknown;
  page?: unknown;
  start?: unknown;
  end?: unknown;
  acl_context?: unknown;
  license?: unknown;
  source_url?: unknown;
  sha256?: unknown;
}
export interface Gold {
  answer_points?: string[];
  gold_doc_ids?: string[];
  answerable?: Answerability;
  [key: string]: unknown;
}
export interface Point {
  point_key: string;
  text: string;
}
// UI drafts omit null fields; server DTOs are generated from the current OpenAPI.
type Schema = components["schemas"];
export type Locator = Pick<Schema["Locator"], "doc_id"> &
  Partial<{
    [K in Exclude<keyof Schema["Locator"], "doc_id">]: NonNullable<
      Schema["Locator"][K]
    >;
  }>;
export type SuggestedPoint = Omit<Schema["SuggestedPoint"], "evidence"> & {
  evidence: Locator[];
};
export type EvidenceChange = Omit<Schema["EvidenceChange"], "locators"> & {
  locators: Locator[];
};
export type ReviewPayload = Omit<
  Partial<Schema["ReviewV2"]>,
  | "point_labels"
  | "evidence_labels"
  | "answerable"
  | "reason"
  | "specialized_review"
  | "suggested_points"
  | "evidence_changes"
  | "point_evidence"
> & {
  point_labels: Record<string, PointLabel>;
  evidence_labels: Record<string, number>;
  answerable: Answerability | "";
  reason: string;
  point_evidence?: Record<string, Locator[]>;
  suggested_points?: SuggestedPoint[];
  evidence_changes?: EvidenceChange[];
  specialized_review?: Record<
    string,
    { observation: string; reason: string; evidence: Locator[] }
  >;
};
export interface Task {
  paused?: boolean;
  legacy?: boolean;
  review_version?: string;
  profile_hash?: string;
  manual_version?: string;
  id: string;
  batch_id: string;
  unit_id: string;
  dataset: string;
  phase: Phase;
  status: string;
  content_revision: string;
  profile_version: string;
}
export interface TaskDetail extends Task {
  material: {
    question?: string;
    payload?: unknown;
    contexts: ContextDocument[];
    acl_context?: unknown;
    access_context?: unknown;
    chunk?: unknown;
    quality_metrics?: unknown;
    inject_plan?: unknown;
    time_context?: unknown;
    scope_context?: unknown;
    key_facts?: unknown;
    source_case_ids?: unknown;
    resolved_sources?: unknown;
    source_composition?: unknown;
    evidence_union?: unknown;
    evaluation_k?: unknown;
    domain?: unknown;
    domains?: unknown;
    reasoning_chain?: unknown;
    synthetic_pii?: unknown;
    pair_controls?: unknown;
    metadata?: Record<string, unknown>;
  };
  gold?: Gold;
  expected_behavior?: unknown;
  points?: Point[];
  own_blind?: { answer?: string; reason?: string };
  own_submission?: Record<string, unknown> | null;
  draft: { version: number; payload: Record<string, unknown> } | null;
}
export interface Agreement {
  id: string;
  batch_id: string;
  kappa: number | null;
  po: number | null;
  pe: number | null;
  n: number;
  verdict: string;
  blocked_reasons: string[];
  disagreement_unit_ids?: string[];
}
export interface Unit {
  key_facts?: unknown;
  unit_id: string;
  question?: string;
  gold?: Gold;
  contexts: ContextDocument[];
  expected_behavior?: unknown;
}
export interface Submission {
  id?: string;
  unit_id?: string;
  phase?: string;
  actor_id?: string;
  payload?: Record<string, unknown>;
  assignment_id?: string;
  [key: string]: unknown;
}
export interface AnnotationBatch {
  version?: number;
  review_version?: string;
  profile_revision_id?: string;
  manual_version?: string;
  due_at?: string;
  reminder_interval_minutes?: number;
  id: string;
  import_id: string;
  dataset: string;
  state: string;
  round: number;
  annotator_a: string;
  annotator_b: string;
  selected_ids: string[];
  sample_count: number;
  blocked_reasons: string[];
  blind_submitted: number;
  review_submitted: number;
  agreement?: Agreement;
  finalized: boolean;
  units?: Unit[];
  assignments?: {
    id: string;
    unit_id: string;
    user_id: string;
    seat: string;
  }[];
  submissions?: Submission[];
}
export interface Arbitration {
  id: string;
  batch_id: string;
  unit_id: string;
  arbitrator_id: string;
  reason: string;
  final_gold: Gold;
  confirmed: boolean;
  confirmed_by: string | null;
}
export interface Handoff {
  snapshot_hash?: string;
  id: string;
  import_id: string;
  mode: string;
  status: string;
  manifest: {
    files?:
      | Record<string, { sha256: string; line_count?: number; rows?: number }>
      | {
          name?: string;
          filename?: string;
          sha256?: string;
          rows?: number;
          line_count?: number;
        }[];
    [key: string]: unknown;
  } | null;
  blocked_reasons: string[];
  external_status: string;
  created_at: string;
}
export interface Job {
  id: string;
  kind: string;
  state: string;
  attempts: number;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
}
export interface AuditEvent {
  id: string;
  actor_id: string | null;
  action: string;
  object_type?: string;
  object_id?: string;
  created_at: string;
  request_id?: string;
  details?: Record<string, unknown>;
}
export interface Health {
  status?: string;
  database?: boolean;
  migration?: string;
  worker?: unknown;
  [key: string]: unknown;
}

import type { ContextDocument, Locator, Point, PointLabel, SuggestedPoint, EvidenceChange } from "../types";

export type WorkflowKind = "VERIFICATION" | "OBSERVATION";
export type Verdict = "VERIFIED" | "NEEDS_REVISION" | "RETURNED";
export type AbsenceReason = "库内无答案" | "答案已过期" | "答案在权限外";
export type EvidenceIntent = "KEEP_GOLD" | "KEEP_RANKING" | "MOVE_TO_GOLD" | "MOVE_TO_RANKING" | "REMOVE";
export interface EvidenceAssessment { grade: number; reason: string; locators: Locator[]; intent: EvidenceIntent }
export interface V13Gold {
  answer_points?: string[];
  gold_doc_ids?: string[];
  relevance_grades?: Record<string, number>;
  ranking_annotations?: Record<string, number>;
  expected_refusal?: boolean;
  absence_reason?: AbsenceReason | null;
  gold_entities?: Entity[];
  gold_relations?: Relation[];
  [key: string]: unknown;
}
export interface Entity { entity_id: string; name: string; type: string; span: [number, number] }
export interface Relation { head: string; tail: string; type: string }
export interface Extraction { gold_entities: Entity[]; gold_relations: Relation[] }
export interface Vocabulary { entity_types: string[]; relation_types: string[]; version: string; sha256: string }
export interface ReviewV3 {
  review_version: "openkb.s4-review.v3";
  workflow_kind: WorkflowKind;
  verdict: Verdict;
  point_labels: Record<string, PointLabel>;
  point_reasons: Record<string, string>;
  point_evidence: Record<string, Locator[]>;
  point_search_scope: Record<string, string[]>;
  evidence_assessments: Record<string, EvidenceAssessment>;
  expected_refusal?: boolean;
  absence_reason: AbsenceReason | null;
  expected_refusal_reason: string;
  reason: string;
  extraction?: Extraction;
  specialized_review: Record<string, {observation: string; reason: string; evidence: Locator[]}>;
  suggested_points?: SuggestedPoint[];
  evidence_changes?: EvidenceChange[];
}
export interface V13Import {
  id: string; batch_id: string; source_revision: string; mode: string; status: string;
  unit_count: number; blocked_reasons: string[]; datasets?: string[];
}
export interface V13Batch {
  id: string; import_id: string; dataset: string; workflow_kind: WorkflowKind; state: string;
  selected_ids: string[]; sample_count: number; blind_submitted: number; review_submitted: number;
  verification_completed: number; blocked_reasons: string[];
  profile_version?:string;manual_version?:string;
  quality?: {kappa: number | null; action?: string; status?: string; blocked_reasons?: string[]; [key: string]: unknown};
  assignments?: {id:string;unit_index_id:string;user_id:string;seat:string;phase:string;status:string}[];
}
export interface V13Task {
  id: string; batch_id: string; unit_id: string; dataset: string; workflow_kind: WorkflowKind;
  phase: "BLIND" | "REVIEW"; status: string; content_revision: string; profile_version: string; manual_version: string;
  material?: {question?: string; contexts?: ContextDocument[]; text?: string; chunk?: string; [key: string]: unknown};
  gold?: V13Gold; points?: Point[]; own_blind?: Record<string, unknown>; own_submission?: Record<string, unknown> | null;
  draft?: {version: number; payload: Record<string, unknown>} | null;
  paused?: boolean; vocabulary?: Vocabulary | null;
  active?: boolean;
  unit_index_id?: string;
}
export interface V13Report {
  N?: number; n?: number; verified_count?: number; verification_completed?: number; observation_pairs?: number;
  blocked_reasons?: string[]; state?: string; [key: string]: unknown;
  observation_completed?: number; readiness?: string; blockers?: string[];
}

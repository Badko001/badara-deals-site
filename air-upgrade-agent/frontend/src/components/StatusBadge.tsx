import type { MonitoringStatus } from "../types/api";

const LABELS: Record<MonitoringStatus, string> = {
  IDLE: "EN ATTENTE",
  MONITORING: "MONITORING",
  OPPORTUNITY_FOUND: "OPPORTUNITY FOUND",
  ACTION_REQUIRED: "ACTION REQUIRED",
  STOPPED: "ARRÊTÉ",
  ERROR: "ERREUR",
};

export function StatusBadge({ status }: { status: MonitoringStatus }) {
  return <span className={`badge badge-${status.toLowerCase()}`}>{LABELS[status]}</span>;
}

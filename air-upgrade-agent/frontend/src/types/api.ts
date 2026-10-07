// Mirrors backend/app/api/schemas.py. All data is anonymised by the backend.

export type DecisionStatus = "NO_OPPORTUNITY" | "OPPORTUNITY" | "ACTION_REQUIRED";

export type MonitoringStatus =
  | "IDLE"
  | "MONITORING"
  | "OPPORTUNITY_FOUND"
  | "ACTION_REQUIRED"
  | "STOPPED"
  | "ERROR";

export type ExecutionStatus =
  | "DRY_RUN_SIMULATED"
  | "CONFIRMED_BY_AIRLINE"
  | "NOT_CONFIRMED_BY_AIRLINE"
  | "ABORTED";

export interface RejectedOption {
  option_id: string;
  reason: string;
  cash_cost: number | null;
  miles_cost: number | null;
}

export interface UpgradeDecision {
  status: DecisionStatus;
  reason: string;
  passengers_target: number;
  passengers_eligible: number | null;
  business_available: boolean | null;
  business_seats_required: number;
  business_seats_observed: number | null;
  cash_cost: number | null;
  miles_cost: number | null;
  recommendation: string;
  confidence: number;
  requires_human_confirmation: boolean;
  option_id: string | null;
  rejected_options: RejectedOption[];
  data_issues: string[];
  snapshot_id: string | null;
  decided_by: string;
  evaluated_at: string;
}

export interface PassengerView {
  anonymized_id: string;
  current_cabin: string | null;
  eligibility: string | null;
}

export interface FlightView {
  anonymized_booking_id: string | null;
  flight_number: string | null;
  origin: string | null;
  destination: string | null;
  departure_datetime: string | null;
  current_cabin: string | null;
  target_cabin: string;
  passengers: PassengerView[];
  business_available: boolean | null;
  business_seats_visible: number | null;
  business_seats_provenance: string;
  checkin_status: string | null;
  observed_messages: string[];
  confirmed_by_airline: boolean;
  snapshot_time: string;
}

export interface MonitoringState {
  status: MonitoringStatus;
  running: boolean;
  last_check: string | null;
  next_check: string | null;
  interval_seconds: number;
  checks_count: number;
  consecutive_errors: number;
  last_error: string | null;
}

export interface CostLimits {
  cash_limit: number;
  miles_limit: number;
  passengers_target: number;
}

export interface PendingConfirmation {
  confirmation_id: string;
  option_id: string;
  snapshot_id: string;
  state: string;
  max_cash: number;
  max_miles: number;
  passengers: number;
  created_at: string;
  expires_at: string;
  summary: {
    flight: string | null;
    origin: string | null;
    destination: string | null;
    from_cabin: string;
    to_cabin: string;
  };
}

export interface UpgradeExecutionResult {
  status: ExecutionStatus;
  message: string;
  option_id: string | null;
  verification_snapshot_id: string | null;
  timestamp: string;
}

export interface Notification {
  id: string;
  event: string;
  message: string;
  timestamp: string;
}

export interface RuntimeConfig {
  dry_run: boolean;
  debug_mode: boolean;
  provider: string;
  llm_enabled: boolean;
  mock_scenario: string | null;
  session_ready: boolean;
}

export interface Dashboard {
  config: RuntimeConfig;
  limits: CostLimits;
  monitoring: MonitoringState;
  flight: FlightView | null;
  decision: UpgradeDecision | null;
  pending_confirmation: PendingConfirmation | null;
  last_execution: UpgradeExecutionResult | null;
  notifications: Notification[];
}

export interface MockScenarios {
  current: string;
  scenarios: Record<string, string>;
}

// --- Price watch ---------------------------------------------------------------

export type FareCabin = "economy" | "premium_economy" | "business" | "first";

export interface PriceWatch {
  watch_id: string;
  name: string;
  origin: string;
  destinations: string[];
  depart_from: string;
  depart_to: string;
  trip_length_days: number | null;
  passengers: number;
  cabin: FareCabin;
  max_total_price: number | null;
  airlines: string[];
  active: boolean;
}

export type NewPriceWatch = Omit<PriceWatch, "watch_id" | "active">;

export interface FareQuote {
  destination: string;
  depart_date: string;
  return_date: string | null;
  total_price: number;
  currency: string;
  carrier: string | null;
  flight_numbers: string[];
  cabin: FareCabin;
  passengers: number;
  source: string;
  observed_at: string;
}

export interface WatchSummary {
  watch: PriceWatch;
  best_current: FareQuote | null;
  lowest_ever: FareQuote | null;
  last_check: string | null;
  quotes_count: number;
}

export interface PriceAlert {
  watch_id: string;
  watch_name: string;
  kind: "BELOW_THRESHOLD" | "PRICE_DROP" | "NEW_LOW";
  quote: FareQuote;
  previous_price: number | null;
  booking_url: string | null;
  message: string;
  timestamp: string;
}

export interface PriceWatchStatus {
  source: string;
  running: boolean;
  last_run: string | null;
  next_run: string | null;
  interval_seconds: number;
}

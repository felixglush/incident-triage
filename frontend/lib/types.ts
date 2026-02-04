export type Incident = {
  id: number;
  title: string;
  status: string;
  severity: string;
  assigned_team?: string | null;
  assigned_user?: string | null;
  summary?: string | null;
  summary_citations?: unknown[] | null;
  next_steps?: string[] | null;
  affected_services?: string[] | null;
  created_at?: string | null;
  updated_at?: string | null;
  resolved_at?: string | null;
  closed_at?: string | null;
  alert_count?: number;
  last_alert_at?: string | null;
};

export type Alert = {
  id: number;
  external_id: string;
  source: string;
  title: string;
  message?: string | null;
  alert_timestamp?: string | null;
  severity?: string | null;
  predicted_team?: string | null;
  confidence_score?: number | null;
  classification_source?: string | null;
  service_name?: string | null;
  environment?: string | null;
  region?: string | null;
  error_code?: string | null;
  entity_source?: string | null;
  incident_id?: number | null;
  created_at?: string | null;
};

export type IncidentListResponse = {
  items: Incident[];
  total: number;
  limit: number;
  offset: number;
};

export type AlertListResponse = {
  items: Alert[];
  total: number;
  limit: number;
  offset: number;
};

export type IncidentDetailResponse = {
  incident: Incident;
  alerts: Alert[];
  actions: {
    id: number;
    action_type: string;
    description: string;
    user?: string | null;
    extra_metadata?: unknown;
    timestamp?: string | null;
  }[];
};

export type SimilarIncident = {
  id: number;
  title: string;
  status: string;
  severity: string;
  assigned_team?: string | null;
  score: number;
};

export type SimilarIncidentResponse = {
  items: SimilarIncident[];
  total: number;
  limit: number;
};

export type DashboardMetricsResponse = {
  active_incidents: number;
  critical_incidents: number;
  untriaged_alerts: number;
  mtta_minutes: number | null;
  mttr_minutes: number | null;
};

export type Runbook = {
  id: string;
  title: string;
  source: string;
  tags: string[];
  last_updated?: string | null;
};

export type RunbookListResponse = {
  items: Runbook[];
  total: number;
  limit: number;
  offset: number;
};

export type Connector = {
  id: string;
  name: string;
  status: string;
  detail?: string | null;
  updated_at?: string | null;
};

export type ConnectorListResponse = {
  items: Connector[];
  total: number;
  limit: number;
  offset: number;
};

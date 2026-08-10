import client from "./client";

export interface DashboardRunItem {
  id: number;
  project_id: number;
  project_name: string;
  project_status: "active" | "disabled";
  status: "queued" | "running" | "success" | "failed" | "skipped";
  triggered_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  platforms: string[];
  prompt_count: number;
}

export interface DashboardUpcomingItem {
  project_id: number;
  project_name: string;
  customer_id: number;
  customer_name: string;
  next_run_at: string;
  platforms: string[];
}

export interface DashboardOut {
  today_runs: number;
  today_success: number;
  today_failed: number;
  enabled_projects: number;
  status_distribution: {
    queued: number;
    running: number;
    success: number;
    failed: number;
    skipped: number;
  };
  recent_runs: DashboardRunItem[];
  upcoming: DashboardUpcomingItem[];
}

export const getDashboard = () =>
  client.get<DashboardOut>("/dashboard").then((r) => r.data);

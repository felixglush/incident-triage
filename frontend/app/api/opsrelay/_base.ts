const DEFAULT_BASE = "http://backend:8000";

export function getOpsRelayBase() {
  return process.env.OPSRELAY_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_BASE;
}

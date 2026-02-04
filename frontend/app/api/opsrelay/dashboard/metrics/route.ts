import { getOpsRelayBase } from "../../_base";

export async function GET(_request: Request) {
  const base = getOpsRelayBase();
  const res = await fetch(`${base}/dashboard/metrics`);
  const body = await res.text();
  return new Response(body, { status: res.status, headers: { "Content-Type": "application/json" } });
}

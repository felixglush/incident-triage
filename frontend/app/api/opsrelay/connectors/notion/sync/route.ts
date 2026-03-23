import { getOpsRelayBase } from "../../../_base";

export async function POST() {
  const base = getOpsRelayBase();
  const res = await fetch(`${base}/connectors/notion/sync`, { method: "POST" });
  const body = await res.text();
  return new Response(body, { status: res.status, headers: { "Content-Type": "application/json" } });
}

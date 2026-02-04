import { getOpsRelayBase } from "../../../_base";

export async function POST(_request: Request, { params }: { params: { id: string } }) {
  const base = getOpsRelayBase();
  const res = await fetch(`${base}/connectors/${params.id}/connect`, { method: "POST" });
  const body = await res.text();
  return new Response(body, { status: res.status, headers: { "Content-Type": "application/json" } });
}

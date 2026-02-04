import { getOpsRelayBase } from "../../_base";

export async function GET(_request: Request, { params }: { params: { id: string } }) {
  const base = getOpsRelayBase();
  const res = await fetch(`${base}/incidents/${params.id}`);
  const body = await res.text();
  return new Response(body, { status: res.status, headers: { "Content-Type": "application/json" } });
}

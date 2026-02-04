import { getOpsRelayBase } from "../../../_base";

export async function PATCH(request: Request, { params }: { params: { id: string } }) {
  const base = getOpsRelayBase();
  const url = new URL(request.url);
  const target = `${base}/incidents/${params.id}/status${url.search}`;
  const res = await fetch(target, { method: "PATCH" });
  const body = await res.text();
  return new Response(body, { status: res.status, headers: { "Content-Type": "application/json" } });
}

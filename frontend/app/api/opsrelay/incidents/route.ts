import { getOpsRelayBase } from "../_base";

export async function GET(request: Request) {
  const base = getOpsRelayBase();
  const url = new URL(request.url);
  const target = `${base}/incidents${url.search}`;
  const res = await fetch(target);
  const body = await res.text();
  return new Response(body, { status: res.status, headers: { "Content-Type": "application/json" } });
}

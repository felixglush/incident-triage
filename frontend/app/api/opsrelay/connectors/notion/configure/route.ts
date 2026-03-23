import { getOpsRelayBase } from "../../../_base";

export async function POST(request: Request) {
  const base = getOpsRelayBase();
  const body = await request.text();
  const res = await fetch(`${base}/connectors/notion/configure`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const responseBody = await res.text();
  return new Response(responseBody, { status: res.status, headers: { "Content-Type": "application/json" } });
}

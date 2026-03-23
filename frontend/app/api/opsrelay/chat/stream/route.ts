import { getOpsRelayBase } from "../../_base";

export async function GET(request: Request) {
  const base = getOpsRelayBase();
  const url = new URL(request.url);
  const target = `${base}/chat/stream${url.search}`;
  const res = await fetch(target, {
    headers: { Accept: "text/event-stream" },
  });

  const contentType = res.headers.get("content-type") || "application/json";
  const headers = new Headers();
  headers.set("Content-Type", contentType);
  if (contentType.includes("text/event-stream")) {
    headers.set("Cache-Control", "no-cache");
    headers.set("Connection", "keep-alive");
  }

  return new Response(res.body, {
    status: res.status,
    headers,
  });
}

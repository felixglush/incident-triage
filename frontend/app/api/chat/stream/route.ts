export const runtime = "nodejs";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function GET() {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: string, data: unknown) => {
        controller.enqueue(encoder.encode(`event: ${event}\n`));
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
      };

      send("assistant", {
        id: "msg-2",
        role: "assistant",
        content: "Summarizing incident and pulling related context...",
      });

      await sleep(600);
      send("tool", { tool: "incident.similar", status: "running" });

      await sleep(500);
      send("tool", { tool: "runbook.search", status: "running" });

      await sleep(700);
      send("assistant", {
        id: "msg-3",
        role: "assistant",
        content:
          "Summary ready. Similar incidents: INC-0921, INC-0897. Next steps queued.",
      });

      send("done", { status: "complete" });
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

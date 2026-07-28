import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

function backendURL(path: string[], search: string): string {
  const baseURL = process.env.VERITY_API_URL?.replace(/\/$/, "");
  if (!baseURL) {
    throw new Error("VERITY_API_URL is not configured");
  }
  return `${baseURL}/${path.map(encodeURIComponent).join("/")}${search}`;
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  try {
    const { path } = await context.params;
    const headers = new Headers();
    const contentType = request.headers.get("content-type");
    const accept = request.headers.get("accept");
    const lastEventID = request.headers.get("last-event-id");
    const token = process.env.VERITY_API_TOKEN;

    if (contentType) headers.set("content-type", contentType);
    if (accept) headers.set("accept", accept);
    if (lastEventID) headers.set("last-event-id", lastEventID);
    if (token) headers.set("authorization", `Bearer ${token}`);
    headers.set("x-forwarded-for", request.headers.get("x-forwarded-for") ?? "vercel");

    const upstream = await fetch(
      backendURL(path, request.nextUrl.search),
      {
        method: request.method,
        headers,
        body:
          request.method === "GET" || request.method === "HEAD"
            ? undefined
            : await request.arrayBuffer(),
        cache: "no-store",
        redirect: "manual",
        signal: request.signal,
      },
    );
    const responseHeaders = new Headers();
    for (const name of ["content-type", "cache-control", "x-accel-buffering"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "backend proxy failed";
    return Response.json({ error: message }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;

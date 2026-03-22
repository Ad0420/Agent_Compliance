import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const sitePassword = process.env.SITE_PASSWORD;

  // If no password is configured, allow through (local dev)
  if (!sitePassword) {
    return NextResponse.next();
  }

  const authHeader = request.headers.get("authorization");

  if (authHeader) {
    const encoded = authHeader.split(" ")[1];
    const decoded = Buffer.from(encoded, "base64").toString("utf-8");
    const password = decoded.split(":").slice(1).join(":");

    if (password === sitePassword) {
      return NextResponse.next();
    }
  }

  return new NextResponse("Access restricted.", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Vera"',
    },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

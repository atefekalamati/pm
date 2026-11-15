import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

export default function config(phase: string): NextConfig {
  return {
    // Built as static files and served by FastAPI.
    output: "export",
    turbopack: {
      rules: {
        "*.css": {
          loaders: ["@tailwindcss/turbopack"],
          as: "*.css",
        },
      },
    },
    // `npm run dev` only: send /api to the FastAPI backend. The static export has no rewrites;
    // there FastAPI serves the app and the API from the same address.
    ...(phase === PHASE_DEVELOPMENT_SERVER && {
      rewrites: async () => [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }],
    }),
  };
}

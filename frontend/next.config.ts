import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
};

export default nextConfig;

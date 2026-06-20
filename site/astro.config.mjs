import { defineConfig } from "astro/config";

const cacheDir = process.env.MRP_ASTRO_CACHE_DIR;

export default defineConfig({
  site: "https://www.maricoparecords.com",
  output: "static",
  ...(cacheDir ? { cacheDir } : {})
});

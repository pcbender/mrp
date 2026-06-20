import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

process.env.ASTRO_TELEMETRY_DISABLED ??= "1";

const require = createRequire(import.meta.url);
const astroPackage = require.resolve("astro/package.json");
const astroBin = path.join(path.dirname(astroPackage), "astro.js");

const child = spawn(process.execPath, [astroBin, ...process.argv.slice(2)], {
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});

import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const outDir = path.join(rootDir, "dist", "main");

const sharedConfig = {
  bundle: true,
  platform: "node",
  target: "node22",
  format: "cjs",
  external: ["electron"],
  sourcemap: false,
  logLevel: "info"
};

await Promise.all([
  build({
    ...sharedConfig,
    entryPoints: [path.join(rootDir, "src/main/index.ts")],
    outfile: path.join(outDir, "index.js")
  }),
  build({
    ...sharedConfig,
    entryPoints: [path.join(rootDir, "src/main/shell-preload.ts")],
    outfile: path.join(outDir, "shell-preload.js")
  }),
  build({
    ...sharedConfig,
    entryPoints: [path.join(rootDir, "src/main/web-preload.ts")],
    outfile: path.join(outDir, "web-preload.js")
  })
]);

console.log("[luminara-shell] Main & preload bundles built -> dist/main/");

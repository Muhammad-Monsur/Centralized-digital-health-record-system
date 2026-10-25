// Production asset build: bundle + minify + content-hash CSS/JS/fonts into app/static/dist,
// and write dist/manifest.json, which the templates use (USE_BUILT_ASSETS=true) to emit
// fingerprinted URLs. Fingerprinted files never change, so they're served with
// "Cache-Control: public, max-age=31536000, immutable" and are safe to put on a CDN.
//
//   npm run build        (or: node scripts/build_assets.mjs)
//   npm run clean
import { build } from "esbuild";
import { readFileSync, readdirSync, copyFileSync, rmSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { brotliCompressSync, gzipSync } from "node:zlib";
import path from "node:path";

const STATIC = "app/static";
const OUT = `${STATIC}/dist`;

rmSync(OUT, { recursive: true, force: true });
if (process.argv.includes("--clean")) process.exit(0);
mkdirSync(OUT, { recursive: true });

const common = {
  bundle: true,
  minify: true,
  outdir: OUT,
  metafile: true,
  logLevel: "warning",
  legalComments: "none",
  absWorkingDir: process.cwd(),
};

// CSS: @imports are inlined (no request waterfall); url(../fonts/x.woff2) files are copied with a hash.
const css = await build({
  ...common,
  entryPoints: { core: `${STATIC}/css/core.css`, portal: `${STATIC}/css/portal.css`, landing: `${STATIC}/css/landing.css` },
  entryNames: "[name].[hash]",
  assetNames: "fonts/[name].[hash]",
  loader: { ".woff2": "file", ".svg": "file" },
  target: ["chrome109", "firefox115", "safari15.4", "edge109"],
});

// JS: one entry; every dynamic import() becomes its own chunk (code splitting per page).
const js = await build({
  ...common,
  entryPoints: { main: `${STATIC}/js/main.js` },
  entryNames: "[name].[hash]",
  chunkNames: "chunks/[name].[hash]",
  format: "esm",
  splitting: true,
  target: ["es2020"],
});

// manifest: "css/core.css" -> "dist/core.3F2A.css", "fonts/x.woff2" -> "dist/fonts/x.ABCD.woff2"
const manifest = {};
const rel = (p) => path.relative(STATIC, p).split(path.sep).join("/");
for (const result of [css, js]) {
  for (const [out, meta] of Object.entries(result.metafile.outputs)) {
    if (out.endsWith(".map")) continue;
    if (meta.entryPoint) manifest[rel(meta.entryPoint)] = rel(out);
    else if (out.includes("/fonts/")) {
      const src = Object.keys(meta.inputs)[0];
      if (src) manifest[rel(src)] = rel(out);
    }
  }
}
// Photos: copied with a content hash so they can be cached for a year like the bundles.
const PHOTOS = `${STATIC}/img/photos`;
mkdirSync(`${OUT}/img`, { recursive: true });
for (const name of readdirSync(PHOTOS)) {
  if (!/\.(avif|webp|jpe?g|png)$/i.test(name)) continue;
  const src = `${PHOTOS}/${name}`;
  const hash = createHash("sha256").update(readFileSync(src)).digest("hex").slice(0, 8).toUpperCase();
  const ext = path.extname(name);
  const out = `${OUT}/img/${path.basename(name, ext)}.${hash}${ext}`;
  copyFileSync(src, out);
  manifest[rel(src)] = rel(out);
}
writeFileSync(`${OUT}/manifest.json`, JSON.stringify(manifest, null, 2));

// Size report (what the browser actually downloads after compression).
const rows = [];
for (const result of [css, js]) {
  for (const out of Object.keys(result.metafile.outputs)) {
    if (out.endsWith(".woff2")) continue;
    const buf = readFileSync(out);
    rows.push([rel(out), statSync(out).size, gzipSync(buf).length, brotliCompressSync(buf).length]);
  }
}
const kb = (n) => (n / 1024).toFixed(1).padStart(6);
console.log("file".padEnd(46), "  raw KB  gzip KB  br KB");
for (const [f, raw, gz, br] of rows.sort()) console.log(f.padEnd(46), kb(raw), kb(gz), kb(br));
console.log(`manifest: ${Object.keys(manifest).length} entries -> ${OUT}/manifest.json`);

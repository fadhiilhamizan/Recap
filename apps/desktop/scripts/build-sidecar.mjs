// Bangun sidecar Rust dan salin ke src-tauri/binaries dengan sufiks target triple,
// sesuai konvensi `bundle.externalBin` Tauri (misalnya recap-dummy-sidecar-x86_64-pc-windows-msvc.exe).
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..", "..");
const profile = process.argv.includes("--debug") ? "debug" : "release";
const triple = execFileSync("rustc", ["--print", "host-tuple"], { encoding: "utf8" }).trim();
const sidecars = ["recap-dummy-sidecar"];

execFileSync("cargo", ["build", ...(profile === "release" ? ["--release"] : []), ...sidecars.flatMap((s) => ["-p", s])], {
  cwd: root,
  stdio: "inherit",
});
const outDir = join(here, "..", "src-tauri", "binaries");
mkdirSync(outDir, { recursive: true });
for (const name of sidecars) {
  const ext = process.platform === "win32" ? ".exe" : "";
  copyFileSync(join(root, "target", profile, name + ext), join(outDir, `${name}-${triple}${ext}`));
  console.log(`sidecar: ${name}-${triple}${ext}`);
}

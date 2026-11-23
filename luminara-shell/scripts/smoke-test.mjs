import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const UNIT_ONLY = process.env.LUMINARA_SMOKE_UNIT_ONLY === "1";

function walkFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkFiles(full));
    else out.push(full);
  }
  return out;
}

// 1. Static hygiene check: zero .innerHTML and every file strictly < 450 lines
console.log("[smoke] 1/5 Checking static hygiene (zero .innerHTML, <450 lines per file)...");
const srcFiles = walkFiles(path.join(rootDir, "src")).filter((f) => /\.(ts|tsx|html|js|css)$/.test(f));
for (const file of srcFiles) {
  const text = fs.readFileSync(file, "utf8");
  assert.equal(
    /\.innerHTML\b/.test(text),
    false,
    `Forbidden .innerHTML found in ${path.relative(rootDir, file)}`
  );
  const lineCount = text.split(/\r?\n/).length;
  assert.ok(
    lineCount < 450,
    `File ${path.relative(rootDir, file)} exceeds 450 lines (${lineCount})`
  );
}
console.log(`[smoke] Checked ${srcFiles.length} source files: 0 .innerHTML, all < 450 lines.`);

// 2. Verify compiled artifacts exist
console.log("[smoke] 2/5 Verifying dist/ build outputs...");
const requiredDist = [
  "dist/main/index.js",
  "dist/main/shell-preload.js",
  "dist/main/web-preload.js",
  "dist/renderer/index.html"
];
for (const rel of requiredDist) {
  assert.ok(fs.existsSync(path.join(rootDir, rel)), `Missing build output: ${rel}`);
}

// 3. Compile & unit-test main process modules via esbuild into temp dir
console.log("[smoke] 3/5 Running unit tests on privacy-shield, mutation-firewall, store, bot-brain, session-guards...");
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "luminara-v4-smoke-"));
const electronStubPath = path.join(tmpDir, "electron-stub.cjs");
fs.writeFileSync(electronStubPath, "module.exports = { session: { fromPartition: () => ({}) } };", "utf8");
const modulesToTest = ["privacy-shield", "mutation-firewall", "store", "bot-brain", "session-guards"];
await Promise.all(
  modulesToTest.map((name) =>
    build({
      entryPoints: [path.join(rootDir, `src/main/${name}.ts`)],
      outfile: path.join(tmpDir, `${name}.cjs`),
      bundle: true,
      platform: "node",
      format: "cjs",
      target: "node22",
      alias: { electron: electronStubPath }
    })
  )
);

const shieldMod = require(path.join(tmpDir, "privacy-shield.cjs"));
const firewallMod = require(path.join(tmpDir, "mutation-firewall.cjs"));
const storeMod = require(path.join(tmpDir, "store.cjs"));
const brainMod = require(path.join(tmpDir, "bot-brain.cjs"));
const guardsMod = require(path.join(tmpDir, "session-guards.cjs"));

// Unit Test A: Privacy Shield v3 (first-party preservation, GET/mainFrame-only stripping, redirect-loop break)
assert.ok(shieldMod.TRACKER_DOMAINS.length >= 80, "Expected 80+ tracker domains");
const shield = new shieldMod.PrivacyShieldManager();
assert.equal(
  shield.evaluateRequest("https://stats.doubleclick.net/collect", "https://news.ycombinator.com", "xhr", "tab_1").action,
  "block"
);
assert.equal(
  shield.evaluateRequest("https://js.hubspot.com/embed.js", "https://example.org", "script", "tab_1").action,
  "block",
  "Third-party tracker must be blocked"
);
assert.equal(
  shield.evaluateRequest("https://js.hubspot.com/app.js", "https://app.hubspot.com/dashboard", "script", "tab_1").action,
  "allow",
  "First-party hubspot asset on hubspot.com must NEVER be blocked"
);
assert.equal(
  shield.evaluateRequest("https://browser.sentry.io/api", "https://sentry.io/issues", "xhr", "tab_1").action,
  "allow",
  "First-party sentry asset on sentry.io must NEVER be blocked"
);
assert.equal(
  shield.evaluateRequest("https://example.org/api?utm_source=x", "https://example.org", "xhr", "tab_1", "POST").action,
  "allow",
  "POST/XHR query params must never be stripped"
);
const stripRes = shield.evaluateRequest(
  "https://example.org/pricing?plan=pro&si=keepme&utm_source=x&fbclid=abc123&gclid=xyz",
  "https://previous-site.invalid",
  "mainFrame",
  "tab_1",
  "GET"
);
assert.equal(stripRes.action, "redirect");
assert.equal(stripRes.redirectURL, "https://example.org/pricing?plan=pro&si=keepme");
// Redirect loop breaker: immediate repeat of same cleaned URL within 5s must allow
const loopRes = shield.evaluateRequest(
  "https://example.org/pricing?plan=pro&si=keepme&utm_source=loop",
  "https://example.org",
  "mainFrame",
  "tab_1",
  "GET"
);
assert.equal(loopRes.action, "allow", "Redirect loop must be broken within 5s window");

shield.toggleDomain("example.org");
assert.equal(shield.isDomainPaused("example.org"), true);
assert.equal(
  shield.evaluateRequest("https://stats.doubleclick.net/pixel", "https://example.org", "image", "tab_1").action,
  "allow"
);
shield.toggleDomain("example.org");
console.log("[smoke]   PrivacyShieldManager PASS (first-party safe, GET mainFrame strip, loop break, domain toggle)");

// Unit Test B: Mutation Firewall (multipart scrubbing, ping/cspReport ignored, cancelTab, allow/deny/timeout)
const cards = [];
const fw = new firewallMod.MutationFirewallManager({
  timeoutMs: 250,
  alwaysGuard: true,
  onCardCreated: (c) => cards.push(c)
});

assert.equal(
  fw.shouldIntercept({
    url: "https://example.org/beacon",
    method: "POST",
    resourceType: "ping",
    tabId: "tab_1",
    botId: null,
    botName: "Page",
    botColor: "#199473",
    isBotInitiated: true
  }),
  false,
  "ping resource type must be ignored"
);

const multipartBody = [
  "--bound123",
  'Content-Disposition: form-data; name="username"',
  "",
  "alice",
  "--bound123",
  'Content-Disposition: form-data; name="password"',
  "",
  "ultra-secret-pass",
  "--bound123",
  'Content-Disposition: form-data; name="note"',
  "",
  "Token Bearer eyJsecret123456789",
  "--bound123--"
].join("\r\n");

const p1 = fw.requestApproval({
  url: "https://shop.example.org/api/checkout",
  method: "POST",
  resourceType: "xhr",
  tabId: "tab_1",
  botId: "remy",
  botName: "Remy",
  botColor: "#16A095",
  isBotInitiated: true,
  uploadData: [{ bytes: Buffer.from(multipartBody) }]
});
assert.equal(cards.length, 1);
assert.equal(cards[0].diffPreview.includes("ultra-secret-pass"), false, "Multipart password leaked!");
assert.equal(cards[0].diffPreview.includes("eyJsecret123456789"), false, "Multipart token leaked!");
assert.equal(cards[0].diffPreview.includes("username: alice"), true);
fw.resolveDecision(cards[0].id, "allow-once");
assert.equal(await p1, true);

// Test cancelTab cleans up pending card immediately
const pCancel = fw.requestApproval({
  url: "https://shop.example.org/api/delete",
  method: "DELETE",
  tabId: "tab_close_me",
  botId: "pi",
  botName: "Pi",
  botColor: "#7C4DFF",
  isBotInitiated: true
});
assert.equal(fw.cancelTab("tab_close_me"), 1);
assert.equal(await pCancel, false);

// Test always-allow-site and timeout
const pAlways = fw.requestApproval({
  url: "https://trusted.example.org/api/save",
  method: "PUT",
  tabId: "tab_2",
  botId: "dana",
  botName: "Dana",
  botColor: "#2E7CF6",
  isBotInitiated: true
});
fw.resolveDecision(cards[cards.length - 1].id, "always-site");
assert.equal(await pAlways, true);

const pTimeout = fw.requestApproval({
  url: "https://slow.example.org/api/submit",
  method: "POST",
  tabId: "tab_2",
  botId: "remy",
  botName: "Remy",
  botColor: "#16A095",
  isBotInitiated: true
});
assert.equal(await pTimeout, false);
console.log("[smoke]   MutationFirewallManager PASS (multipart scrub, ping ignore, cancelTab, allow/always/timeout)");

// Unit Test C: LocalStore enc:v1 prefix + no plaintext disk write when OS encryption unavailable
const storeDirEnc = path.join(tmpDir, "userdata-enc");
const storeEnc = new storeMod.LocalStore(storeDirEnc, {
  isAvailable: () => true,
  encrypt: (s) => Buffer.from(`ENC:${s}`, "utf8"),
  decrypt: (b) => b.toString("utf8").replace(/^ENC:/, "")
});
const pubEnc = storeEnc.updateSettings({ provider: "openrouter", apiKey: "sk-or-test-987654" });
assert.equal(pubEnc.hasApiKey, true);
assert.equal(pubEnc.encryptionAvailable, true);
assert.equal(storeEnc.getDecryptedApiKey(), "sk-or-test-987654");
const diskEnc = JSON.parse(fs.readFileSync(path.join(storeDirEnc, "luminara-v4-config.json"), "utf8"));
assert.ok(diskEnc.encryptedApiKeyBase64.startsWith("enc:v1:"), "Disk secret must use enc:v1 prefix");

const storeDirNoEnc = path.join(tmpDir, "userdata-noenc");
const storeNoEnc = new storeMod.LocalStore(storeDirNoEnc, {
  isAvailable: () => false,
  encrypt: () => Buffer.alloc(0),
  decrypt: () => ""
});
const pubNoEnc = storeNoEnc.updateSettings({ provider: "openai", apiKey: "sk-plain-must-not-write" });
assert.equal(pubNoEnc.hasApiKey, true);
assert.equal(pubNoEnc.encryptionAvailable, false);
assert.equal(storeNoEnc.getDecryptedApiKey(), "sk-plain-must-not-write");
const rawDiskNoEnc = fs.readFileSync(path.join(storeDirNoEnc, "luminara-v4-config.json"), "utf8");
assert.equal(rawDiskNoEnc.includes("sk-plain-must-not-write"), false, "Plaintext key written to disk!");
assert.equal(JSON.parse(rawDiskNoEnc).encryptedApiKeyBase64, "");
console.log("[smoke]   LocalStore PASS (enc:v1 atomic storage, zero plaintext disk fallback)");

// Unit Test D: BotBrain, SSRF endpoint validation, localhost URLs, step secret scrubbing, permission policy
const pibotBuiltin = path.resolve(rootDir, "../vendor/PiBot/packages/teams/builtin");
const brain = new brainMod.BotBrain(pibotBuiltin);
assert.ok(brain.getBots().length >= 4);
assert.equal(brainMod.formatSearchUrl("localhost:3000/app", "duckduckgo"), "http://localhost:3000/app");
assert.equal(brainMod.formatSearchUrl("openai.com", "duckduckgo"), "https://openai.com");
assert.throws(() => brainMod.validateHttpUrl("https://"), /valid/i);
assert.throws(() => brainMod.validateHttpUrl("javascript:alert(1)"), /http/i);
assert.equal(brainMod.validateHttpUrl("example.org"), "https://example.org/");
assert.throws(() => brainMod.validateEndpointUrl("http://169.254.169.254/latest/meta-data"), /Blocked/i);
assert.throws(() => brainMod.validateEndpointUrl("https://[fe80::1]/v1"), /Blocked/i);
assert.throws(() => brainMod.validateEndpointUrl("https://[fd00:ec2::254]/v1"), /Blocked/i);
assert.throws(() => brainMod.validateEndpointUrl("http://evil.example.com/v1"), /HTTPS/i);
assert.equal(brainMod.validateEndpointUrl("http://127.0.0.1:11434").hostname, "127.0.0.1");

assert.equal(
  brainMod.sanitizeRecordedStep({ action: "input", label: "Password", selector: "input[type=password]", valuePreview: "hunter2" }),
  null
);
const scrubbedStep = brainMod.sanitizeRecordedStep({
  action: "input",
  label: "Notes",
  selector: "#notes",
  valuePreview: "Key is sk-live-secret99999999"
});
assert.equal(scrubbedStep.valuePreview.includes("sk-live-secret99999999"), false);
assert.equal(scrubbedStep.valuePreview.includes("[redacted]"), true);

assert.equal(guardsMod.isWebPermissionAllowed("geolocation"), false);
assert.equal(guardsMod.isWebPermissionAllowed("media"), false);
assert.equal(guardsMod.isWebPermissionAllowed("notifications"), false);
assert.equal(guardsMod.isWebPermissionAllowed("fullscreen"), true);
assert.equal(guardsMod.isWebPermissionAllowed("clipboard-sanitized-write"), true);
console.log("[smoke]   BotBrain + Security Guards PASS (SSRF block, localhost routing, step redaction, permissions)");

// 4. Boot REAL Electron binary unless LUMINARA_SMOKE_UNIT_ONLY=1
if (UNIT_ONLY) {
  console.log("[smoke] 4/5 LUMINARA_SMOKE_UNIT_ONLY=1 set — skipping Electron GUI launch.");
  fs.rmSync(tmpDir, { recursive: true, force: true });
  console.log("[smoke] 5/5 UNIT-ONLY CHECKS PASSED.");
  process.exit(0);
}

console.log("[smoke] 4/5 Launching real Electron runtime smoke check (BaseWindow + sandboxed shellView + WebContentsView)...");
const electronExe = require("electron");
const electronEnv = { ...process.env, LUMINARA_SMOKE_TEST: "1" };
delete electronEnv.ELECTRON_RUN_AS_NODE;

const electronResult = await new Promise((resolve, reject) => {
  const child = spawn(electronExe, [rootDir], {
    cwd: rootDir,
    env: electronEnv,
    stdio: ["ignore", "pipe", "pipe"]
  });
  let stdout = "";
  let stderr = "";
  const killTimer = setTimeout(() => {
    child.kill();
    reject(new Error(`Electron smoke test timed out.\nSTDOUT:\n${stdout}\nSTDERR:\n${stderr}`));
  }, 25_000);

  child.stdout.on("data", (d) => {
    stdout += d.toString();
  });
  child.stderr.on("data", (d) => {
    stderr += d.toString();
  });
  child.on("close", (code) => {
    clearTimeout(killTimer);
    resolve({ code, stdout, stderr });
  });
});

assert.equal(
  electronResult.code,
  0,
  `Electron exited with ${electronResult.code}\nSTDOUT:\n${electronResult.stdout}\nSTDERR:\n${electronResult.stderr}`
);
const okLine = electronResult.stdout.split(/\r?\n/).find((line) => line.includes('"SMOKE_OK"'));
assert.ok(okLine, `Missing SMOKE_OK marker in Electron output:\n${electronResult.stdout}`);
console.log(`[smoke] 5/5 Real Electron smoke verified: ${okLine.trim()}`);

fs.rmSync(tmpDir, { recursive: true, force: true });
console.log("[smoke] ALL CHECKS PASSED.");

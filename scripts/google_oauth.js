/**
 * BELMONT OPS — Google OAuth Token Generator
 * Runs locally to get Calendar + Gmail refresh tokens, then pushes them to Railway.
 *
 * Usage:
 *   cd C:\Users\jacob\.claude\sessions\belmont-ops\scripts
 *   node google_oauth.js
 *
 * Reads credentials from environment variables or a local .env file.
 * Set these before running (or create a scripts/.env file):
 *   GOOGLE_CLIENT_ID=...
 *   GOOGLE_CLIENT_SECRET=...
 *   RAILWAY_TOKEN=...
 *   RAILWAY_PROJECT_ID=be63e025-0e77-4466-8e36-2e08ad2cf753
 *   RAILWAY_ENV_ID=d02dce4a-0c67-4766-819d-10eb9be9dc9b
 *   RAILWAY_TELEGRAM_SERVICE_ID=e035affa-1533-4ba4-a20e-6119b44d4e38
 *   RAILWAY_MCP_SERVICE_ID=eb2b0794-5cf4-4092-a6ce-756ea1319870
 */

const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");
const { URL } = require("url");

// ── Load .env if present ───────────────────────────────────────────────────────
const envFile = path.join(__dirname, ".env");
if (fs.existsSync(envFile)) {
  const lines = fs.readFileSync(envFile, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
    if (m) process.env[m[1]] = m[2].trim();
  }
}

const CLIENT_ID = process.env.GOOGLE_CLIENT_ID || "";
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET || "";
const RAILWAY_TOKEN = process.env.RAILWAY_TOKEN || "";
const PROJECT_ID = process.env.RAILWAY_PROJECT_ID || "be63e025-0e77-4466-8e36-2e08ad2cf753";
const ENV_ID = process.env.RAILWAY_ENV_ID || "d02dce4a-0c67-4766-819d-10eb9be9dc9b";
const TELEGRAM_SERVICE_ID = process.env.RAILWAY_TELEGRAM_SERVICE_ID || "e035affa-1533-4ba4-a20e-6119b44d4e38";
const MCP_SERVICE_ID = process.env.RAILWAY_MCP_SERVICE_ID || "eb2b0794-5cf4-4092-a6ce-756ea1319870";
const REDIRECT_URI = "http://127.0.0.1:3456/callback";

if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error("❌ GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set.");
  console.error("   Create a scripts/.env file with:\n   GOOGLE_CLIENT_ID=...\n   GOOGLE_CLIENT_SECRET=...\n   RAILWAY_TOKEN=...");
  process.exit(1);
}

// Google OAuth scopes — Calendar + Gmail
const SCOPES = [
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/calendar.events",
  "https://www.googleapis.com/auth/gmail.send",
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.compose",
].join(" ");

function buildAuthUrl() {
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: "code",
    scope: SCOPES,
    access_type: "offline",
    prompt: "consent",
  });
  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
}

function exchangeCode(code) {
  return new Promise((resolve, reject) => {
    const body = new URLSearchParams({
      code, client_id: CLIENT_ID, client_secret: CLIENT_SECRET,
      redirect_uri: REDIRECT_URI, grant_type: "authorization_code",
    }).toString();
    const req = https.request(
      { hostname: "oauth2.googleapis.com", path: "/token", method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "Content-Length": Buffer.byteLength(body) } },
      (res) => { let d = ""; res.on("data", c => d += c); res.on("end", () => resolve(JSON.parse(d))); }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

function railwayUpsert(serviceId, name, value) {
  return new Promise((resolve, reject) => {
    if (!RAILWAY_TOKEN) { console.log(`  ⚠️  RAILWAY_TOKEN not set — cannot push ${name} automatically`); resolve({}); return; }
    const query = JSON.stringify({ query: `mutation { variableUpsert(input: { projectId: "${PROJECT_ID}", environmentId: "${ENV_ID}", serviceId: "${serviceId}", name: "${name}", value: ${JSON.stringify(value)} }) }` });
    const req = https.request(
      { hostname: "backboard.railway.app", path: "/graphql/v2", method: "POST",
        headers: { Authorization: `Bearer ${RAILWAY_TOKEN}`, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(query) } },
      (res) => { let d = ""; res.on("data", c => d += c); res.on("end", () => resolve(JSON.parse(d))); }
    );
    req.on("error", reject);
    req.write(query);
    req.end();
  });
}

async function pushToRailway(tokens) {
  const vars = [
    { name: "GOOGLE_REFRESH_TOKEN", value: tokens.refresh_token },
    { name: "GOOGLE_ACCESS_TOKEN", value: tokens.access_token },
    // Keep client credentials in sync with whichever client generated these tokens
    { name: "GOOGLE_CLIENT_ID", value: CLIENT_ID },
    { name: "GOOGLE_CLIENT_SECRET", value: CLIENT_SECRET },
  ];
  console.log("\n🚂 Pushing tokens to Railway...");
  for (const { name, value } of vars) {
    if (!value) { console.log(`  ⚠️  Skipping ${name} — not in token response`); continue; }
    await railwayUpsert(TELEGRAM_SERVICE_ID, name, value);
    await railwayUpsert(MCP_SERVICE_ID, name, value);
    console.log(`  ✅ ${name} set on both services`);
  }
  console.log("\n✅ Railway updated! Both services will auto-redeploy in ~1 minute.\n");
}

function openBrowser(url) {
  const { exec } = require("child_process");
  const cmd = process.platform === "win32" ? `start "" "${url}"` : process.platform === "darwin" ? `open "${url}"` : `xdg-open "${url}"`;
  exec(cmd);
}

async function main() {
  console.log("\n🔑 Belmont Ops — Google OAuth Token Generator\n");
  const authUrl = buildAuthUrl();

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost:3456");
    if (url.pathname !== "/callback") { res.end("Not found"); return; }

    const code = url.searchParams.get("code");
    const error = url.searchParams.get("error");

    if (error) {
      res.writeHead(400, { "Content-Type": "text/html" });
      res.end(`<h2>❌ Error: ${error}</h2>`);
      console.error(`\n❌ OAuth error: ${error}`);
      server.close();
      return;
    }

    console.log("  ✅ Authorization code received");
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<html><body style="font-family:sans-serif;padding:40px;text-align:center"><h2>✅ Success!</h2><p>Tokens are being pushed to Railway. You can close this window.</p></body></html>`);
    server.close();

    try {
      console.log("  🔄 Exchanging code for tokens...");
      const tokens = await exchangeCode(code);
      if (tokens.error) { console.error(`\n❌ Token exchange failed: ${tokens.error} — ${tokens.error_description}`); return; }
      console.log(`  ✅ access_token received (expires ${tokens.expires_in}s)`);
      console.log(`  ✅ refresh_token: ${tokens.refresh_token ? "YES" : "MISSING"}`);

      if (!tokens.refresh_token) {
        console.log("\n⚠️  No refresh_token returned. The app was previously authorized.");
        console.log("   Go to https://myaccount.google.com/permissions → remove 'Belmont Ops' → re-run.\n");
        return;
      }

      await pushToRailway(tokens);

      console.log("📋 Tokens saved to Railway and printed below:\n");
      console.log(`   GOOGLE_REFRESH_TOKEN = ${tokens.refresh_token}`);
      console.log(`   GOOGLE_ACCESS_TOKEN  = ${tokens.access_token}\n`);
    } catch (e) {
      console.error("\n❌ Error:", e.message);
    }
  });

  server.listen(3456, "127.0.0.1", () => {
    console.log("📡 Callback server: http://127.0.0.1:3456");
    console.log("\n🌐 Opening Google sign-in in your browser...");
    console.log("   (paste manually if browser didn't open:)\n");
    console.log(`   ${authUrl}\n`);
    openBrowser(authUrl);
    console.log('⏳ Waiting for you to authorize "Belmont Ops"...\n');
  });
}

main().catch(console.error);

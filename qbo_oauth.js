/**
 * BELMONT OPS — QBO OAUTH TOKEN FETCHER
 * Run: node qbo_oauth.js
 * Then open the URL shown, authorize in browser, tokens print automatically.
 */

const http = require('http');
const https = require('https');
const url = require('url');

const CLIENT_ID     = 'ABqaZQt2xE9iHzd3N9uhVvYE9VmwQUHxdrTCvxUjHpaoZVVsbt';
const CLIENT_SECRET = 'YEHbX7YXINyNSEzq3ulzcgbsPGGlCcRTiRvlgTFF';
const REDIRECT_URI  = 'http://localhost:8888/callback';
const STATE         = 'belmont' + Date.now();

const authUrl =
  'https://appcenter.intuit.com/connect/oauth2?' +
  `client_id=${CLIENT_ID}` +
  `&response_type=code` +
  `&scope=com.intuit.quickbooks.accounting` +
  `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}` +
  `&state=${STATE}`;

console.log('\n========================================');
console.log(' BELMONT QBO OAUTH — OPEN THIS URL:');
console.log('========================================\n');
console.log(authUrl);
console.log('\n========================================');
console.log('Waiting on http://localhost:8888 ...\n');

const server = http.createServer((req, res) => {
  const parsed = url.parse(req.url, true);

  if (parsed.pathname !== '/callback') {
    res.end('Not found');
    return;
  }

  const code    = parsed.query.code;
  const realmId = parsed.query.realmId || '9341456262197564';

  if (!code) {
    res.end('<h2>Error: no code in callback. Check your Intuit app redirect URI setting.</h2>');
    server.close();
    process.exit(1);
  }

  res.end('<h2>Authorization successful! Close this tab and check your terminal.</h2>');
  console.log('Got auth code. Exchanging for tokens...');

  const credentials = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64');
  const postData    = `grant_type=authorization_code&code=${code}&redirect_uri=${encodeURIComponent(REDIRECT_URI)}`;

  const options = {
    hostname: 'oauth.platform.intuit.com',
    path:     '/oauth2/v1/tokens/bearer',
    method:   'POST',
    headers: {
      'Authorization':  `Basic ${credentials}`,
      'Content-Type':   'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(postData)
    }
  };

  const tokenReq = https.request(options, (tokenRes) => {
    let data = '';
    tokenRes.on('data', chunk => data += chunk);
    tokenRes.on('end', () => {
      try {
        const tokens = JSON.parse(data);
        if (tokens.error) {
          console.error('\nToken exchange failed:', tokens.error_description || tokens.error);
          server.close();
          process.exit(1);
        }
        console.log('\n========================================');
        console.log(' COPY THESE — SET IN RAILWAY MCP SERVER');
        console.log('========================================\n');
        console.log(`QBO_ACCESS_TOKEN=${tokens.access_token}`);
        console.log(`QBO_REFRESH_TOKEN=${tokens.refresh_token}`);
        console.log(`QBO_REALM_ID=${realmId}`);
        console.log(`\nAccess token expires in: ${tokens.expires_in}s (~1 hour)`);
        console.log('Refresh token expires in: ~100 days');
        console.log('\n========================================\n');
        server.close();
        process.exit(0);
      } catch (e) {
        console.error('Parse error:', e, '\nRaw response:', data);
        server.close();
        process.exit(1);
      }
    });
  });

  tokenReq.on('error', e => {
    console.error('Request error:', e);
    server.close();
  });

  tokenReq.write(postData);
  tokenReq.end();
});

server.on('error', e => {
  if (e.code === 'EADDRINUSE') {
    console.error('\nPort 8888 is in use. Close whatever is using it and retry.');
  } else {
    console.error('Server error:', e);
  }
  process.exit(1);
});

server.listen(8888);

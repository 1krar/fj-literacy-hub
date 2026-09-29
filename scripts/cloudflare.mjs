import { generateKeyPairSync, privateDecrypt, constants } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const project = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const credentialDir = join(process.env.APPDATA, 'CodexCloudflare');
const privateKeyFile = join(credentialDir, 'private-key.dpapi');
const tokenFile = join(credentialDir, 'pages-token.enc');
const publicKeyFile = join(credentialDir, 'public-key.pem');
const mode = process.argv[2];
const account = JSON.parse(readFileSync(join(project, 'cloudflare-account.json'), 'utf8'));
function powershell(command, input = '') {
  const cleanEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => key.toLowerCase() !== 'psmodulepath'));
  const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', command], {
    input, encoding: 'utf8', windowsHide: true,
    env: { ...cleanEnv, CODEX_CF_KEY_FILE: privateKeyFile },
  });
  if (result.status !== 0) {
    const message = result.error?.message || result.stderr?.split(/\r?\n/)[0] || `exit ${result.status}`;
    throw new Error(`Windows credential encryption/decryption failed: ${message.replace(/[A-Za-z0-9_+/=-]{30,}/g, '[redacted]')}`);
  }
  return result.stdout.trim();
}
if (mode === 'init-key') {
  mkdirSync(credentialDir, { recursive: true });
  if (!existsSync(privateKeyFile)) {
    const keys = generateKeyPairSync('rsa', {
      modulusLength: 3072,
      publicKeyEncoding: { type: 'spki', format: 'pem' },
      privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    });
    powershell("$ErrorActionPreference='Stop'; $taskPlain=[Console]::In.ReadToEnd(); $taskSecure=ConvertTo-SecureString -String $taskPlain -AsPlainText -Force; $taskCipher=ConvertFrom-SecureString $taskSecure; [IO.File]::WriteAllText($env:CODEX_CF_KEY_FILE,$taskCipher)", keys.privateKey);
    writeFileSync(publicKeyFile, keys.publicKey);
  }
  if (!existsSync(publicKeyFile)) throw new Error('Credential public key is missing.');
  if (process.argv[3]) writeFileSync(process.argv[3], readFileSync(publicKeyFile));
  console.log('Windows-protected credential key is ready.');
} else {
  let token = process.env.CLOUDFLARE_API_TOKEN;
  if (!token && existsSync(tokenFile)) {
    const privateKey = powershell("$ErrorActionPreference='Stop'; $taskSecure=ConvertTo-SecureString ([IO.File]::ReadAllText($env:CODEX_CF_KEY_FILE)); $taskPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskSecure); try { [Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskPointer)) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskPointer) }");
    token = privateDecrypt({ key: privateKey, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256' }, readFileSync(tokenFile)).toString('utf8');
  }
  if (mode === 'verify') {
    if (!token) throw new Error('Cloudflare deployment credential is not configured.');
    const headers = { Authorization: `Bearer ${token}` };
    const config = JSON.parse(readFileSync(join(project, 'wrangler.jsonc'), 'utf8'));
    const verified = await fetch('https://api.cloudflare.com/client/v4/user/tokens/verify', { headers });
    const data = await verified.json();
    if (!verified.ok || !data.success || data.result?.status !== 'active') throw new Error(`Token verification failed (HTTP ${verified.status}).`);
    const response = await fetch(`https://api.cloudflare.com/client/v4/accounts/${account.account_id}/pages/projects/${config.name}`, { headers });
    const page = await response.json();
    if (!response.ok || !page.success) throw new Error(`Pages project access failed (HTTP ${response.status}).`);
    console.log(JSON.stringify({ credential: 'active', project: page.result.name, domain: page.result.subdomain, productionBranch: page.result.production_branch }, null, 2));
  } else {
    const args = process.argv.slice(2);
    const result = spawnSync(process.execPath, [join(project, 'node_modules', 'wrangler', 'bin', 'wrangler.js'), ...args], {
      cwd: project, stdio: 'inherit', windowsHide: true,
      env: { ...process.env, CLOUDFLARE_ACCOUNT_ID: account.account_id, ...(token ? { CLOUDFLARE_API_TOKEN: token } : {}), WRANGLER_SEND_METRICS: 'false' },
    });
    process.exitCode = result.status ?? 1;
  }
}

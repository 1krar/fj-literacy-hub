import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const file = path.join(root, 'dist', 'resources.json');
const data = JSON.parse(fs.readFileSync(file, 'utf8'));
const ids = new Set();
const urls = new Set();
const categories = new Set(data.categories.map(c => c.id));
for (const resource of data.resources) {
  if (ids.has(resource.id)) throw new Error(`Duplicate ID: ${resource.id}`);
  ids.add(resource.id);
  const url = new URL(resource.url);
  if (!['https:', 'http:'].includes(url.protocol)) throw new Error(`Unsupported URL: ${resource.url}`);
  const normalized = resource.url.replace(/\/$/, '');
  if (urls.has(normalized)) throw new Error(`Duplicate URL: ${resource.url}`);
  urls.add(normalized);
  if (!resource.name || !resource.description || !['website', 'course', 'document'].includes(resource.kind)) throw new Error(`Invalid resource: ${resource.id}`);
  if (!resource.categories.length || !resource.categories.every(c=>categories.has(c))) throw new Error(`Invalid category: ${resource.id}`);
  if (!resource.modules.every(n=>Number.isInteger(n) && n >= 1 && n <= 50)) throw new Error(`Invalid module: ${resource.id}`);
}
if (Object.keys(data.modules).length !== 50) throw new Error('Expected 50 module labels');
for (let n = 1; n <= 50; n++) {
  if (!data.resources.some(r=>r.modules.includes(n))) throw new Error(`No entry for module ${n}`);
}
fs.writeFileSync(path.join(root, 'dist', 'resources.js'), `window.LITERACY_DATA = ${JSON.stringify(data)};\n`);
const bookmarkData = JSON.parse(fs.readFileSync(path.join(root, 'dist', 'bookmarks.json'), 'utf8'));
let bookmarkCount = 0;
const bookmarkIds = new Set();
function validateBookmarks(nodes) {
  for (const node of nodes) {
    if (!node.id || !node.name || bookmarkIds.has(node.id)) throw new Error('Invalid bookmark ID/name');
    bookmarkIds.add(node.id);
    if (node.children) validateBookmarks(node.children);
    else {
      bookmarkCount++;
      if (node.url) {
        const url = new URL(node.url);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error(`Invalid bookmark link: ${node.id}`);
        for (const key of url.searchParams.keys()) if (/token|secret|password|authkey|api_key|pass_ticket|exportkey/i.test(key)) throw new Error(`Credential field in bookmark: ${node.id}`);
      } else if (!node.entry) throw new Error(`Missing bookmark entry: ${node.id}`);
      if (node.icon && !/^data:image\/(png|jpeg|x-icon);base64,[A-Za-z0-9+/=]+$/.test(node.icon)) throw new Error(`Invalid icon: ${node.id}`);
    }
  }
}
validateBookmarks(bookmarkData.folders);
fs.writeFileSync(path.join(root, 'dist', 'bookmarks.js'), `window.BOOKMARK_DATA = ${JSON.stringify(bookmarkData)};\n`);
// Cache-bust each dependency after edits, including previously cached resources.js.
let html = fs.readFileSync(path.join(root, 'dist', 'index.html'), 'utf8');
for (const asset of ['styles.css', 'resources.js', 'bookmarks.js', 'app.js']) {
  const hash = createHash('sha256').update(fs.readFileSync(path.join(root, 'dist', asset))).digest('hex').slice(0,10);
  const regex = new RegExp(`(["'])${asset.replace('.', '\\.')}[^"']*(["'])`, 'g');
  html = html.replace(regex, `$1${asset}?v=${hash}$2`);
}
fs.writeFileSync(path.join(root, 'dist', 'index.html'), html);
for (const [view, title] of [['bookmarks','我的收藏夹'], ['resources','备赛资源库']]) {
  fs.writeFileSync(path.join(root, 'dist', `${view}.html`), html.replace('data-view="home"', `data-view="${view}"`).replace(/<title>.*?<\/title>/, `<title>${title} · 素养聚合</title>`));
}
console.log(`Imported ${bookmarkCount} bookmarks. Generated home, bookmarks and resources pages.`);
console.log(`Validated ${data.resources.length} links across 50 modules. Static output: dist/`);

const coreHash = createHash('sha256').update(fs.readFileSync(path.join(root,'dist','assistant-core.mjs'))).digest('hex').slice(0,10);
const assistantModule = path.join(root,'dist','assistant.mjs');
fs.writeFileSync(assistantModule, fs.readFileSync(assistantModule,'utf8').replace(/assistant-core\.mjs(?:\?v=[a-f0-9]+)?/g,'assistant-core.mjs?v='+coreHash));
let assistantHtml = fs.readFileSync(path.join(root,'dist','assistant.html'),'utf8');
for (const asset of ['assistant.css','assistant.mjs','resources.js','bookmarks.js']) {
  const hash = createHash('sha256').update(fs.readFileSync(path.join(root,'dist',asset))).digest('hex').slice(0,10);
  assistantHtml = assistantHtml.replace(new RegExp(asset.replace('.', '\\.') + '(?:\\?v=[a-f0-9]+)?', 'g'), asset+'?v='+hash);
}
fs.writeFileSync(path.join(root,'dist','assistant.html'),assistantHtml);
console.log('Generated question assistant with trusted catalog routes.');
let launchHtml=fs.readFileSync(path.join(root,'dist','launch-assistant.html'),'utf8');
for (const asset of ['launch-assistant.css','launch-assistant.mjs']) {
  const hash=createHash('sha256').update(fs.readFileSync(path.join(root,'dist',asset))).digest('hex').slice(0,10);
  launchHtml=launchHtml.replace(new RegExp(asset.replace('.', '\\.')+'(?:\\?v=[a-f0-9]+)?','g'),asset+'?v='+hash);
}
fs.writeFileSync(path.join(root,'dist','launch-assistant.html'),launchHtml);

const guidePath=path.join(root,"dist","assistant-guide.html");
const guideCssHash=createHash("sha256").update(fs.readFileSync(path.join(root,"dist","launch-assistant.css"))).digest("hex").slice(0,10);
fs.writeFileSync(guidePath,fs.readFileSync(guidePath,"utf8").replace(/launch-assistant\.css(?:\?v=[a-f0-9]+)?/g,"launch-assistant.css?v="+guideCssHash));
let ctrlHtml=fs.readFileSync(path.join(root,'dist','ctrl-assistant.html'),'utf8');
const ctrlModule=path.join(root,'dist','ctrl-assistant-v2.mjs');
const captureHash=createHash('sha256').update(fs.readFileSync(path.join(root,'dist','capture-input.mjs'))).digest('hex').slice(0,10);
fs.writeFileSync(ctrlModule,fs.readFileSync(ctrlModule,'utf8').replace(/capture-input\.mjs(?:\?v=[a-f0-9]+)?/g,'capture-input.mjs?v='+captureHash));
fs.writeFileSync(ctrlModule,fs.readFileSync(ctrlModule,'utf8').replace(/assistant-core\.mjs(?:\?v=[a-f0-9]+)?/g,'assistant-core.mjs?v='+coreHash));
for(const asset of ['ctrl-assistant.css','ctrl-assistant-v2.mjs']){
  const hash=createHash('sha256').update(fs.readFileSync(path.join(root,'dist',asset))).digest('hex').slice(0,10);
  ctrlHtml=ctrlHtml.replace(new RegExp(asset.replace('.', '\\.')+'(?:\\?v=[a-zA-Z0-9]+)?','g'),asset+'?v='+hash);
}
fs.writeFileSync(path.join(root,'dist','ctrl-assistant.html'),ctrlHtml);

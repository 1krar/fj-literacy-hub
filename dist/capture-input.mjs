// Each document owns one handler, including the Document Picture-in-Picture page.
const bound = new WeakSet();
export function bindImageCapture(doc, receive, onError = () => {}) {
  if (bound.has(doc)) return;
  bound.add(doc);
  const accept = file => {
    if (file) Promise.resolve(receive(file)).catch(onError);
  };
  doc.addEventListener('paste', event => {
    const item = Array.from(event.clipboardData?.items || []).find(item =>
      item.kind === 'file' && item.type.startsWith('image/'));
    if (!item) return; // Ordinary text keeps native paste semantics.
    event.preventDefault();
    accept(item.getAsFile());
  });
  doc.addEventListener('dragover', event => {
    if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault();
  });
  doc.addEventListener('drop', event => {
    if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return;
    event.preventDefault();
    const images = Array.from(event.dataTransfer?.files || []).filter(file => file.type.startsWith('image/'));
    images.forEach(accept);
    if (!images.length) onError(new Error('请拖入 PNG 或 JPEG 图片'));
  });
}

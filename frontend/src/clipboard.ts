/**
 * Copies `text` to the clipboard; false if the browser would not.
 *
 * navigator.clipboard only exists in a secure context (HTTPS or localhost),
 * and the deployed site is served over plain HTTP by the load balancer. There
 * the older select-and-execCommand('copy') route still works, as long as it
 * runs inside the click handler.
 */
export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

export const money = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
export const cost = (value) => value == null ? 'Unknown' : money.format(value);
export const label = (name) => name.replaceAll('_', ' ');
export const eventTypes = ['strike', 'congestion', 'equipment_failure', 'severe_weather'];

export async function api(path, body) {
  const response = await fetch('/api' + path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const { detail } = await response.json().catch(() => ({}));
    const reason = Array.isArray(detail) ? detail.map((item) => item.msg || item.issue).join('; ') : detail;
    throw new Error(reason || 'Connect the HarborShift API on port 8000 and try again.');
  }
  return response.json();
}

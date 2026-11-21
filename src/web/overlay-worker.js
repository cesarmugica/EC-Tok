// EC-Tok: UNA sola conexión de eventos para todas las fuentes de EC-Tok abiertas en el mismo programa (LIVE Studio/OBS).
// El navegador solo abre 6 conexiones a la vez con la misma dirección; con 6 o más fuentes, cada una con su conexión,
// ya no quedaba lugar para bajar los videos y los personajes dejaban de salir. Aquí se escucha una vez y se reparte.
let es = null;
const ports = new Set();
const send = data => { for (const p of ports) { try { p.postMessage(data); } catch (_) { ports.delete(p); } } };
function open() {
  es = new EventSource('/api/stream?who=overlay');
  es.onmessage = m => send(m.data);
  es.onopen = () => send('{"type":"_open"}');
}
onconnect = e => {
  const port = e.ports[0];
  ports.add(port);
  port.onmessage = m => { if (m.data === 'bye') ports.delete(port); };
  port.start();
  if (!es) open(); else if (es.readyState === 1) port.postMessage('{"type":"_open"}');
};

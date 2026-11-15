# EC-Tok

Alertas, sonidos, lectura de chat y metas para tus **lives de TikTok** — gratis, para Windows. Al estilo de TikFinity.

## Qué hace

- **🔔 Alertas en pantalla**: cuando alguien manda un regalo, te sigue o comparte el live, aparece una alerta animada (con confeti en regalos grandes).
- **🔊 Sonidos por regalo**: elige qué sonido toca con cada regalo (uno en especial, regalos de N 💎 o más, cualquier regalo), con follows, compartidos o cada N likes.
- **🗣 Leer el chat**: una voz de Windows lee los comentarios (y si quieres también regalos, follows y compartidos).
- **🎬 Animaciones**: automáticas (Heart Me, follow, cofre, suscripción, batallas, x2/x3…), botones de acceso rápido y pantalla «Ya regresamos». Trae un banco de animaciones y puedes agregar las tuyas (WebM/WebP con transparencia, APNG o GIF).
- **🎯 Metas y 🏆 top donadores**: barras de progreso (likes, diamantes, regalos, follows, compartidos) y el ranking de quién más dona.
- **Modo prueba**: botones para ver alertas, sonidos y voz sin estar en vivo.

## Cómo se usa

1. Instala **EC-Tok-Setup** (pestaña *Releases*) y ábrelo.
2. En **🔴 En vivo** escribe tu @usuario y dale **Conectar** (si todavía no estás en vivo, EC-Tok espera y se conecta solo).
3. Copia la dirección del overlay (alertas, metas o top) y agrégala como fuente web:
   - **TikTok LIVE Studio**: ➕ Agregar fuente → Enlace (Link).
   - **OBS**: Fuente → Navegador.
4. Los sonidos y la voz suenan en tu PC: que LIVE Studio u OBS capture el audio del escritorio.

## Cómo funciona por dentro

TikTok no tiene una conexión oficial para esto. EC-Tok usa la librería libre
[TikTokLive](https://github.com/isaackogan/TikTokLive) (no oficial), que se conecta con solo el @usuario (sin contraseña)
y usa el servicio de firma de [Euler Stream](https://www.eulerstream.com) (gratis, con límite de conexiones por hora; con
una clave propia el límite es más alto — se pone en ⚙ Ajustes). Si TikTok cambia algo, puede dejar de conectar unas horas
hasta que se actualice la librería.

El programa es un servidor local (solo `127.0.0.1:8795`) con la ventana y los overlays.
Los datos se guardan en `%LOCALAPPDATA%\EC-Tok` (ajustes y sonidos).

EC-Tok no es de TikTok ni está afiliado con TikTok. Código abierto (la librería TikTokLive usa una licencia AGPL modificada).

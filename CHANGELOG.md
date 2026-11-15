# Cambios de EC-Tok

## 1.5.2 — La chica también se anima
- La escena de la chica ahora es animada (brinca, levanta el puño, se ríe), con el letrero siguiéndola cuadro por cuadro.

## 1.5.1 — El chico ahora sí se anima
- La escena del chico es animación de verdad (brinca, levanta el puño, se ríe) y **el texto del letrero lo sigue cuadro por cuadro**, aunque el letrero se mueva o se incline.
- Las escenas aceptan tiras de cuadros con el letrero ubicado en cada cuadro (para los personajes animados que vengan).

## 1.5.0 — Escenas con letrero 🧒👧
- Nuevas animaciones tipo Pixar: **un chico y una chica que entran brincando, se mecen, con un corazón que late y un letrero** donde EC-Tok escribe lo que tú quieras.
- **Cada regla tiene su propio texto** para el letrero, con comodines: `{user}` (sale resaltado), `{gift}`, `{count}`, `{likes}`, `{diamonds}`. Ej.: «¡Gracias por seguirme, {user}!» o «¡Gracias por tus {likes} likes!». Si lo dejas vacío, pone uno según lo que pasó y en tu idioma. El texto se acomoda solo al tamaño del letrero.
- En español, los regalos comunes salen con su nombre en español en el letrero (Heart Me → Quiéreme, Rose → Rosa…).
- En los botones rápidos, el letrero dice el nombre del botón.
- Las pestañas de arriba (En vivo, Alertas, Animaciones…) se quedan fijas aunque bajes en la página.
- En instalaciones nuevas, el follow sale con el chico y su letrero.

## 1.4.0 — ❤️ Top likes
- Nuevo ranking de **quién te da más likes** (tap a la pantalla): en 🔴 En vivo junto al top de donadores, y como overlay para tu live: `http://localtest.me:8795/overlay?w=likes`.
- Título y cuántos mostrar en 🎯 Metas y top.
- Arreglado: el top de donadores vacío mostraba un texto raro en vez de «Todavía nadie… ¡manda el primer regalo!».

## 1.3.1
- En el modo prueba, el Heart Me llega de uno en uno (TikTok solo deja mandar uno al día por persona), sin «×10».

## 1.3.0 — El nombre de quien lo mandó
- Las animaciones automáticas ahora pueden mostrar **la foto y el nombre de quien mandó el regalo** (o quien te siguió, abrió el cofre o se suscribió), en una tarjeta que aparece con un rebote debajo de la animación. En regalos también dice cuál y cuántos («Rosa ×5»).
- Se prende o apaga por animación con la nueva columna **Nombre** (🎬 Animaciones). Viene prendida en Heart Me, follow, regalos grandes, cofre y suscripción.
- El botón ▶ de cada regla muestra cómo se ve, con tu @usuario de ejemplo.

## 1.2.6 — «Ya regresamos» se quita completo
- Al quitar la pantalla «☕ Ya regresamos», el fondo oscuro semitransparente ya no se queda encima del live.

## 1.2.5 — Créditos
- Abajo de la ventana: «💜 EC-Tok es gratis y siempre lo será. Sigue la cuenta @imuxoficial en TikTok (Colab Claude AI)», en los tres idiomas.

## 1.2.4 — Direcciones listas para LIVE Studio
- Las direcciones de los overlays (pestaña 🔴 En vivo → 📋 Copiar) ahora son `http://localtest.me:8795/overlay?w=…`, que TikTok LIVE Studio acepta tal cual.

## 1.2.3 — La ventana vieja se cierra al actualizar
- Al darle **Actualizar**, la ventana vieja de EC-Tok se cierra sola y queda solo la nueva (igual que en EC-Tube). El programa viejo también se cierra en cuanto arranca el instalador.

## 1.2.2 — Actualizar sin dejar la versión vieja abierta
- Al darle **Actualizar**, la versión vieja ahora se cierra sola en cuanto arranca el instalador (antes a veces se quedaba en memoria junto a la nueva).
- La ventana de EC-Tok que tenías abierta se recarga sola con la versión nueva, en lugar de abrirse una segunda ventana.

## 1.2.1 — Overlays en TikTok LIVE Studio
- TikTok LIVE Studio no aceptaba las direcciones `http://127.0.0.1…` ni `http://localhost…` («Introduce una URL válida»). Ahora los overlays usan `http://ectok.localhost:8795/overlay?w=…`, que LIVE Studio sí acepta y que apunta a tu propia PC.
- Si alguna vez no carga, cambia `ectok.localhost` por `localtest.me`.
- Por seguridad, con esos nombres solo se abren los overlays; la ventana de EC-Tok sigue siendo solo para tu PC.

## 1.2.0 — Español, English, Português (Brasil)
- La ventana de EC-Tok ahora está en **español, inglés y portugués de Brasil** (🌐 arriba a la derecha). Arranca en el idioma que elijas al instalar; el instalador también viene en los tres.
- Los textos de fábrica (alertas, lectura de chat, metas, «Ya regresamos», botones rápidos) se cambian al nuevo idioma; los que ya editaste se respetan.
- Nuevas animaciones **THANK YOU!** y **OBRIGADO!** (la de «¡GRACIAS!» cambia sola según el idioma).
- Los mensajes de conexión y los comentarios de prueba también salen en el idioma elegido.

## 1.1.3 — Regalos en inglés o español
- Las reglas de animaciones y sonidos reconocen los regalos comunes con su nombre en inglés o en español: «Heart Me» = «Quiéreme», «Rose» = «Rosa», «Lion» = «León», «Universe» = «Universo», etc. (y sin importar acentos o mayúsculas).

## 1.1.2 — El Heart Me sale con el globo
- La animación de fábrica del **Heart Me** ahora es el **globo corazón** (si no la habías cambiado, se cambia sola).

## 1.1.1 — Globo de corazón
- Nueva animación en el banco: **globo corazón** (un globo metálico rojo que sube flotando), hecha por Cesar con IA y suavizada a 25 cuadros por segundo.

## 1.1.0 — 🎬 Animaciones
- Nueva pestaña **🎬 Animaciones** y nuevo overlay **🎬 Animaciones** (`/overlay?w=anim`).
- **Automáticas**, cada una con su casilla sí/no, animación, duración y tamaño: cualquier regalo, un regalo en especial (p. ej. Heart Me), regalos de N 💎 o más, follow, compartir, cada N likes, suscripción, Super Fan, regalo de la comunidad (cofre), empieza/termina una batalla y potenciadores x2/x3. Si llegan varias juntas, salen en fila.
- **⚡ Botones de acceso rápido** (también teclas 1 a 9 en 🔴 En vivo) para lanzar una animación cuando quieras.
- **☕ «Ya regresamos»**: pantalla de pausa con la animación y el texto que elijas; se queda hasta que la quitas.
- **Banco de animaciones**: 12 que trae EC-Tok (corazones, confeti, fuegos artificiales, estrellas, ¡Gracias!, x2, x3, micrófono cantando, osito bailando, café «ya regreso», ecualizador, globos de plática) y las tuyas en `%LOCALAPPDATA%\EC-Tok\animaciones` (WebM o WebP con transparencia recomendados; también APNG y GIF).
- Batallas y potenciadores casi no están documentados por TikTok: EC-Tok intenta reconocerlos y guarda los primeros en el registro para afinarlos.

## 1.0.0 — Primera versión
- **🔴 En vivo**: conectar con tu @usuario (sin contraseña); si todavía no estás en vivo, espera y se conecta solo. Lista de lo que va pasando (regalos, follows, compartidos, likes, comentarios) y cuentas del live.
- **🔔 Alertas en pantalla** (overlay para TikTok LIVE Studio u OBS): regalos (desde N 💎), follows, compartidos y cada N likes; textos editables, colores, tamaño, animación y posición; confeti en regalos grandes.
- **🔊 Sonidos por regalo**: reglas por regalo exacto, regalos de N 💎 o más, cualquier regalo, follows, compartidos o cada N likes; en fila o encimados; volumen por sonido.
- **🗣 Leer el chat** con las voces de Windows: comentarios, regalos, follows y compartidos; voz, velocidad, tono y volumen; solo comentarios con un prefijo; sin enlaces.
- **🎯 Metas** (likes, diamantes, regalos, follows, compartidos) y **🏆 Top donadores** como overlays.
- **Modo prueba** para ver todo sin estar en vivo.
- Botón **Actualizar** y clave opcional de Euler Stream en ⚙ Ajustes.

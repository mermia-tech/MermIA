# Prompts de ilustración: agente de WhatsApp

Prompts para generar las 9 imágenes de `docs/agente-whatsapp-flujo-visual.md` en Gemini o ChatGPT. Cada prompt se pega solo, en una conversación nueva, y produce una sola imagen. Guarda cada imagen en esta carpeta con el nombre exacto de la tabla, en formato `.jpg`.

| Archivo | Sección del documento |
|---|---|
| `01-recorrido-mensaje.jpg` | 1. El recorrido de un mensaje (inicio) |
| `02-quien-contesta.jpg` | 2. Cómo decide quién contesta (inicio) |
| `03-cambio-de-dato.jpg` | 3. Cómo se cambia un dato (inicio) |
| `04-llega-reporte.jpg` | 4. Cómo llega un reporte (inicio) |
| `05-numeros-con-recibo.jpg` | 1, Paso 7: la IA redacta y el código revisa los números |
| `06-propone-aprueba-aplica.jpg` | 3, Paso 1: la IA propone, no guarda |
| `07-archivo-repetido.jpg` | 4, Paso 1: se descarga y guarda el archivo |
| `08-siempre-hay-respuesta.jpg` | 2, Paso 3: ¿se pasó del tope? |
| `09-ventana-24-horas.jpg` | 3, Paso 3: el dueño recibe el cambio con botones |

Todos los prompts comparten el mismo bloque de estilo. Va repetido en cada uno para que se puedan pegar por separado.

---

## 01-recorrido-mensaje.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: one message travels from the owner's phone, through a check of who is writing, to a counter where the question is answered, and back as one sealed reply.

Metaphor: a tiny post office road. Xiaohei is the mail carrier walking a winding orange path. At the start, Xiaohei picks up an envelope that drops out of a big hand-drawn phone. In the middle, Xiaohei holds the envelope up to a small booth window where a hand stamps an ID card. Further on, Xiaohei slides the envelope into a counter slot labeled with a magnifying glass. At the end, Xiaohei walks back toward the phone carrying a single sealed envelope.

Handwritten labels in Spanish (each label appears EXACTLY ONCE, short, handwritten):
- "mensaje de Carlos" (black, near the phone)
- "¿quién escribe?" (black, near the ID booth)
- "consulta" (black, near the counter slot)
- "una sola respuesta" (orange, near the sealed envelope)
- "se registra" (blue, small note near the end of the path)
- "nada de silencio" (blue, small note)

Rules: no title anywhere, no numbers, no numbered steps, no step boxes. Do not write the words "inteligencia artificial calcula", "automático", "guardado". Keep Xiaohei and the path within 40-60% of the canvas.
```

## 02-quien-contesta.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: fixed rules decide first; only what is left goes to the AI.

Metaphor: a railway junction. Xiaohei stands on a small platform and pulls a big lever with both arms. Three thin tracks split from one point. A short train of envelopes goes to a near platform with a button on a post. A second short train goes to a platform with a stack of pre-printed cards. The third track climbs a long gentle hill toward a distant small cloud-shaped station.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "botón" (black, near the button platform)
- "plantilla" (black, near the printed cards)
- "lo demás" (orange, on the climbing track)
- "IA" (black, near the distant station)
- "reglas fijas primero" (orange, near the lever)
- "sin costo" (blue, small note near the first two platforms)

Rules: no title anywhere, no numbers, no numbered steps. Do not write "la IA decide", "aleatorio", "todo va a la IA". Main subject within 40-60% of the canvas.
```

## 03-cambio-de-dato.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: a requested price change waits at a locked door until a person with the key opens it.

Metaphor: Xiaohei stands very still holding up a sheet of paper that shows a crossed-out old price and a new price written next to it, in front of a tall door with a big padlock. Behind the door, a filing cabinet. To the side, a simple human figure (the owner) holds the only key. A small hourglass sits on the floor next to Xiaohei.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "$212 → $225 el kilo" (black, on the sheet Xiaohei holds)
- "pendiente" (orange, near Xiaohei)
- "la llave es del dueño" (black, near the human figure)
- "confirmar" (orange, near the keyhole)
- "vence en 24 h" (red, near the hourglass)
- "queda en la bitácora" (blue, near the filing cabinet)

Rules: no title anywhere, no numbered steps, the only numbers allowed are the ones inside the labels above. Do not write "guardado", "aplicado", "listo". The door must look closed. Main subject within 40-60% of the canvas.
```

## 04-llega-reporte.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: a spreadsheet report is received, read and sorted into one of three outcomes; a clean one can still be undone.

Metaphor: Xiaohei works at a small hand-drawn sorting table. A spreadsheet sheet with a grid slides in from the left along an orange chute. Xiaohei reads it through a big magnifying glass. Three trays sit in front: one shelf where the sheet goes in neatly, one tray with a question mark tag, one tray with the sheet folded and returned. A small rewind-arrow knob sits on the shelf.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "reporte del gerente" (black, near the incoming sheet)
- "leer" (orange, near the magnifying glass)
- "aplicado" (black, near the shelf)
- "en revisión" (orange, near the question-mark tray)
- "rechazado con nota" (red, near the returned tray)
- "deshacer" (blue, near the rewind knob)

Rules: no title anywhere, no numbers, no numbered steps. Do not write "IA", "inteligencia artificial", "automático". Main subject within 40-60% of the canvas.
```

## 05-numeros-con-recibo.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: the AI only copies numbers; code checks that every number in the reply has a receipt from a database query. A number without a receipt is thrown out.

Metaphor: Xiaohei is an inspector at a small desk, wearing nothing special, holding a reply sheet with a few figures circled. Next to Xiaohei is a neat spike holding paper receipts. Xiaohei pinches one circled figure with tweezers and holds it against the receipts. A second figure, with no matching receipt, falls off the sheet into a small trash bin.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "respuesta" (black, near the reply sheet)
- "recibos de la consulta" (black, near the spike of receipts)
- "¿tiene recibo?" (orange, near the tweezers)
- "número inventado" (red, near the falling figure)
- "se reintenta una vez" (blue, small note)
- "la IA no hace cuentas" (black, small)

Rules: no title anywhere, no numbered steps. Draw figures only as squiggles or "$" shapes, do not write real amounts. Do not write "la IA calcula", "estimado", "aproximado". Main subject within 40-60% of the canvas.
```

## 06-propone-aprueba-aplica.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: three separate hands: the AI proposes, a person approves, the code applies. The AI never touches the records.

Metaphor: a thin wall divides the scene. On the left, Xiaohei writes on a small paper and pushes it through a mail slot in the wall. On the right, a simple human figure signs the paper with a pen. Further right, a mechanical arm on a rail opens a filing cabinet drawer only after the signature. Xiaohei's side of the wall has no access to the cabinet.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "propone" (orange, near Xiaohei)
- "aprueba una persona" (black, near the human)
- "aplica el código" (black, near the mechanical arm)
- "la IA no guarda" (red, on Xiaohei's side of the wall)
- "antes y después" (blue, near the paper)

Rules: no title anywhere, no numbers, no numbered steps. Do not write "la IA guarda", "automático", "aplicado por la IA". Main subject within 40-60% of the canvas.
```

## 07-archivo-repetido.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: every file has a fingerprint; the same file sent twice is recognized and not loaded again.

Metaphor: Xiaohei holds a big magnifying glass over a file that has a fingerprint drawn on its corner. Behind Xiaohei is an open drawer full of small fingerprint cards. Xiaohei holds one card from the drawer next to the file: they match. With the other hand Xiaohei pushes the file back out through a small window, stamped. A different file with a new fingerprint goes along an orange path to a shelf.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "huella del archivo" (black, near the fingerprint)
- "ya lo había recibido" (blue, near the returned stamped file)
- "archivo nuevo" (orange, near the file on the path)
- "se cuenta una vez" (black, near the shelf)
- "ventas infladas" (red, small, crossed out)

Rules: no title anywhere, no numbers, no numbered steps. Do not write "se carga dos veces", "borrado", "IA". Main subject within 40-60% of the canvas.
```

## 08-siempre-hay-respuesta.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: when the daily limit is reached or the AI fails, the user still gets an answer: a menu of frequent questions. Never silence.

Metaphor: a small shop counter. Behind it, a roll-down shutter over a window is closed. In front of the closed shutter, Xiaohei calmly hands a printed menu card to the first of a short line of envelope-shaped visitors with tiny legs. A small stack of identical menu cards sits on the counter.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "tope del día" (red, on the closed shutter)
- "menú de preguntas" (orange, near the card Xiaohei hands out)
- "nunca silencio" (black, near Xiaohei)
- "IA en pausa" (blue, small note near the shutter)
- "mañana se reinicia" (blue, small note)

Rules: no title anywhere, no numbers, no numbered steps. Do not write "cerrado", "error", "sin servicio", "vuelva después". Main subject within 40-60% of the canvas.
```

## 09-ventana-24-horas.jpg

```text
Generate ONE standalone illustration, 16:9 horizontal.

Style: pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. Lots of empty white space (at least 35% blank). No gradients, no shadows, no paper texture, no PPT or infographic look, no commercial vector style, no children's illustration, no cute mascot, no realistic phone UI.

Character: Xiaohei (小黑), a small solid-black creature with white dot eyes, thin legs and thin arms, slightly uneven hand-drawn body, blank serious deadpan expression. Not cute. Xiaohei must DO the central action.

Idea: after the user writes, there is a 24-hour window for free messages with buttons. When it closes, only official pre-approved templates can be sent, and they cost money.

Metaphor: Xiaohei stands guard beside a small gate next to a giant hourglass. On the left half of the scene, sand is still falling and Xiaohei lets handwritten letters with little buttons drawn on them pass through the gate. On the right half, the same hourglass is empty, and Xiaohei lets through only a stiff envelope with a wax seal, while holding a small coin.

Handwritten labels in Spanish (each label appears EXACTLY ONCE):
- "el usuario escribió" (black, near the falling sand)
- "mensaje libre con botones" (orange, near the handwritten letters)
- "ventana cerrada" (red, near the empty hourglass)
- "plantilla aprobada por Meta" (black, near the sealed envelope)
- "cuesta" (blue, near the coin)

Rules: no title anywhere, no numbers, no numbered steps. Do not write "gratis siempre", "spam", "promoción". Main subject within 40-60% of the canvas.
```

---

## Lista de control (revisa cada imagen)

- [ ] Es horizontal 16:9.
- [ ] El fondo es blanco puro, sin textura, sombra ni degradado.
- [ ] Hay mucho espacio en blanco; el dibujo ocupa más o menos la mitad.
- [ ] Xiaohei aparece y **hace** la acción central (si lo quitas, la idea ya no se entiende).
- [ ] Xiaohei se ve serio, no tierno ni de caricatura infantil.
- [ ] No parece una diapositiva, un diagrama formal ni una pantalla de celular real.
- [ ] Están todas las etiquetas pedidas y **cada una aparece una sola vez**.
- [ ] Ortografía en español correcta, con acentos y signos (¿ ?), sin letras inventadas.
- [ ] No hay títulos (sobre todo arriba a la izquierda).
- [ ] No hay números ni pasos numerados, salvo los que pide la etiqueta (solo la imagen 03).
- [ ] No aparecen las palabras prohibidas de su prompt.
- [ ] Colores: negro para lo principal, naranja para el flujo, rojo solo en advertencias, azul en notas.

## Prompt de corrección por edición

Úsalo sobre la imagen generada, cambiando lo que está entre llaves. Corrige una cosa a la vez.

```text
Edit the provided image. Change only this: {describe el problema, por ejemplo: "remove the handwritten title in the top-left corner" / "the label 'pendiente' appears twice; keep only the one next to Xiaohei and erase the other" / "fix the spelling of the label 'revison' to 'revisión'" / "make Xiaohei hold the lever instead of standing beside it"}.
Fill any erased area with the same clean pure white background. Preserve everything else exactly: Xiaohei, the other labels, the line style, the colors, the composition, the 16:9 aspect ratio and the image quality. Do not add any new text, title, number or object.
```

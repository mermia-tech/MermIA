# 12 - Mensajes de ejemplo del agente

> Weekly report by default (daily as opt-in): per 04 the WhatsApp cost gap is only ~US$0.22/restaurant/month, so habit decides, and one Monday-morning summary is easier to keep reading than seven; real margin breaches still go out the same day.

Restaurante de ejemplo: **Taquería El Güero**, 2 sucursales (Centro y Polanco). Dueño: Carlos. Gerentes: Laura (Centro) y Miguel (Polanco). Fechas: octubre 2026.

**Etiquetas de cada mensaje**
- **[Plantilla utility]**: plantilla aprobada por Meta. Se puede mandar con la ventana cerrada (cuesta MXN 0.1565) y es gratis si la ventana de 24 h está abierta. Solo datos de la cuenta, sin recomendaciones.
- **[Libre en ventana]**: mensaje libre (o interactivo con botones) dentro de la ventana de 24 h que abrió el usuario. Cuenta como mensaje de servicio.
- **(sin LLM)**: lo arma el código con una plantilla de texto; **(LLM)**: lo redacta el modelo con números que vienen de nuestras herramientas.
- Botones: máximo 3, máximo 20 caracteres cada uno.

---

## 1. Reporte semanal proactivo

### 1a. Plantilla `reporte_semanal` [Plantilla utility] (sin LLM)
Lunes 12 oct, 9:00.

> 📊 *Resumen semanal de Taquería El Güero*
> Semana del 5 al 11 de octubre
>
> Ventas: *$412,860.00* (+4.3% vs semana anterior)
> Tickets: 2,184 · Ticket promedio: $189.04
> Más vendido: Tacos al pastor (1,846 órdenes)
> Platillos con costo arriba de tu meta: 3
>
> Toca un botón para ver el detalle.
>
> `[Ver márgenes]` `[Por sucursal]` `[Ver detalle]`

Variables: nombre, fechas, ventas, % de cambio, tickets, ticket promedio, platillo, número de platillos. Sin sugerencias de precio en la plantilla (eso la volvería marketing).

### 1b. El dueño toca `Ver márgenes` [Libre en ventana] (sin LLM)

> Estos 3 platillos ya pasaron tu meta de costo (32%) 👇
>
> *1. Costra de pastor* — costo $29.80, precio $89.00 → *38.8%*
> Si la subes a *$95.00* (+6.7%) quedaría en 36.4%.
> ⚠️ Receta estimada (la capturamos por chat). ¿La revisamos?
>
> *2. Orden de bistec* — costo $27.90, precio $85.00 → *38.1%*
> El bistec subió 12.2%: de $189.00 a $212.00 el kilo (factura de Carnes San Juan, 8 oct).
> A *$90.00* (+5.9%) quedaría en 36.0%. Para llegar a 32% tendría que costar $101; quizá conviene revisar la porción.
>
> *3. Gringa de pastor* — costo $24.60, precio $79.00 → *36.1%*
> A *$85.00* (+7.6%) quedaría en 33.6%.
>
> Son sugerencias, no cambio nada sin tu OK.
>
> `[Cambiar precios]` `[Revisar recetas]` `[Así déjalo]`

---

## 2. Preguntas del dueño

### 2a. "¿Cuánto vendimos ayer?" [Libre en ventana] (sin LLM: pregunta frecuente con respuesta de plantilla)
Miércoles 14 oct.

> Ayer, martes 13 de octubre, vendiste *$58,940.50* 💰
> • Centro: $34,210.00
> • Polanco: $24,730.50
>
> Tickets: 311 · Promedio: $189.52
> Contra el martes pasado: +6.1% ($55,550.00)
>
> _Según los reportes de Productos vendidos del 13 oct._

### 2b. "¿Qué platillo me deja menos?" [Libre en ventana] (LLM)

> Depende de cómo lo midas:
>
> • *En porcentaje*, el que peor está es la *Costra de pastor*: el costo se lleva el 38.8% del precio (tu meta es 32%).
> • *En pesos por pieza*, de los que pasan tu meta, la *Gringa de pastor* es la que menos te deja: $43.50 (precio sin IVA menos costo).
>
> Ojo: la receta de la costra es estimada. Si me confirmas cuánta carne y queso lleva, el número queda exacto.
>
> `[Confirmar receta]` `[Ver todos]`

### 2c. "¿Por qué bajaron las ventas en Polanco?" [Libre en ventana] (LLM)

> La causa no la puedo saber (clima, obras, competencia), pero esto es lo que muestran tus datos de la semana pasada:
>
> 📉 Polanco vendió *$171,320.00*, -9.8% vs la semana anterior ($189,930.00).
> • Bajaron los tickets: 902 vs 1,025 (-12.0%).
> • El ticket promedio subió: $189.93 vs $185.30 (+2.5%).
> • Casi toda la baja fue el *viernes 9*: $28,410.00 vs $39,880.00 (-28.8%).
>
> También subieron las cancelaciones: 14 vs 5, por $3,245.00 en total. 9 se registraron con el usuario de Juan.
>
> ¿Quieres ver el detalle de esas cancelaciones?
>
> `[Ver cancelaciones]` `[Comparar sucursales]`

---

## 3. Cambio que pide confirmación

Miércoles 14 oct, 13:40. Carlos escribe: *"oye ya me subieron el bistec, ahora me lo dan a 225 el kilo"*

### 3a. Propuesta [Libre en ventana] (LLM detecta la intención; el texto lo arma el código)
Si la ventana estuviera cerrada (por ejemplo, un cambio propuesto por un gerente), se manda como plantilla `cambio_pendiente` [Plantilla utility].

> ✏️ *Cambio pendiente* (todavía no se guarda)
>
> *Ingrediente:* Bistec de res (kg)
> *Costo actual:* $212.00
> *Costo nuevo:* $225.00 (+6.1%)
> *Desde:* hoy, 14 oct
>
> *Platillos que cambian:*
> • Orden de bistec: $27.90 → $29.46 (food cost 38.1% → 40.2%)
> • Alambre de bistec: +$2.34 por orden
> • Taco de bistec: +$0.46 por taco
>
> Este cambio vence mañana a las 13:40 si no lo confirmas.
>
> `[Confirmar]` `[Cancelar]` `[Editar]`

### 3b. Carlos toca `Confirmar` [Libre en ventana] (sin LLM)

> ✅ *Guardado.* Bistec de res: $225.00 el kilo desde el 14 oct.
> Aprobó: Carlos (dueño), 14 oct 13:42.
>
> Ya recalculé los 3 platillos. Si fue un error, escríbeme "deshacer" y te pido confirmar de nuevo.

### 3c. Carlos toca `Editar` [Libre en ventana] (sin LLM)

> Va. ¿Cuál es el costo correcto por kilo del bistec? Escríbelo así: *218.50*

Luego se repite la propuesta 3a con el nuevo valor.

### 3d. Carlos toca `Cancelar` [Libre en ventana] (sin LLM)

> Listo, no cambié nada. El bistec sigue en $212.00 el kilo.

### 3e. Venció sin respuesta [Libre en ventana si sigue abierta; si no, plantilla `cambio_resuelto`, utility] (sin LLM)

> ⌛ El cambio del bistec ($212.00 → $225.00) venció sin confirmarse. No se guardó nada.
> Si todavía aplica, vuelve a decirme el precio.

### 3f. Alguien toca un botón viejo (sin LLM)

> Ese cambio ya se resolvió el 14 oct a las 13:42 (lo confirmó Carlos). No hice nada más.

---

## 4. Onboarding del gerente que sube reportes

### 4a. Al dueño, después de dar de alta a Laura [Libre en ventana] (sin LLM)
El alta de Laura es un cambio y pasa por confirmación (como en 3a). Para no mandarle a Laura un mensaje en frío (que Meta podría tratar como marketing), le pedimos al dueño que le reenvíe un enlace. Cuando Laura escribe, se abre su ventana.

> Listo, Laura ya puede mandar reportes de *Centro*. 🙌
> Reenvíale este mensaje para que me escriba:
>
> 👉 wa.me/52XXXXXXXXXX?text=Hola%20MermIA%2C%20c%C3%B3digo%20GUERO-4821

### 4b. Laura escribe "Hola MermIA, código GUERO-4821" → bienvenida [Libre en ventana] (sin LLM)

> ¡Hola Laura! 👋 Soy MermIA, el asistente de Taquería El Güero.
> Carlos te dio acceso para mandarme los reportes de ventas de *Centro*. Con ellos le preparo sus números de la semana.
>
> Antes de empezar: guardamos tu nombre, tu número y los archivos que mandes, solo para este servicio. Aviso de privacidad: mermia.mx/privacidad
>
> `[Acepto]` `[Ver aviso]`

### 4c. Laura toca `Acepto` → cómo mandar el reporte [Libre en ventana] (sin LLM)
La ruta del menú es del manual de SR 8.0; hay que confirmarla con la versión del piloto.

> ¡Gracias! Tu tarea es una sola, todos los días después del corte:
>
> *1.* En Soft Restaurant: *Reportes → Productos vendidos en general*
> *2.* Periodo: el día que cerraste
> *3.* Destino: *Excel* → guárdalo
> *4.* Mándamelo por aquí como *documento* 📎 (desde la compu con WhatsApp Web o Desktop es más fácil)
>
> Tarda como 1 minuto. Si un día no hubo venta, solo toca el botón que te mando al otro día.
> ¿Me mandas el de ayer para probar?

### 4d. Reporte correcto [Libre en ventana] (sin LLM)

> ✅ Recibí *Productos vendidos* de *Centro*, lunes 12 oct.
> 46 platillos · 612 piezas · ventas *$31,880.00*
>
> ¿Cuadra con tu corte de ese día?
>
> `[Todo bien]` `[Algo no cuadra]`

Días después, con racha:

> ✅ Listo, martes 13 oct: ventas $34,210.00. Llevas 5 días seguidos 💪

### 4e. Manda una foto en lugar del archivo [Libre en ventana] (sin LLM para el texto; la lectura de la foto usa visión)

> ¡Gracias! 📷 Me llegó una *foto*. Para que los números salgan exactos necesito el *archivo de Excel* (pasos: Reportes → Productos vendidos en general → Excel).
>
> Si hoy no puedes, leo la foto, pero esos números quedarán marcados como *aproximados* hasta que llegue el archivo.
>
> `[Mando el archivo]` `[Lee la foto]`

Si toca `Lee la foto`:

> Leí esto en la foto: ventas *$31,880.00*, 612 piezas, lunes 12 oct. ¿Es correcto?
>
> `[Sí, es correcto]` `[No]`

### 4f. Manda otro reporte [Libre en ventana] (sin LLM)

> Este archivo es el *Corte de caja* del 12 oct. Lo guardo para comparar totales 👍, pero el que necesito es *Productos vendidos en general* (trae cada platillo).
> ¿Me lo mandas también?

Si el archivo no se reconoce:

> Mmm, no reconocí este archivo 🤔 (_ventas_octubre_final.xlsx_). No cargué nada.
> El que necesito es *Productos vendidos en general* exportado a Excel. Si tienes dudas, escríbeme "ayuda" y te contacta una persona.

### 4g. Duplicado o corrección [Libre en ventana] (sin LLM)

Mismo archivo:

> Este reporte del 12 oct ya lo tenía (es el mismo archivo). No lo volví a cargar 👍

Mismo día, cifras distintas:

> Ya tenía un reporte de Centro del 12 oct, pero este trae otra cifra: $31,880.00 → *$32,410.00*.
> ¿Lo reemplazo?
>
> `[Reemplazar]` `[Dejar el anterior]`

### 4h. Recordatorio cuando no llega el reporte [Plantilla utility `recordatorio_reporte`] (sin LLM)
Martes 11:00, si no llegó el del lunes.

> Hola Laura, todavía no recibo el reporte de ventas de *Centro* del *lunes 12 oct*. Puedes mandarlo por aquí cuando puedas.
>
> `[Lo mando ahora]` `[Hoy no hubo venta]`

### 4i. Aviso al dueño después de 2 días sin reporte [Plantilla utility `reporte_faltante`] (sin LLM)

> Hola Carlos, no hemos recibido los reportes de *Polanco* del *12 y 13 oct*. El resumen de esa sucursal saldrá incompleto hasta que lleguen.
>
> `[Avisar a Miguel]` `[Está bien]`

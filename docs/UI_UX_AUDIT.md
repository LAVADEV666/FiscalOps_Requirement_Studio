# Auditoría y optimización UI/UX de FiscalOps

Implementación y validación: 6 de noviembre de 2026.

## Hallazgos y correcciones

| Hallazgo | Cambio implementado |
| --- | --- |
| Portada larga con hero, ilustración y secciones apiladas | Espacio de trabajo limitado al viewport, con importación PDF como vista inicial y cinco pestañas de acceso directo |
| Ancho mínimo de 780 px y herramientas superpuestas en ventanas pequeñas | Capa responsiva compartida, controles compactos, pestañas con desplazamiento propio y alternancia PDF/expediente en móvil |
| Solo cinco sesiones recientes y empresas sin acceso a sus registros | Biblioteca completa con búsqueda, filtros, orden, favoritos, grupos, archivo y paginación ajustada a la altura disponible |
| Respaldo descargable sin biblioteca local de copias | Catálogo de resguardos persistentes, verificación SHA-256, descarga, nombres editables, archivo y restauración en sesiones nuevas |
| Tarjetas corporativas sin personalización | Portadas PNG normalizadas, iconos corporativos con emojis, fondos configurables y posibilidad de ocultar la portada sin borrarla |
| Salida de WordCraft mediante descarte o cierre del iframe | Documento conservado en memoria al volver, botón visible para retomarlo, guardado y recuperación independientes de la navegación interna |
| Depuración con validador escrito y sin acceso directo por sesión | Tache directo con Deshacer, depuración por selección sin escribir confirmaciones y papelera recuperable; eliminación definitiva como segunda acción con botones |
| Portada registrada visible solo en la biblioteca de empresas | Identidad compartida por RFC en expediente, Estudio Word, WordCraft, biblioteca de plantillas, diseñador y vista previa |
| Símbolo estático y controles desplegables genéricos | Motor SSGT con aceleración y frenado, estela del PNG adjunto, acentos púrpura/cian y desplegables nativos estilizados |
| Antigüedad basada solo en el modelo OCR | Última actividad considera también el DOCX de WordCraft y la organización del expediente; cambios posteriores a la revisión invalidan la selección |
| Selección inválida que podía dejar habilitado un archivo anterior | Reinicio de archivo y controles; procesamiento bloqueado hasta seleccionar un PDF válido |
| Finalización de un PDF que podía interrumpir otra tarea | Notificación y acceso al expediente terminado cuando el usuario está en otra pestaña o tiene un formulario abierto |

## Diseño y accesibilidad

- Se utiliza el PNG HD original de SSGT y la firma Powered by FiscalOps. El símbolo adjunto se conserva byte por byte en `static/ssgt-symbol.png`; CSS y canvas lo encuadran sin modificar el archivo. Se mantienen fuera las grandes áreas promocionales.
- Tipografía de sistema, jerarquía compacta, bordes discretos, alineación común y controles coherentes entre pantallas.
- La página ocupa `100dvh` y no tiene scroll vertical u horizontal. Los documentos y contenidos extensos se leen dentro de paneles acotados; las listas principales usan paginación adaptable.
- Navegación principal con roles de pestaña, estado seleccionado y navegación por flechas, Inicio y Fin. Los estados de guardado, errores y operaciones se anuncian mediante regiones de estado.
- Se respeta la preferencia de movimiento reducido. Animaciones y estela tienen controles persistentes en Ajustes. El motor acelera al iniciar el trabajo y frena hasta detenerse; el bucle de animación descansa sin actividad. La estela tiene un máximo de 26 partículas por superficie, desaparece en 620 ms, libera su buffer en reposo y no captura clics ni aparece durante el arrastre de texto. Los controles conservan foco visible y nombres accesibles.
- En teléfonos, el editor principal alterna PDF y expediente. El resumen y el estado de guardado siguen accesibles. WordCraft conserva su cinta contextual; los comandos del resumen nativo se acceden mediante Vista y Revisar cuando se compacta su barra inferior.
- Se conservan búsqueda, filtros, orden, densidad y navegación en el navegador. Organización de sesiones, apariencia corporativa y resguardos se persisten en el almacenamiento local de la aplicación.

## Protección de información

No hay tareas de depuración automática ni operaciones destructivas durante la carga de bibliotecas. Archivar solo cambia la organización del registro.

El tache (×) retira una sesión directamente, incluyendo las recientes, sin confirmación escrita. Deshacer la recupera. Para varias sesiones se revisa una lista, se seleccionan registros y se pulsa Retirar seleccionadas, sin validador. Una antigüedad de 0 muestra todas. La papelera conserva los archivos e identificadores; retirar no libera espacio por sí solo. Si una sesión cambia en otra ventana después de cargar la lista, se conserva y se pide actualizar esa lista.

Eliminar definitivamente requiere un registro ya retirado y una segunda acción con botones Cancelar/Eliminar, sin escribir un validador. La API exige confirmación y coincidencia del identificador; valida que la ruta sea un hijo directo de la papelera antes de eliminarla. Empresas, sesiones activas y resguardos independientes no pueden seleccionarse mediante esa acción.

Volver de WordCraft conserva el mismo iframe y su estado. Los reemplazos atómicos toleran bloqueos breves de archivo en Windows mediante reintentos acotados. Los fallos de guardado mantienen una copia de los bytes pendientes para reintento o descarga. La navegación o recarga del navegador mantiene la advertencia de cambios pendientes. Las ediciones profesionales siguen separadas del modelo OCR; el cambio de interfaz no altera ese contrato.

## Validación

- Suite completa: **106 pruebas aprobadas, 1 omitida**. La omitida requiere el PDF externo configurado mediante `FISCALOPS_REAL_TEST_PDF`; no se utilizó documentación fiscal privada para sustituirlo.
- Matriz en Chrome: **90 estados de pantalla**, sin errores de JavaScript ni desbordamientos del viewport. Incluye las cinco pestañas iniciales y los cinco módulos del expediente en 1920×1080, 1440×900, 1366×768, 1024×768, 800×600, 768×1024, 390×844, 360×640 y 320×568.
- Flujo real con PDF generado para la prueba: arrastrar/soltar, extracción de dos numerales, apertura del expediente, descarga DOCX, lectura por zonas y creación de resguardo local.
- Biblioteca: búsqueda y organización persistentes, personalización PNG y emoji, consulta de sesiones por empresa, creación/archivo/restauración de resguardos y conservación del expediente original.
- Depuración: tache de una sesión recién creada sin validadores, Deshacer, selección de todas las sesiones con antigüedad 0 y recuperación de todo el lote. Se mantiene la regresión de aislamiento de rutas, concurrencia y conservación de resguardos independientes.
- Efectos: PNG original como partículas reales, aceleración y parada del motor, liberación de canvas al terminar la estela, preferencias persistentes y desactivación por movimiento reducido. Desplegables con selección real y teclado comprobados.
- Portadas: misma URL y hash de portada en expediente, Estudio Word, plantillas, diseñador y WordCraft; comprobadas también en vista móvil.
- WordCraft: ocupación exacta del viewport, edición real, retorno sin guardar, reapertura del mismo documento, guardado de los cambios, fallo simulado, retorno con el fallo pendiente y recuperación mediante reintento. Descarga e indicadores comprobados en móvil.
- Procesamiento en segundo plano: un formulario abierto conserva su contenido al terminar el PDF. Una selección posterior de archivo inválido desactiva el procesamiento.

Todas las pruebas de integración utilizaron carpetas aisladas en `.build-checks`, puertos de prueba y registros ficticios. No se depuraron datos de operación. Los scripts, resultados y capturas de la validación se conservan allí y se excluyen del paquete de distribución.

## Archivos principales

- `static/index.html`, `static/index.js`, `static/home-library.js`: interfaz inicial, bibliotecas y flujos.
- `static/premium.css`, `static/neon.css`: sistema visual, acentos, desplegables y adaptación a resoluciones.
- `static/company-identity.js`: componente compartido de portada y apariencia por RFC.
- `static/fiscal-motion.js`, `static/ssgt-symbol.png`: motor, estela y preferencias visuales.
- `static/audit.html`, `static/audit.js`, `static/wordcraft.js`: editor principal, controles móviles y ciclo de vida de WordCraft.
- `backup_store.py`, `enterprise_store.py`, `maintenance.py`, `persistence.py`, `app.py`: persistencia, portadas, resguardos y protecciones.
- `tests/test_premium_library.py`: regresión de los nuevos contratos de datos y seguridad de las acciones.

Reiniciar FiscalOps carga las rutas nuevas de la API. Los archivos estáticos se sirven sin caché; no se requiere reinstalar dependencias para este cambio. La construcción portable incluye el módulo nuevo y todos los recursos de interfaz.

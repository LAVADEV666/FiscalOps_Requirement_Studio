# FiscalOps Requirement Studio - Changelog

## Mantenimiento de v8.0.1

- Agrega motor SSGT que acelera al cargar y frena al terminar, firma Powered by FiscalOps, acentos cian/púrpura y estela del mouse con el PNG original proporcionado.
- Incorpora preferencias visuales persistentes, movimiento reducido y efectos sin captura de clics o selección de texto.
- Estiliza los desplegables nativos y sus menús donde el navegador admite selectores personalizables.
- Unifica la portada registrada por RFC entre biblioteca, editor, WordCraft y todas las vistas de plantillas.
- Conserva accesible Retomar WordCraft dentro del cuadro de diálogo activo.

- Rediseña la interfaz Premium con el logo HD original de SSGT, cinco espacios de trabajo, uso completo del viewport y adaptación a escritorio, tablet y teléfono.
- Agrega búsqueda, filtros, favoritos, grupos, archivo y paginación adaptable para expedientes; conserva preferencias en el navegador.
- Incorpora portadas PNG, emojis corporativos y fondos configurables para empresas, junto con acceso a sus expedientes y sesiones.
- Agrega un catálogo persistente de resguardos ZIP verificados, restauración en sesiones nuevas y organización de copias.
- Agrega tache de retiro directo y Deshacer; permite depuración por selección sin validadores escritos y mantiene la papelera recuperable. La eliminación definitiva es una segunda acción explícita.
- Mantiene WordCraft montado al volver al editor principal, con regreso inmersivo, cambios pendientes y recuperación de guardados fallidos.
- Evita procesar una selección inválida y evita interrumpir formularios cuando termina una importación en segundo plano.

- Integra WordCraft web 0.14.0 local con apertura, guardado DOCX, recuperación y detección de conflictos; conserva el escrito profesional en cada expediente.
- Activa creación de plantillas en blanco o carta, vistas previas DOCX y biblioteca visual con icono/color por RFC.
- Agrega colocación del rectángulo OCR y borde opcional en plantillas, manteniendo el punto de inserción de numerales y elementos visuales.
- Incluye dependencias web y sus licencias en el paquete portable, sin descargas durante el uso.

- Agrega ejecución nativa en Python 3.13.14 x64 con PaddleOCR 3, modelos móviles y lanzadores que detectan el runtime local.

- Incorpora interfaz de escritorio SSGT, plantillas por RFC y relectura local de zonas del PDF.
- Unifica el arranque y las pruebas en `.venv-ocr` y elimina el código heredado de motores OCR desactivados.
- Excluye datos locales del control de versiones, limita el tamaño de los registros y evita duplicar el PDF de las cargas completadas.

## v8.0.1 Stable
- Corrige la regresión fatal de la segunda pantalla por paneles faltantes.
- Agrega los contenedores IA, OCR, Evidencias y Cumplimiento.
- Hace defensivos los renderizadores opcionales.
- Actualiza versionado y cache busting de recursos.
- Valida el flujo completo con el PDF COVASA de 16 páginas.
- Depura archivos históricos y componentes obsoletos del paquete.

## v8.0.0 Stable
- Motor documental canónico, Word auditado, multiempresa, matriz SAT, evidencias, OCR robusto, IA controlada y procesamiento asíncrono.

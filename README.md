# Listado de centros educativos de Canarias

Conjunto de datos abierto, versionado y actualizado automáticamente que parte del listado oficial de centros educativos del Gobierno de Canarias y lo enriquece con información que no está disponible, está incompleta o aparece separada en otros conjuntos de datos.

**Sitio web y documentación:** https://ateeducacion.github.io/listado-centros-educativos-canarias/

## Objetivo

El archivo [`centros.csv`](centros.csv), situado en la raíz del repositorio, reúne en un único recurso:

- los datos generales de los centros educativos publicados en el portal de datos abiertos de Canarias;
- el Centro del Profesorado (CEP) asociado, incluido su código;
- el Colectivo de Escuelas Rurales (CER), cuando corresponda;
- el Equipo de Orientación Educativa y Psicopedagógico (EOEP), cuando esté disponible;
- la zona de inspección educativa obtenida del conjunto de datos oficial de zonas de inspección;
- los CEP, CER, EOEP y oficinas Medusa como registros del mismo listado, identificados mediante su tipo de centro.

Este repositorio es una solución temporal de enriquecimiento mientras las fuentes oficiales no incluyan todos estos datos de forma completa y coherente.

> Este proyecto no constituye una publicación oficial ni sustituye a los conjuntos de datos del Gobierno de Canarias. Cada dato conserva su procedencia y el proceso de transformación es reproducible.

## Archivo principal

```text
centros.csv
```

Los códigos de centro se tratan siempre como texto para conservar los ocho dígitos. El archivo se publica en UTF-8 y usa coma como separador.

Entre las columnas añadidas o normalizadas se encuentran:

| Columna | Descripción |
|---|---|
| `CentroProfesoresCodigo` | Código del CEP asociado. |
| `CentroProfesoresNombre` | Denominación normalizada del CEP. |
| `URLWebCEP` | Sitio web del CEP, cuando está disponible. |
| `CentroCER` | CER asociado, cuando corresponde. |
| `EOEP` | EOEP publicado o recuperado de las fuentes de apoyo. |
| `ZonaInspeccionCodigo` | Código de la zona de inspección. |
| `ZonaInspeccionNombre` | Denominación de la zona de inspección. |
| `FuenteCEP` | Procedencia de la asignación del CEP. |
| `FuenteZonaInspeccion` | Procedencia de la zona de inspección. |
| `Activo` | `1` si el centro está vigente y `0` si se conserva solo por trazabilidad histórica. |
| `FechaAlta` / `FechaBaja` | Vigencia conocida cuando una fuente oficial permite determinarla. |
| `CodigoSustituidoPor` | Código del centro que sustituye a uno dado de baja. |
| `FuenteCentro` | Procedencia del registro base. |
| `FuenteEstado` / `FuenteEstadoURL` | Fuente pública usada para una corrección de vigencia. |

No se publica el nombre de la persona inspectora. Solo se incorpora la identificación de la zona de inspección.

## Fuentes

La generación consulta, como mínimo, los siguientes conjuntos de datos:

1. **Centros Educativos de Canarias**, publicado en el portal de datos abiertos del Gobierno de Canarias.
2. **Zonas de Inspección Educativa de Canarias**, del que se utilizan la relación entre centros y zonas y el catálogo de zonas.
3. Datos de apoyo mantenidos en este repositorio para completar las asignaciones de CEP que todavía no ofrece la fuente principal.
4. Correcciones de vigencia revisadas y versionadas cuando el BOC o el directorio oficial de centros se adelantan a la publicación de OpenData.

El BOC se usa como **detector de posibles cambios**, no como una fuente que modifique el catálogo de forma automática. El workflow genera un informe y cualquier corrección se incorpora de forma explícita con su procedencia.

La automatización localiza los recursos mediante la API CKAN del portal, evitando depender permanentemente de identificadores de recurso concretos.

## Generación

```sh
python -m pip install -r requirements.txt
python scripts/update_data.py
python scripts/validate_data.py
python scripts/export_consumers.py
python scripts/check_boc.py
```

El proceso realiza estas operaciones:

1. descarga los recursos oficiales actuales;
2. normaliza códigos, encabezados y valores;
3. cruza cada centro con su zona de inspección mediante el código oficial;
4. completa los datos de CEP con la tabla curada;
5. conserva los datos de EOEP y CER disponibles;
6. incorpora los servicios educativos que deban formar parte del listado único;
7. aplica únicamente correcciones de estado revisadas y con fuente pública;
8. genera `centros.csv` y `centros.json`;
9. valida códigos, duplicados, sustituciones, relaciones y estructura;
10. genera contratos reducidos para otros aplicativos;
11. comprueba publicaciones recientes del BOC y genera un informe de posibles desfases.

## Actualización automática

El workflow nocturno consulta las fuentes oficiales. Cuando detecta cambios:

- regenera los archivos;
- ejecuta las validaciones;
- crea una rama automática;
- abre o actualiza un pull request con el resumen de altas, bajas y modificaciones.

Los cambios no se incorporan directamente a `main`: deben revisarse y fusionarse mediante pull request.

## Contratos para otros aplicativos

GitHub Pages publica, además del conjunto completo:

- `centros.min.json`: catálogo ligero con código, denominación, isla, municipio, tipo y estado; pensado para formularios y aplicaciones web.
- `centros-distancias.csv`: únicamente centros activos con coordenadas válidas, con el esquema que necesita el proyecto de distancias.
- `manifest.json`: versión de esquema, recuentos y SHA-256 de los artefactos anteriores.

Los consumidores deben usar estos contratos en lugar de volver a consultar directamente las fuentes upstream.

## Sitio web

La documentación de GitHub Pages explica las fuentes, el modelo de datos y el proceso de actualización. También permite buscar y filtrar el contenido de `centros.csv` desde el navegador.

## Limitaciones

- Las asignaciones de CEP procedentes de datos de apoyo pueden quedar desactualizadas si se modifica el ámbito territorial de un CEP.
- Algunos centros pueden no tener zona de inspección en el conjunto oficial.
- La ausencia de un valor no implica necesariamente que el servicio no exista; puede indicar que la fuente no lo publica.
- Las transformaciones automáticas no corrigen silenciosamente conflictos: se registran como errores o advertencias para su revisión.

## Cita

La forma recomendada de citar el conjunto de datos es:

> Área de Tecnología Educativa. *Listado de centros educativos de Canarias*. Conjunto de datos derivado y enriquecido a partir de fuentes del Gobierno de Canarias. https://github.com/ateeducacion/listado-centros-educativos-canarias

También se incluye el archivo [`CITATION.cff`](CITATION.cff), compatible con la función **Cite this repository** de GitHub.

## Licencia y atribución

El repositorio se distribuye bajo **Creative Commons Attribution 4.0 International (CC BY 4.0)**. El texto de la licencia está en [`LICENSE`](LICENSE).

La elección de CC BY 4.0 permite reutilizar la base de datos, la documentación y las transformaciones, pero obliga a conservar la atribución y a indicar los cambios. Esto es adecuado para un conjunto derivado de fuentes públicas que también requieren reconocimiento de procedencia.

Atribución de las fuentes:

> Información elaborada utilizando, entre otras, la obtenida del Gobierno de Canarias. Los datos han sido transformados y enriquecidos; esta publicación no es oficial ni implica respaldo del Gobierno de Canarias.

Al reutilizar los datos debe conservarse también la referencia al conjunto oficial de origen y la fecha de la versión utilizada.
# ETABS MCP

Servidor MCP que conecta a Claude Code con la sesión **abierta** de ETABS para leer y
entender el modelo completo: pisos, ejes, materiales, secciones, cargas, casos,
combinaciones y, si está analizado, resultados.

## Estado — v0.1 (2026-10-06)

- Funcionando de punta a punta, probado contra `CL132.EDB` (Lote 132 – Loma Reserva) en ETABS 23.2.
- Registrado en Claude Code a nivel de usuario como `etabs` (`claude mcp get etabs`).
- **Solo lectura.**
- Repo privado `ZafiroSad/ETABS-MCP`, rama `master`.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `etabs_estado` | Versión, archivo, unidades, bloqueo, estado del análisis, conteos |
| `etabs_resumen` | Panorama: pisos, elementos por piso, materiales, secciones (cantidad, longitud, pisos), áreas, patrones, casos con estado, combos |
| `etabs_tablas` | Lista las tablas de Display > Show Tables (las de resultados solo si está analizado) |
| `etabs_tabla` | Lee cualquier tabla como filas; filtra, limita y elige casos/combos para resultados |
| `etabs_metodos` | Firmas de los métodos de una interfaz de la API (`FrameObj`, `PropFrame`, `Results`…) |
| `etabs_consultar` | Llama cualquier método `Get*`/`Count*` de la API; rechaza todo lo demás |

## Arquitectura

```
server.py              entrada (la lanza Claude Code por stdio con el python del .venv)
etabs_mcp/conexion.py  carga ETABSv1.dll con pythonnet (CoreCLR), se engancha a la instancia
                       abierta y trae el invocador genérico por reflexión
etabs_mcp/servidor.py  herramientas MCP (SDK mcp 2.x: MCPServer, no FastMCP)
```

## Decisiones

- **API .NET, no COM.** La ProgID `CSI.ETABS.API.ETABSObject` no está registrada en este
  equipo; `cHelper.GetObject` sobre `ETABSv1.dll` funciona sin registrar nada.
- **Invocador genérico.** La reflexión .NET dice el tipo de cada parámetro; se rellenan
  solos los de salida y se llama directo con pythonnet, que devuelve `(ret, salidas…)`.
  Se refleja sobre la interfaz (`clr.GetClrType(type(obj))`), no sobre el proxy COM.
  Los tipos se comparan por `FullName`, nunca con `==` contra `System.String`.
- **Unidades:** por defecto kN-m-C. Se cambian durante la consulta y se restauran
  (verificado: el modelo vuelve a N_mm_C).
- **Solo lectura por diseño.** Escribir en el modelo queda para una fase aparte, con el
  protocolo respaldo → cambiar → verificar → no guardar.
- Columnas/vigas en el resumen se clasifican por geometría (vertical = columna).

## Problemas conocidos y pendientes

- El nombre `Fa-Inundación` sale como `Fa-Inundaci�n`: el texto ya viene dañado desde el
  propio modelo de ETABS, no lo introduce el MCP.
- El entorno reducido de un cliente MCP rompía la carga de .NET (`Could not find
  ProgramFiles`); resuelto fijando `ProgramFiles` y `dotnet_root` en `conexion.py`.
- Ruta de ETABS fija a la v23 (variable `ETABS_RUTA` para cambiarla).
- Pendiente: herramientas de resultados directas (derivas, cortante basal, modos) una
  vez el modelo esté analizado; fase de escritura.

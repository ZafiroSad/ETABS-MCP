"""Servidor MCP de ETABS: lectura del modelo abierto.

Herramientas de SOLO LECTURA. La unica alteracion temporal es cambiar las
unidades de trabajo durante una consulta y restaurarlas al terminar.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from contextlib import contextmanager

from mcp.server.mcpserver import MCPServer

from .conexion import E, System, firmas, invocar, modelo, resolver

mcp = MCPServer(
    "etabs",
    instructions=(
        "Lee el modelo abierto en ETABS. Empezar por etabs_resumen; para "
        "cualquier dato que no traiga, usar etabs_tablas + etabs_tabla (son "
        "las mismas tablas de Display > Show Tables). etabs_consultar llama "
        "cualquier metodo Get de la API. Unidades por defecto: kN, m, C."
    ),
)

ESTADO_CASO = {1: "sin correr", 2: "no terminado", 3: "no corrio", 4: "terminado"}
UNIDADES_DEFECTO = "kN_m_C"


@contextmanager
def unidades(nombre: str | None):
    """Cambia las unidades mientras dura la consulta y las restaura."""
    m = modelo()
    if not nombre:
        yield str(m.GetPresentUnits())
        return
    previas = m.GetPresentUnits()
    m.SetPresentUnits(System.Enum.Parse(E.eUnits, nombre))
    try:
        yield nombre
    finally:
        m.SetPresentUnits(previas)


def _lista(interfaz: str) -> list[str]:
    r = invocar(resolver(interfaz), "GetNameList")
    return r.get("MyName") or r.get("Name") or []


def _r(x: float, n: int = 4) -> float:
    return round(x, n)


# ------------------------------------------------------------------ estado

@mcp.tool()
def etabs_estado() -> dict:
    """Version de ETABS, archivo abierto, unidades, bloqueo y estado del analisis."""
    m = modelo()
    casos = invocar(m.Analyze, "GetCaseStatus")
    estados = Counter(ESTADO_CASO.get(s, s) for s in casos["Status"])
    return {
        "version": invocar(m, "GetVersion")["Version"],
        "archivo": m.GetModelFilename(True),
        "unidades_actuales": str(m.GetPresentUnits()),
        "bloqueado": bool(m.GetModelIsLocked()),
        "analisis": dict(estados),
        "conteo": {
            "puntos": m.PointObj.Count(),
            "porticos": m.FrameObj.Count(),
            "areas": m.AreaObj.Count(),
        },
    }


# ------------------------------------------------------------------ resumen

@mcp.tool()
def etabs_resumen(unidades_trabajo: str = UNIDADES_DEFECTO) -> dict:
    """Panorama completo del modelo: pisos, ejes, materiales, secciones con su
    cantidad y piso, losas/muros, patrones de carga, casos (con estado del
    analisis) y combinaciones.

    unidades_trabajo: nombre de eUnits de ETABS (kN_m_C, kgf_m_C, N_mm_C, tonf_m_C...).
    """
    m = modelo()
    with unidades(unidades_trabajo) as u:
        p = invocar(m.Story, "GetStories_2")
        pisos = [
            {
                "nombre": n,
                "cota": _r(z),
                "altura": _r(h),
                "maestro": maestro,
                "similar_a": sim or None,
            }
            for n, z, h, maestro, sim in zip(
                p["StoryNames"], p["StoryElevations"], p["StoryHeights"],
                p["IsMasterStory"], p["SimilarToStory"],
            )
        ]

        # Porticos: se clasifican por geometria (vertical = columna).
        f = invocar(m.FrameObj, "GetAllFrames")
        por_seccion = defaultdict(lambda: {"columnas": 0, "vigas": 0, "inclinados": 0,
                                           "longitud_total": 0.0, "pisos": set()})
        tipo_por_piso = defaultdict(Counter)
        for i in range(f["NumberNames"]):
            dx = f["Point2X"][i] - f["Point1X"][i]
            dy = f["Point2Y"][i] - f["Point1Y"][i]
            dz = f["Point2Z"][i] - f["Point1Z"][i]
            horiz = math.hypot(dx, dy)
            largo = math.sqrt(dx * dx + dy * dy + dz * dz)
            if horiz < 1e-6 * max(largo, 1):
                clase = "columnas"
            elif abs(dz) < 1e-6 * max(largo, 1):
                clase = "vigas"
            else:
                clase = "inclinados"
            s = por_seccion[f["PropName"][i]]
            s[clase] += 1
            s["longitud_total"] += largo
            s["pisos"].add(f["StoryName"][i])
            tipo_por_piso[f["StoryName"][i]][clase] += 1
        secciones_portico = {
            nombre: {**v, "longitud_total": _r(v["longitud_total"], 2),
                     "pisos": sorted(v["pisos"])}
            for nombre, v in sorted(por_seccion.items())
        }

        # Areas (losas, muros) por propiedad y piso.
        a = invocar(m.AreaObj, "GetNameList")["MyName"]
        areas = defaultdict(lambda: {"cantidad": 0, "pisos": set()})
        for nombre in a:
            prop = invocar(m.AreaObj, "GetProperty", nombre)["PropName"]
            piso = invocar(m.AreaObj, "GetLabelFromName", nombre).get("Story", "")
            areas[prop]["cantidad"] += 1
            areas[prop]["pisos"].add(piso)
        secciones_area = {
            k: {"cantidad": v["cantidad"], "pisos": sorted(v["pisos"])}
            for k, v in sorted(areas.items())
        }

        casos = invocar(m.Analyze, "GetCaseStatus")
        estado_caso = dict(zip(casos["CaseName"], casos["Status"]))

        return {
            "archivo": m.GetModelFilename(True),
            "unidades": u,
            "cota_base": _r(p["BaseElevation"]),
            "pisos": pisos,
            "elementos_por_piso": {k: dict(v) for k, v in tipo_por_piso.items()},
            "materiales": _lista("PropMaterial"),
            "secciones_portico": secciones_portico,
            "secciones_area": secciones_area,
            "patrones_carga": _lista("LoadPatterns"),
            "casos_carga": {
                c: ESTADO_CASO.get(estado_caso.get(c), "?") for c in _lista("LoadCases")
            },
            "combinaciones": _lista("RespCombo"),
        }


# ------------------------------------------------------------------ tablas

@mcp.tool()
def etabs_tablas(filtro: str = "") -> list[str]:
    """Lista las tablas disponibles (Display > Show Tables). Las de resultados
    solo aparecen si el modelo esta analizado. filtro: texto a buscar."""
    t = invocar(modelo().DatabaseTables, "GetAvailableTables")
    return [k for k in t["TableKey"] if filtro.lower() in k.lower()]


@mcp.tool()
def etabs_tabla(
    tabla: str,
    campos: list[str] | None = None,
    filtro: str = "",
    limite: int = 200,
    casos: list[str] | None = None,
    combinaciones: list[str] | None = None,
    grupo: str = "",
    unidades_trabajo: str = UNIDADES_DEFECTO,
) -> dict:
    """Lee una tabla de ETABS como filas.

    tabla: nombre exacto (ver etabs_tablas). campos: columnas a traer (todas si
    se omite). filtro: solo filas que contengan ese texto. limite: maximo de
    filas devueltas. casos / combinaciones: para tablas de resultados, cuales
    mostrar. grupo: restringir a un grupo de ETABS.
    """
    m = modelo()
    db = m.DatabaseTables
    if casos is not None:
        invocar(db, "SetLoadCasesSelectedForDisplay", casos)
    if combinaciones is not None:
        invocar(db, "SetLoadCombinationsSelectedForDisplay", combinaciones)
    with unidades(unidades_trabajo) as u:
        r = invocar(db, "GetTableForDisplayArray", tabla, campos or [], grupo)
    if r["ret"] != 0:
        return {"error": f"ETABS no devolvio la tabla '{tabla}' (codigo {r['ret']})."}
    columnas = r["FieldsKeysIncluded"]
    n = len(columnas)
    datos = r["TableData"]
    filas = [dict(zip(columnas, datos[i:i + n])) for i in range(0, len(datos), n)]
    if filtro:
        f = filtro.lower()
        filas = [x for x in filas if any(f in str(v).lower() for v in x.values())]
    total = len(filas)
    return {
        "tabla": tabla,
        "unidades": u,
        "columnas": columnas,
        "filas_totales": total,
        "filas_devueltas": min(total, limite),
        "filas": filas[:limite],
    }


# ------------------------------------------------------------------ API cruda

@mcp.tool()
def etabs_metodos(interfaz: str = "", filtro: str = "") -> list[str]:
    """Firmas de los metodos de una interfaz de la API (vacio = SapModel).
    Ej.: interfaz='FrameObj', 'PropFrame', 'Results', 'DesignConcrete'."""
    return firmas(interfaz, filtro)


@mcp.tool()
def etabs_consultar(
    interfaz: str,
    metodo: str,
    argumentos: list | None = None,
    unidades_trabajo: str = UNIDADES_DEFECTO,
) -> dict:
    """Llama un metodo de LECTURA de la API (Get*, Count*). Solo se pasan las
    entradas en orden; los parametros de salida se rellenan solos y vuelven
    con su nombre. ret = 0 es exito.
    Ej.: interfaz='PropFrame', metodo='GetRectangle', argumentos=['C50X60C28'].
    """
    if not metodo.startswith(("Get", "Count")):
        return {"error": "Solo se permiten metodos de lectura (Get*, Count*)."}
    with unidades(unidades_trabajo) as u:
        r = invocar(resolver(interfaz), metodo, *(argumentos or []))
    return {"unidades": u, **r}


def main():
    mcp.run()


if __name__ == "__main__":
    main()

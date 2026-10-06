"""Conexion con la sesion abierta de ETABS a traves de su API .NET (ETABSv1.dll).

No usa COM registrado: carga la DLL de la instalacion con pythonnet (CoreCLR)
y se engancha a la instancia que ya esta corriendo.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from pythonnet import load

# Si el cliente MCP lanza el proceso con un entorno reducido, clr_loader no
# encuentra el runtime de .NET; se le indica la ruta explicitamente.
os.environ.setdefault("ProgramFiles", r"C:\Program Files")
load("coreclr", dotnet_root=os.environ.get("DOTNET_ROOT", r"C:\Program Files\dotnet"))

import clr  # noqa: E402  (debe ir despues de load)

RUTA_ETABS = os.environ.get(
    "ETABS_RUTA", r"C:\Program Files\Computers and Structures\ETABS 23"
)
sys.path.append(RUTA_ETABS)
clr.AddReference("ETABSv1")

import ETABSv1 as E  # noqa: E402
import System  # noqa: E402
from System import Array, Object  # noqa: E402

_modelo = None


def modelo():
    """Devuelve cSapModel de la instancia abierta; reconecta si se perdio."""
    global _modelo
    if _modelo is not None:
        try:
            _modelo.GetModelIsLocked()
            return _modelo
        except Exception:
            _modelo = None
    helper = E.cHelper(E.Helper())
    try:
        objeto = helper.GetObject("CSI.ETABS.API.ETABSObject")
    except Exception as exc:
        raise RuntimeError(
            "No hay una sesion de ETABS abierta a la que conectarse."
        ) from exc
    _modelo = objeto.SapModel
    return _modelo


# ---------------------------------------------------------------- conversion

def _defecto(tipo):
    """Valor vacio para un parametro de salida del tipo .NET dado."""
    if tipo.IsArray:
        return System.Array.CreateInstance(tipo.GetElementType(), 0)
    if tipo.FullName == "System.String":
        return ""
    return System.Activator.CreateInstance(tipo)


def _a_net(valor, tipo):
    """Convierte un valor de Python al tipo .NET del parametro."""
    if tipo.IsArray:
        elem = tipo.GetElementType()
        arr = System.Array.CreateInstance(elem, len(valor))
        for i, v in enumerate(valor):
            arr[i] = _a_net(v, elem)
        return arr
    if tipo.IsEnum:
        if isinstance(valor, str):
            return System.Enum.Parse(tipo, valor)
        return System.Enum.ToObject(tipo, int(valor))
    nombre = tipo.FullName
    if nombre == "System.String":
        return str(valor)
    if nombre == "System.Boolean":
        return bool(valor)
    if nombre in ("System.Double", "System.Single"):
        return float(valor)
    return int(valor)


def a_python(valor):
    """Convierte un valor .NET devuelto por la API a tipos de Python."""
    if valor is None:
        return None
    if isinstance(valor, (str, int, float, bool)):
        return valor
    if isinstance(valor, System.Array):
        return [a_python(v) for v in valor]
    if isinstance(valor, System.Enum):
        return str(valor)
    try:
        return float(valor)
    except Exception:
        return str(valor)


# ---------------------------------------------------------------- invocacion

def _tipo(objetivo):
    """Tipo de interfaz .NET (cStory, cFrameObj...) del objeto envuelto.

    objetivo.GetType() devolveria el proxy COM, que no expone los metodos.
    """
    return clr.GetClrType(type(objetivo))

def invocar(objetivo, metodo: str, *entradas: Any) -> dict:
    """Llama un metodo de la API por reflexion.

    `entradas` llena los primeros parametros en orden; el resto (los de
    salida) se rellenan con vacios. Devuelve {"ret": codigo, <nombre>: valor}
    con los nombres reales de los parametros de la API. ret == 0 es exito.
    """
    candidatos = [
        m for m in _tipo(objetivo).GetMethods() if m.Name == metodo
    ]
    if not candidatos:
        raise AttributeError(f"La API no tiene el metodo {metodo}.")
    # Si hay sobrecargas, preferir la que admite exactamente esas entradas
    # con la menor cantidad de parametros.
    candidatos.sort(key=lambda m: len(m.GetParameters()))
    info = next(
        (m for m in candidatos if len(m.GetParameters()) >= len(entradas)),
        candidatos[-1],
    )
    params = list(info.GetParameters())
    args = []
    for i, p in enumerate(params):
        tipo = p.ParameterType
        if tipo.IsByRef:
            tipo = tipo.GetElementType()
        if i < len(entradas) and entradas[i] is not None:
            args.append(_a_net(entradas[i], tipo))
        elif p.HasDefaultValue and not p.ParameterType.IsByRef:
            args.append(p.DefaultValue)
        else:
            args.append(_defecto(tipo))
    # Llamada directa: pythonnet devuelve (ret, salida1, salida2, ...) con
    # los parametros "ref" en orden; la reflexion solo nos dio los tipos.
    resultado = getattr(objetivo, metodo)(*args)
    refs = [p for p in params if p.ParameterType.IsByRef]
    if not refs:
        return {"ret": a_python(resultado)}
    salida = {"ret": a_python(resultado[0])}
    for p, v in zip(refs, resultado[1:]):
        salida[p.Name] = a_python(v)
    return salida


def resolver(ruta: str):
    """'FrameObj' -> SapModel.FrameObj ; '' -> SapModel."""
    obj = modelo()
    for parte in filter(None, ruta.split(".")):
        obj = getattr(obj, parte)
    return obj


def firmas(ruta: str, filtro: str = "") -> list[str]:
    """Lista las firmas de los metodos de una interfaz de la API."""
    obj = resolver(ruta)
    vistos = []
    for m in _tipo(obj).GetMethods():
        if filtro.lower() not in m.Name.lower():
            continue
        ps = ", ".join(
            ("ref " if p.ParameterType.IsByRef else "")
            + (p.ParameterType.GetElementType() if p.ParameterType.IsByRef else p.ParameterType).Name
            + " " + p.Name
            for p in m.GetParameters()
        )
        vistos.append(f"{m.Name}({ps})")
    return sorted(set(vistos))

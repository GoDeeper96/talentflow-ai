import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scoring import anonimizar, calcular, cita_en_texto, _norm  # noqa: E402

METRICAS = [
    {"id": "exp", "nombre": "Experiencia", "importancia": 5, "excluyente": True},
    {"id": "herr", "nombre": "Herramientas", "importancia": 4},
    {"id": "log", "nombre": "Logros", "importancia": 4},
    {"id": "bla", "nombre": "Blandas", "importancia": 3},
    {"id": "idi", "nombre": "Idiomas", "importancia": 2},
]
CV = """Analista de datos en Retail SAC (2021-2024). Construí dashboards en Power BI con DAX.
Automaticé reportes con Python y reduje el tiempo de cierre mensual en 30%.
Coordiné con el equipo comercial. Inglés intermedio."""


def test_ejemplo_del_documento_da_66_7():
    res = [
        {"metrica_id": "exp", "nivel": 4, "cita": "Analista de datos en Retail SAC (2021-2024)"},
        {"metrica_id": "herr", "nivel": 3, "cita": "dashboards en Power BI con DAX"},
        {"metrica_id": "log", "nivel": 2, "cita": "reduje el tiempo de cierre mensual en 30%"},
        {"metrica_id": "bla", "nivel": 2, "cita": "Coordiné con el equipo comercial"},
        {"metrica_id": "idi", "nivel": 1, "cita": "Inglés intermedio"},
    ]
    out = calcular(METRICAS, res, CV)
    assert out["nota"] == 66.67
    assert out["banda"] == "MEDIA"
    assert out["cobertura"] == 100.0


def test_cita_inventada_baja_a_cero():
    res = [{"metrica_id": "exp", "nivel": 4, "cita": "Gerente general de Microsoft"}]
    out = calcular(METRICAS, res, CV)
    exp = out["metricas"][0]
    assert exp["nivel"] == 0 and exp["estado"] == "por verificar"
    assert out["requiere_revision"] is True
    assert out["nota"] == 0


def test_cita_tolera_mayusculas_y_espacios():
    assert cita_en_texto("CONSTRUÍ   dashboards en power bi", _norm(CV))


def test_anonimiza_correo_telefono_dni():
    t = anonimizar("Juan Pérez Rojas\njuan.perez@mail.com 987 654 321 DNI: 45678912\nEdad: 29 años", "Juan Pérez Rojas")
    assert "mail.com" not in t and "987" not in t and "45678912" not in t and "29 años" not in t
    assert "Juan" not in t

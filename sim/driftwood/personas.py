import yaml
from pydantic import BaseModel

from .config import DATA_DIR


class Persona(BaseModel):
    name: str
    age: int
    color: str
    accessory: str
    background: str
    traits: str
    voice: str
    samples: list[str]


def load_personas(path=None) -> list[Persona]:
    raw = yaml.safe_load((path or DATA_DIR / "personas.yaml").read_text(encoding="utf-8"))
    return [Persona.model_validate(p) for p in raw]

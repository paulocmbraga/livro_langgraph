"""Comparação pequena de coerção e validação estrita, separada do núcleo."""
# trecho:comparacao
from pydantic import BaseModel, Field, ValidationError


class Quantidade(BaseModel):
    usuarios: int = Field(ge=0)


def comparar():
    for valor in (80, "80", True, -1):
        resultados = []
        for estrito in (False, True):
            try:
                objeto = Quantidade.model_validate(
                    {"usuarios": valor}, strict=estrito
                )
                resultados.append(objeto.usuarios)
            except ValidationError:
                resultados.append("recusado")
        print(repr(valor), *resultados, sep=" | ")


if __name__ == "__main__":
    comparar()
# fim:comparacao
